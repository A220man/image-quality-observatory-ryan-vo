"""Authenticated image-quality workflows exposed as a documented JSON API."""
from dataclasses import asdict
from typing import Literal
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.auth import authorize
from app.core.errors import AppError
from app.services.metrics import ImageDecodeError, ImageMetrics
from app.services.policy import Policy
from app.services.calibration import calibrate, evaluate_policy
from app.services.grouping import cluster_rows, signature_groups
from app.services.benchmark import run_benchmark
from app.services.catalog import METRICS
from app.services.advisory import explain
from app.services.export import decisions_csv

router = APIRouter(prefix='/api', tags=['Image quality'])


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    blur_min: float = Field(100, ge=0, le=1e8)
    luma_min: float = Field(50, ge=0, le=255)
    luma_max: float = Field(205, ge=0, le=255)
    clip_max: float = Field(.08, gt=0, le=1)
    contrast_min: float = Field(.10, gt=0, lt=1)
    review_margin: float = Field(.15, ge=0, lt=1)

    @model_validator(mode='after')
    def valid_policy(self):
        Policy(**self.model_dump()).validate()
        return self


class LabelInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: Literal['good', 'bad'] | None


def analytics(request: Request, batch: str | None) -> list[dict]:
    catalog = request.app.state.catalog
    if catalog.list(batch=batch, limit=1)['total'] > 5000:
        raise AppError(422, 'analysis_limit', 'Select a batch containing at most 5000 images')
    return catalog.analytics_rows(batch)


@router.get('/health', tags=['Operations'])
def health():
    return {'status': 'ok', 'version': '1.0.0'}


@router.post('/images')
def upload(request: Request, file: UploadFile = File(...), batch: str = Form('default')):
    user = authorize(request, 'reviewer')
    settings = request.app.state.settings
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise AppError(413, 'upload_limit', 'Image exceeds configured upload size limit')
    try:
        image, created = request.app.state.catalog.ingest(content, file.filename or 'image', batch,
                                                         user['subject'], settings.max_image_pixels)
    except (ImageDecodeError, ValueError) as exc:
        raise AppError(422, 'invalid_image', str(exc)) from exc
    return {'image': image, 'created': created}


@router.get('/images')
def images(request: Request, batch: str | None = None,
           decision: Literal['accept', 'review', 'reject'] | None = None,
           limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    authorize(request)
    return request.app.state.catalog.list(batch=batch, decision=decision, limit=limit, offset=offset)


@router.get('/images/{image_id}')
def image(request: Request, image_id: int):
    authorize(request)
    try:return request.app.state.catalog.get(image_id)
    except KeyError as exc:raise AppError(404, 'not_found', 'Image not found') from exc


@router.get('/exports/decisions.csv')
def export_decisions(request: Request, batch: str | None = None):
    authorize(request)
    return Response(decisions_csv(analytics(request, batch)), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="image-quality-decisions.csv"'})


@router.patch('/images/{image_id}/label')
def label(request: Request, image_id: int, body: LabelInput):
    user = authorize(request, 'reviewer')
    try:return request.app.state.catalog.label(image_id, body.label, user['subject'])
    except KeyError as exc:raise AppError(404, 'not_found', 'Image not found') from exc


@router.delete('/images/{image_id}', status_code=204)
def delete(request: Request, image_id: int):
    user = authorize(request, 'admin')
    try:request.app.state.catalog.delete(image_id, user['subject'])
    except KeyError as exc:raise AppError(404, 'not_found', 'Image not found') from exc


@router.get('/policy')
def policy(request: Request):
    authorize(request)
    return request.app.state.catalog.policy().as_dict()


@router.put('/policy')
def update_policy(request: Request, body: PolicyInput):
    user = authorize(request, 'admin')
    return request.app.state.catalog.update_policy(Policy(**body.model_dump()), user['subject'])


@router.get('/analysis/groups')
def groups(request: Request, batch: str | None = None):
    authorize(request)
    return {'groups': [asdict(g) for g in signature_groups(analytics(request, batch))]}


@router.get('/analysis/clusters')
def clusters(request: Request, batch: str | None = None, k: int = Query(3, ge=1, le=12)):
    authorize(request)
    return asdict(cluster_rows(analytics(request, batch), k))


@router.post('/analysis/calibrate')
def calibration(request: Request, batch: str | None = None):
    authorize(request, 'reviewer')
    rows = [r for r in analytics(request, batch) if r['label'] in {'good', 'bad'}]
    if len(rows) < 4 or {r['label'] for r in rows} != {'good', 'bad'}:
        raise AppError(422, 'insufficient_labels', 'Label at least four images, including good and bad examples')
    samples = [(ImageMetrics(**{k: r[k] for k in METRICS}), r['label']) for r in rows]
    base = request.app.state.catalog.policy()
    fitted, notes = calibrate(samples, base)
    return {'suggested_policy': fitted.as_dict(), 'notes': notes,
            'sample_count': len(samples), 'evaluation_scope': 'training examples only; not held-out performance',
            'before': evaluate_policy(samples, base).as_dict(),
            'after': evaluate_policy(samples, fitted).as_dict(), 'applied': False}


@router.post('/analysis/benchmark')
def benchmark(request: Request, scenes: int = Query(8, ge=4, le=24), seed: int = Query(7, ge=0, le=2**31-1)):
    authorize(request, 'reviewer')
    return run_benchmark(scenes, seed).as_dict()


@router.get('/audit')
def audit(request: Request, limit: int = Query(100, ge=1, le=500)):
    authorize(request, 'admin')
    return {'events': request.app.state.catalog.audit_events(limit)}


@router.post('/analysis/advice')
def advice(request: Request, batch: str | None = None):
    authorize(request, 'reviewer')
    return explain(request.app.state.settings, analytics(request, batch))
