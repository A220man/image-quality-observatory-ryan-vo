import io
import json
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.main import create_app
from app.services.distribution import (
    DIST_METRICS,
    DatasetDistribution,
    compute_distribution,
)


@pytest.fixture
def client():
    settings = Settings(
        environment='test',
        database_path=':memory:',
        auth_mode='demo',
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def login(client):
    response = client.post('/api/auth/demo')
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response


def picture(value=128):
    buffer = io.BytesIO()
    Image.new('L', (32, 32), value).save(buffer, format='PNG')
    return buffer.getvalue()


def test_empty_distribution():
    dist = compute_distribution([])
    assert dist.total_images == 0
    assert dist.health_status == 'empty'
    assert dist.decisions.accept_count == 0
    assert dist.decisions.accept_rate == 0.0
    assert dist.labels.total_labeled == 0
    assert dist.labels.agreement_rate is None
    assert dist.metrics == {}
    assert dist.top_failures == []


def test_metric_statistics_and_percentiles():
    rows = [
        {
            'blur': 50.0,
            'luma_mean': 100.0,
            'luma_std': 20.0,
            'clip_shadow': 0.01,
            'clip_highlight': 0.02,
            'contrast': 0.20,
            'quality_score': 65.0,
            'decision': 'accept',
            'failures': [],
            'label': None,
        },
        {
            'blur': 150.0,
            'luma_mean': 120.0,
            'luma_std': 25.0,
            'clip_shadow': 0.02,
            'clip_highlight': 0.03,
            'contrast': 0.35,
            'quality_score': 85.0,
            'decision': 'accept',
            'failures': [],
            'label': 'good',
        },
        {
            'blur': 250.0,
            'luma_mean': 140.0,
            'luma_std': 30.0,
            'clip_shadow': 0.03,
            'clip_highlight': 0.04,
            'contrast': 0.50,
            'quality_score': 92.0,
            'decision': 'accept',
            'failures': [],
            'label': 'good',
        },
        {
            'blur': 10.0,
            'luma_mean': 30.0,
            'luma_std': 5.0,
            'clip_shadow': 0.15,
            'clip_highlight': 0.01,
            'contrast': 0.05,
            'quality_score': 20.0,
            'decision': 'reject',
            'failures': ['blur_low', 'luma_low'],
            'label': 'bad',
        },
    ]

    dist = compute_distribution(rows)
    assert dist.total_images == 4
    assert dist.decisions.accept_count == 3
    assert dist.decisions.accept_rate == 0.75
    assert dist.decisions.reject_count == 1
    assert dist.decisions.reject_rate == 0.25
    assert dist.health_status == 'degraded'

    for metric in DIST_METRICS:
        assert metric in dist.metrics
        stat = dist.metrics[metric]
        assert stat.count == 4
        assert stat.min <= stat.p10 <= stat.p25 <= stat.p50 <= stat.p75 <= stat.p90 <= stat.max
        assert round(stat.iqr, 4) == round(stat.p75 - stat.p25, 4)

    blur_stat = dist.metrics['blur']
    assert blur_stat.min == 10.0
    assert blur_stat.max == 250.0
    assert blur_stat.mean == 115.0


def test_label_alignment_and_agreement():
    rows = [
        {'decision': 'accept', 'label': 'good', 'failures': []},
        {'decision': 'reject', 'label': 'bad', 'failures': ['blur_low']},
        {'decision': 'reject', 'label': 'good', 'failures': ['blur_low']},
        {'decision': 'review', 'label': 'good', 'failures': ['luma_margin']},
        {'decision': 'accept', 'label': None, 'failures': []},
    ]

    dist = compute_distribution(rows)
    labels = dist.labels
    assert labels.total_labeled == 4
    assert labels.good_count == 3
    assert labels.bad_count == 1
    assert labels.unlabeled_count == 1
    assert labels.concordant_count == 2
    assert labels.discordant_count == 1
    assert labels.review_count == 1
    assert labels.agreement_rate == 0.50


def test_failure_frequency_and_health_levels():
    critical_rows = [
        {'decision': 'reject', 'failures': json.dumps(['blur_low', 'luma_low'])},
        {'decision': 'reject', 'failures': json.dumps(['blur_low'])},
        {'decision': 'accept', 'failures': '[]'},
    ]
    crit_dist = compute_distribution(critical_rows)
    assert crit_dist.health_status == 'critical'
    assert len(crit_dist.top_failures) == 2
    assert crit_dist.top_failures[0].check == 'blur_low'
    assert crit_dist.top_failures[0].count == 2
    assert crit_dist.top_failures[0].frequency == round(2 / 3, 4)

    healthy_rows = [
        {'decision': 'accept', 'failures': []} for _ in range(9)
    ] + [{'decision': 'review', 'failures': ['luma_margin']}]
    health_dist = compute_distribution(healthy_rows)
    assert health_dist.health_status == 'healthy'


def test_distribution_api_endpoint(client):
    assert client.get('/api/analysis/distribution').status_code == 401

    login(client)

    resp = client.get('/api/analysis/distribution')
    assert resp.status_code == 200
    data = resp.json()
    assert data['total_images'] == 0
    assert data['health_status'] == 'empty'

    upload = client.post(
        '/api/images',
        files={'file': ('dist_test.png', picture(128), 'image/png')},
        data={'batch': 'dist_batch'},
    )
    assert upload.status_code == 200
    image_id = upload.json()['image']['id']

    client.patch(f'/api/images/{image_id}/label', json={'label': 'good'})

    resp_all = client.get('/api/analysis/distribution')
    assert resp_all.status_code == 200
    assert resp_all.json()['total_images'] == 1
    assert resp_all.json()['labels']['good_count'] == 1

    resp_batch = client.get(
        '/api/analysis/distribution', params={'batch': 'dist_batch'}
    )
    assert resp_batch.status_code == 200
    assert resp_batch.json()['total_images'] == 1

    resp_other = client.get(
        '/api/analysis/distribution', params={'batch': 'nonexistent'}
    )
    assert resp_other.status_code == 200
    assert resp_other.json()['total_images'] == 0
