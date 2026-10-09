"""Transactional image catalog, policy re-evaluation and reviewer audit history."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from app.core.db import Database, utcnow
from app.services.metrics import ImageMetrics, measure_bytes
from app.services.policy import Policy, assess, failure_signature

METRICS = tuple(ImageMetrics.__dataclass_fields__)


def image_record(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data['failures'] = json.loads(data['failures'])
    data['signature'] = failure_signature(data['failures'])
    return data


def audit(conn: sqlite3.Connection, actor: str, action: str, target: str, detail: dict) -> None:
    conn.execute(
        'INSERT INTO audit_log(actor,action,target,detail,created_at) VALUES(?,?,?,?,?)',
        (actor, action, target, json.dumps(detail, sort_keys=True), utcnow()),
    )


class Catalog:
    def __init__(self, db: Database):
        self.db = db
        policy = Policy()
        with db.transaction() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO policy VALUES(1,?,?,?,?,?,?,?,?)',
                (*policy.as_dict().values(), 'system', utcnow()),
            )

    def policy(self) -> Policy:
        row = self.db.query_one('SELECT * FROM policy WHERE id=1')
        return Policy(**{k: row[k] for k in Policy.__dataclass_fields__})

    def ingest(self, content: bytes, filename: str, batch: str, actor: str,
               max_pixels: int = 40_000_000) -> tuple[dict, bool]:
        # Decode before acquiring the write lock. No untrusted file is persisted.
        decoded, metrics = measure_bytes(content, max_pixels)
        filename = filename.replace('\\', '/').rsplit('/', 1)[-1][:255] or 'image'
        batch = batch.strip()
        if not batch or len(batch) > 100:
            raise ValueError('Batch must contain between 1 and 100 characters')
        with self.db.transaction() as conn:
            existing = conn.execute('SELECT * FROM images WHERE sha256=? AND batch=?',
                                    (decoded.sha256, batch)).fetchone()
            if existing:
                return image_record(existing), False
            row = conn.execute('SELECT * FROM policy WHERE id=1').fetchone()
            policy = Policy(**{k: row[k] for k in Policy.__dataclass_fields__})
            assessment = assess(metrics, policy)
            now = utcnow()
            values = {
                'filename': filename, 'sha256': decoded.sha256, 'width': decoded.width,
                'height': decoded.height, 'format': decoded.format, 'size_bytes': len(content),
                'batch': batch, **metrics.as_dict(), 'failures': json.dumps(assessment.failures),
                'decision': assessment.decision, 'quality_score': assessment.quality_score,
                'created_by': actor, 'created_at': now, 'updated_at': now,
            }
            cursor = conn.execute(
                'INSERT INTO images('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',
                tuple(values.values()),
            )
            image_id = cursor.lastrowid
            audit(conn, actor, 'image.ingest', str(image_id),
                  {'sha256': decoded.sha256, 'batch': batch, 'decision': assessment.decision})
            return image_record(conn.execute('SELECT * FROM images WHERE id=?', (image_id,)).fetchone()), True

    def get(self, image_id: int) -> dict:
        row = self.db.query_one('SELECT * FROM images WHERE id=?', (image_id,))
        if row is None:
            raise KeyError(image_id)
        return image_record(row)

    def list(self, *, batch: str | None = None, decision: str | None = None,
             limit: int = 100, offset: int = 0) -> dict:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError('limit must be 1..500 and offset non-negative')
        if decision is not None and decision not in {'accept', 'review', 'reject'}:
            raise ValueError('Unknown decision')
        clauses, params = [], []
        for field, value in [('batch', batch), ('decision', decision)]:
            if value is not None:
                clauses.append(field+'=?'); params.append(value)
        where = ' WHERE '+' AND '.join(clauses) if clauses else ''
        # Read count and page under one transaction so concurrent deletes cannot
        # produce a total that contradicts the page's snapshot.
        with self.db.transaction() as conn:
            total = conn.execute('SELECT COUNT(*) FROM images'+where, params).fetchone()[0]
            rows = conn.execute('SELECT * FROM images'+where+' ORDER BY id DESC LIMIT ? OFFSET ?',
                                [*params, limit, offset]).fetchall()
        return {'items': [image_record(row) for row in rows], 'total': total,
                'limit': limit, 'offset': offset}

    def label(self, image_id: int, label: str | None, actor: str) -> dict:
        if label not in {None, 'good', 'bad'}:
            raise ValueError('Label must be good, bad or null')
        with self.db.transaction() as conn:
            row = conn.execute('SELECT * FROM images WHERE id=?', (image_id,)).fetchone()
            if row is None:
                raise KeyError(image_id)
            conn.execute('UPDATE images SET label=?,updated_at=? WHERE id=?',
                         (label, utcnow(), image_id))
            audit(conn, actor, 'image.label', str(image_id), {'before': row['label'], 'after': label})
            return image_record(conn.execute('SELECT * FROM images WHERE id=?', (image_id,)).fetchone())

    def delete(self, image_id: int, actor: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute('SELECT sha256,batch FROM images WHERE id=?', (image_id,)).fetchone()
            if row is None:
                raise KeyError(image_id)
            conn.execute('DELETE FROM images WHERE id=?', (image_id,))
            audit(conn, actor, 'image.delete', str(image_id), dict(row))

    def update_policy(self, policy: Policy, actor: str) -> dict:
        policy.validate()
        with self.db.transaction() as conn:
            before = dict(conn.execute('SELECT * FROM policy WHERE id=1').fetchone())
            now = utcnow()
            conn.execute('UPDATE policy SET '+','.join(k+'=?' for k in policy.as_dict())+
                         ',updated_by=?,updated_at=? WHERE id=1', (*policy.as_dict().values(), actor, now))
            rows = conn.execute('SELECT * FROM images').fetchall()
            counts: Counter[str] = Counter()
            for row in rows:
                result = assess(ImageMetrics(**{k: row[k] for k in METRICS}), policy)
                conn.execute('UPDATE images SET failures=?,decision=?,quality_score=?,updated_at=? WHERE id=?',
                             (json.dumps(result.failures), result.decision, result.quality_score, now, row['id']))
                counts[result.decision] += 1
            audit(conn, actor, 'policy.update', 'policy:1',
                  {'before': before, 'after': policy.as_dict(), 'reassessed': len(rows)})
        return {'policy': policy.as_dict(), 'reassessed': len(rows), 'decisions': dict(counts)}

    def analytics_rows(self, batch: str | None = None) -> list[dict]:
        where, params = (' WHERE batch=?', (batch,)) if batch is not None else ('', ())
        return [image_record(r) for r in self.db.query('SELECT * FROM images'+where+' ORDER BY id', params)]

    def audit_events(self, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 500:
            raise ValueError('limit must be 1..500')
        rows = self.db.query('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,))
        return [{**dict(r), 'detail': json.loads(r['detail'])} for r in rows]
