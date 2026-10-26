"""Automated webhook notifications for high rejection rate batches.

Dispatches signed HMAC webhooks when batch quality rejection rate
exceeds configured thresholds per dataset category.
"""
from __future__ import annotations
import asyncio
import hmac
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from app.core.db import Database
from app.services.catalog import Catalog


@dataclass(frozen=True)
class WebhookConfig:
    """Configuration for a webhook endpoint."""
    id: str
    url: str
    secret: str
    categories: dict[str, float] = field(default_factory=dict)  # category -> rejection threshold (0-1)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Redact secret in serialized form
        d['secret'] = '***' if self.secret else ''
        return d

    def threshold_for(self, category: str) -> float | None:
        """Get the rejection threshold for a category, or None if not configured."""
        return self.categories.get(category)


@dataclass(frozen=True)
class QuarantineEvent:
    """Event payload for quarantine webhook."""
    event_id: str
    timestamp: float
    batch: str
    category: str
    total_images: int
    rejected_count: int
    rejection_rate: float
    threshold: float
    triggered: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class WebhookManager:
    """Manages webhook configurations and dispatches quarantine notifications."""

    def __init__(self, db: Database):
        self.db = db
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._init_db()

    def _init_db(self) -> None:
        self.db._conn.executescript('''
            CREATE TABLE IF NOT EXISTS webhook_configs (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                secret TEXT NOT NULL,
                categories TEXT NOT NULL,  -- JSON: {"category": threshold}
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id TEXT PRIMARY KEY,
                webhook_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                status_code INTEGER,
                response_body TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (webhook_id) REFERENCES webhook_configs(id)
            );
        ''')

    def add_config(self, config: WebhookConfig) -> WebhookConfig:
        """Add or update a webhook configuration."""
        self.db._conn.execute('''
            INSERT OR REPLACE INTO webhook_configs (id, url, secret, categories, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            config.id,
            config.url,
            config.secret,
            json.dumps(config.categories),
            1 if config.enabled else 0,
            config.created_at,
        ))
        self.db._conn.commit()
        return config

    def get_config(self, webhook_id: str) -> WebhookConfig | None:
        """Get a webhook configuration by ID."""
        row = self.db._conn.execute('SELECT * FROM webhook_configs WHERE id=?', (webhook_id,)).fetchone()
        if not row:
            return None
        return WebhookConfig(
            id=row['id'],
            url=row['url'],
            secret=row['secret'],
            categories=json.loads(row['categories']),
            enabled=bool(row['enabled']),
            created_at=row['created_at'],
        )

    def list_configs(self) -> list[WebhookConfig]:
        """List all webhook configurations."""
        rows = self.db._conn.execute('SELECT * FROM webhook_configs ORDER BY created_at DESC').fetchall()
        return [
            WebhookConfig(
                id=row['id'],
                url=row['url'],
                secret=row['secret'],
                categories=json.loads(row['categories']),
                enabled=bool(row['enabled']),
                created_at=row['created_at'],
            )
            for row in rows
        ]

    def delete_config(self, webhook_id: str) -> bool:
        """Delete a webhook configuration."""
        cur = self.db._conn.execute('DELETE FROM webhook_configs WHERE id=?', (webhook_id,))
        self.db._conn.commit()
        return cur.rowcount > 0

    def _sign_payload(self, secret: str, payload: bytes) -> str:
        """Generate HMAC-SHA256 signature for payload."""
        return hmac.new(secret.encode(), payload, 'sha256').hexdigest()

    def _record_delivery(
        self,
        webhook_id: str,
        event_id: str,
        payload: dict,
        status_code: int | None,
        response_body: str | None,
        error: str | None,
    ) -> None:
        self.db._conn.execute('''
            INSERT INTO webhook_deliveries (id, webhook_id, event_id, payload, status_code, response_body, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(uuid.uuid4()),
            webhook_id,
            event_id,
            json.dumps(payload),
            status_code,
            response_body,
            error,
            time.time(),
        ))
        self.db._conn.commit()

    async def dispatch(
        self,
        config: WebhookConfig,
        event: QuarantineEvent,
        timeout: float = 10.0,
    ) -> tuple[int | None, str | None, str | None]:
        """Dispatch a quarantine event to a webhook endpoint.

        Returns (status_code, response_body, error).
        """
        payload = event.as_dict()
        payload_bytes = json.dumps(payload, separators=(',', ':')).encode()
        signature = self._sign_payload(config.secret, payload_bytes)

        headers = {
            'Content-Type': 'application/json',
            'X-Webhook-Signature': signature,
            'X-Webhook-Event-Id': event.event_id,
            'X-Webhook-Timestamp': str(int(event.timestamp)),
            'User-Agent': 'ImageQualityObservatory/1.0',
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(config.url, content=payload_bytes, headers=headers)
                return response.status_code, response.text, None
            except httpx.TimeoutException as exc:
                return None, None, f'Timeout: {exc}'
            except httpx.RequestError as exc:
                return None, None, f'Request error: {exc}'

    def check_and_dispatch(
        self,
        catalog: Catalog,
        batch: str,
        category: str,
    ) -> list[tuple[WebhookConfig, QuarantineEvent, tuple[int | None, str | None, str | None]]]:
        """Check if any webhook should be triggered for a batch/category and dispatch.

        Returns list of (config, event, delivery_result) for triggered webhooks.
        """
        # Get batch analytics
        rows = catalog.analytics_rows(batch)
        if not rows:
            return []

        # Filter by category if needed (using batch as category for now)
        # In a real implementation, images might have a category field
        batch_rows = [r for r in rows if r.get('batch') == batch]
        if not batch_rows:
            return []

        total = len(batch_rows)
        rejected = sum(1 for r in batch_rows if r.get('decision') == 'reject')
        rejection_rate = rejected / total if total > 0 else 0.0

        results = []
        for config in self.list_configs():
            if not config.enabled:
                continue
            threshold = config.threshold_for(category)
            if threshold is None:
                continue
            if rejection_rate <= threshold:
                continue

            # Trigger webhook
            event = QuarantineEvent(
                event_id=str(uuid.uuid4()),
                timestamp=time.time(),
                batch=batch,
                category=category,
                total_images=total,
                rejected_count=rejected,
                rejection_rate=rejection_rate,
                threshold=threshold,
                triggered=True,
            )

            # Dispatch using thread pool to avoid event loop conflicts
            future = self._executor.submit(asyncio.run, self.dispatch(config, event))
            delivery_result = future.result(timeout=30.0)

            self._record_delivery(config.id, event.event_id, event.as_dict(), *delivery_result)
            results.append((config, event, delivery_result))

        return results


def compute_batch_rejection_rate(catalog: Catalog, batch: str) -> tuple[int, int, float]:
    """Compute rejection rate for a batch.

    Returns (total, rejected, rate).
    """
    rows = catalog.analytics_rows(batch)
    if not rows:
        return 0, 0, 0.0
    total = len(rows)
    rejected = sum(1 for r in rows if r.get('decision') == 'reject')
    return total, rejected, rejected / total if total > 0 else 0.0