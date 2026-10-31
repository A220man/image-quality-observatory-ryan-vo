"""Tests for automated quarantine webhook notifications."""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import Response

from app.core.config import Settings
from app.core.auth import COOKIE, create_session, digest
from app.core.db import Database
from app.main import create_app
from app.services.webhook import (
    WebhookConfig,
    WebhookManager,
    QuarantineEvent,
    compute_batch_rejection_rate,
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


def picture(value=120):
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO()
    Image.new('L', (32, 32), value).save(buffer, format='PNG')
    return buffer.getvalue()


def test_webhook_config_crud_requires_admin(client):
    """Webhook config endpoints require admin role."""
    login(client)
    # viewer cannot access
    from datetime import datetime, timezone, timedelta
    from app.core.auth import COOKIE, digest
    import secrets
    import json
    
    # Create viewer session directly with known token
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    settings = client.app.state.settings
    with client.app.state.db.transaction() as conn:
        conn.execute('DELETE FROM sessions WHERE expires_at <= ?', (now.isoformat(),))
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)',
                     (digest(token), 'viewer', 'Viewer', json.dumps(['viewer']), csrf,
                      (now + timedelta(seconds=settings.session_ttl_seconds)).isoformat(), now.isoformat()))
    client.cookies.clear()
    client.cookies[COOKIE] = token
    client.headers['X-CSRF-Token'] = csrf
    assert client.post('/api/webhooks', json={'url': 'http://example.com', 'secret': 'a' * 16}).status_code == 403
    assert client.get('/api/webhooks').status_code == 403


def test_webhook_config_crud(client):
    """Create, read, update, delete webhook configurations."""
    login(client)  # admin by default in demo
    # Create
    resp = client.post('/api/webhooks', json={
        'url': 'http://example.com/webhook',
        'secret': 'supersecretkey123456',
        'categories': {'default': 0.1, 'training': 0.2},
        'enabled': True,
    })
    assert resp.status_code == 200
    webhook_id = resp.json()['id']
    assert resp.json()['url'] == 'http://example.com/webhook'
    assert resp.json()['secret'] == '***'  # redacted
    assert resp.json()['categories'] == {'default': 0.1, 'training': 0.2}

    # List
    resp = client.get('/api/webhooks')
    assert resp.status_code == 200
    assert len(resp.json()['webhooks']) == 1

    # Get
    resp = client.get(f'/api/webhooks/{webhook_id}')
    assert resp.status_code == 200
    assert resp.json()['id'] == webhook_id

    # Update
    resp = client.patch(f'/api/webhooks/{webhook_id}', json={
        'url': 'http://example.com/webhook2',
        'secret': 'newsecretkey12345678',
        'categories': {'default': 0.15},
        'enabled': False,
    })
    assert resp.status_code == 200
    assert resp.json()['url'] == 'http://example.com/webhook2'
    assert resp.json()['enabled'] is False

    # Delete
    resp = client.delete(f'/api/webhooks/{webhook_id}')
    assert resp.status_code == 204
    resp = client.get(f'/api/webhooks/{webhook_id}')
    assert resp.status_code == 404


def test_webhook_config_validation(client):
    """Validate webhook config input."""
    login(client)
    # Secret too short
    resp = client.post('/api/webhooks', json={
        'url': 'http://example.com/webhook',
        'secret': 'short',
        'categories': {'default': 0.1},
    })
    assert resp.status_code == 422

    # Threshold out of range
    resp = client.post('/api/webhooks', json={
        'url': 'http://example.com/webhook',
        'secret': 'supersecretkey123456',
        'categories': {'default': 1.5},
    })
    assert resp.status_code == 422

    # Negative threshold
    resp = client.post('/api/webhooks', json={
        'url': 'http://example.com/webhook',
        'secret': 'supersecretkey123456',
        'categories': {'default': -0.1},
    })
    assert resp.status_code == 422


def test_compute_batch_rejection_rate():
    """Test rejection rate computation."""
    from app.services.catalog import Catalog
    from app.core.db import Database

    db = Database(':memory:')
    catalog = Catalog(db)

    # No images
    total, rejected, rate = compute_batch_rejection_rate(catalog, 'empty')
    assert total == 0 and rejected == 0 and rate == 0.0

    # Add some images - need to use the ingest path
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFilter

    def make_good_image():
        img = Image.new('L', (32, 32), 128)
        draw = ImageDraw.Draw(img)
        draw.rectangle([5, 5, 15, 15], fill=200)
        draw.rectangle([20, 20, 27, 27], fill=50)
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def make_blurry_image(base_value=128):
        img = Image.new('L', (32, 32), base_value)
        draw = ImageDraw.Draw(img)
        draw.rectangle([5, 5, 15, 15], fill=200)
        draw.rectangle([20, 20, 27, 27], fill=50)
        img = img.filter(ImageFilter.GaussianBlur(5))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    img_good = make_good_image()
    img_blurry1 = make_blurry_image(128)
    img_blurry2 = make_blurry_image(100)

    catalog.ingest(img_good, 'good.png', 'test_batch', 'tester')
    catalog.ingest(img_blurry1, 'blurry1.png', 'test_batch', 'tester')
    catalog.ingest(img_blurry2, 'blurry2.png', 'test_batch', 'tester')

    total, rejected, rate = compute_batch_rejection_rate(catalog, 'test_batch')
    assert total == 3
    assert rejected == 2  # two blurry images should be rejected
    assert abs(rate - 2/3) < 0.01


def test_webhook_manager_persistence():
    """Test webhook config persistence."""
    from app.core.db import Database

    db = Database(':memory:')
    manager = WebhookManager(db)

    config = WebhookConfig(
        id='test-webhook',
        url='http://example.com/webhook',
        secret='supersecretkey123456',
        categories={'default': 0.1},
        enabled=True,
    )
    manager.add_config(config)

    # Retrieve
    retrieved = manager.get_config('test-webhook')
    assert retrieved is not None
    assert retrieved.id == 'test-webhook'
    assert retrieved.url == 'http://example.com/webhook'
    assert retrieved.secret == 'supersecretkey123456'
    assert retrieved.categories == {'default': 0.1}
    assert retrieved.enabled is True

    # List
    configs = manager.list_configs()
    assert len(configs) == 1

    # Update
    updated = WebhookConfig(
        id='test-webhook',
        url='http://example.com/webhook2',
        secret='newsecretkey12345678',
        categories={'default': 0.2},
        enabled=False,
        created_at=config.created_at,
    )
    manager.add_config(updated)
    retrieved = manager.get_config('test-webhook')
    assert retrieved.url == 'http://example.com/webhook2'
    assert retrieved.enabled is False

    # Delete
    deleted = manager.delete_config('test-webhook')
    assert deleted is True
    assert manager.get_config('test-webhook') is None


def test_quarantine_event_serialization():
    """Test quarantine event serialization."""
    event = QuarantineEvent(
        event_id='test-event-id',
        timestamp=time.time(),
        batch='test_batch',
        category='default',
        total_images=100,
        rejected_count=15,
        rejection_rate=0.15,
        threshold=0.1,
        triggered=True,
    )
    d = event.as_dict()
    assert d['event_id'] == 'test-event-id'
    assert d['batch'] == 'test_batch'
    assert d['total_images'] == 100
    assert d['rejected_count'] == 15
    assert d['rejection_rate'] == 0.15
    assert d['threshold'] == 0.1
    assert d['triggered'] is True


@pytest.mark.asyncio
async def test_webhook_dispatch_signature():
    """Test webhook dispatch generates correct HMAC signature."""
    import hmac

    db = Database(':memory:')
    manager = WebhookManager(db)

    config = WebhookConfig(
        id='test-webhook',
        url='http://example.com/webhook',
        secret='supersecretkey123456',
        categories={'default': 0.1},
        enabled=True,
    )

    event = QuarantineEvent(
        event_id='test-event-id',
        timestamp=time.time(),
        batch='test_batch',
        category='default',
        total_images=100,
        rejected_count=15,
        rejection_rate=0.15,
        threshold=0.1,
        triggered=True,
    )

    payload = event.as_dict()
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode()
    expected_sig = hmac.new(config.secret.encode(), payload_bytes, 'sha256').hexdigest()

    # Mock the HTTP call
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'
        mock_post.return_value = mock_response

        status_code, response_body, error = await manager.dispatch(config, event)

        assert status_code == 200
        assert error is None
        # Verify the signature header was sent
        call_args = mock_post.call_args
        headers = call_args.kwargs['headers']
        assert headers['X-Webhook-Signature'] == expected_sig
        assert headers['X-Webhook-Event-Id'] == 'test-event-id'
        assert 'X-Webhook-Timestamp' in headers


def test_check_and_dispatch_no_images(client):
    """Test check_and_dispatch with empty batch."""
    login(client)
    manager = client.app.state.webhook_manager

    # Add webhook config
    config = WebhookConfig(
        id='test-webhook',
        url='http://example.com/webhook',
        secret='supersecretkey123456',
        categories={'default': 0.1},
        enabled=True,
    )
    manager.add_config(config)

    results = manager.check_and_dispatch(client.app.state.catalog, 'empty_batch', 'default')
    assert results == []


def test_check_quarantine_endpoint(client):
    """Test the check quarantine endpoint."""
    login(client)

    # Add some rejected images to a batch
    from app.services.catalog import Catalog
    from app.services.metrics import measure_bytes
    from PIL import Image, ImageDraw, ImageFilter
    from io import BytesIO

    def make_blurry_image():
        img = Image.new('L', (32, 32), 128)
        draw = ImageDraw.Draw(img)
        draw.rectangle([5, 5, 15, 15], fill=200)
        draw.rectangle([20, 20, 27, 27], fill=50)
        img = img.filter(ImageFilter.GaussianBlur(5))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    img_blurry_bytes = make_blurry_image()

    for i in range(5):
        client.app.state.catalog.ingest(img_blurry_bytes, f'blurry{i}.png', 'bad_batch', 'tester')

    # Add webhook config with low threshold
    resp = client.post('/api/webhooks', json={
        'url': 'http://example.com/webhook',
        'secret': 'supersecretkey123456',
        'categories': {'default': 0.1},  # 10% threshold
        'enabled': True,
    })
    assert resp.status_code == 200

    # Check quarantine - should trigger (5/5 = 100% rejected > 10%)
    resp = client.post('/api/webhooks/check/bad_batch', params={'category': 'default'})
    assert resp.status_code == 200
    data = resp.json()
    assert data['batch'] == 'bad_batch'
    assert len(data['triggered']) == 1
    assert data['triggered'][0]['event']['triggered'] is True


def test_test_webhook_endpoint(client):
    """Test the test webhook endpoint."""
    login(client)

    # Add some images
    from app.services.catalog import Catalog
    from app.services.metrics import measure_bytes
    from PIL import Image, ImageDraw, ImageFilter
    from io import BytesIO

    def make_blurry_image():
        img = Image.new('L', (32, 32), 128)
        draw = ImageDraw.Draw(img)
        draw.rectangle([5, 5, 15, 15], fill=200)
        draw.rectangle([20, 20, 27, 27], fill=50)
        img = img.filter(ImageFilter.GaussianBlur(5))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    img_blurry_bytes = make_blurry_image()

    for i in range(3):
        client.app.state.catalog.ingest(img_blurry_bytes, f'blurry{i}.png', 'test_batch', 'tester')

    # Add webhook config
    resp = client.post('/api/webhooks', json={
        'url': 'http://example.com/webhook',
        'secret': 'supersecretkey123456',
        'categories': {'default': 0.1},
        'enabled': True,
    })
    webhook_id = resp.json()['id']

    # Test webhook - mock the HTTP call
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'
        mock_post.return_value = mock_response

        resp = client.post(f'/api/webhooks/{webhook_id}/test', json={
            'batch': 'test_batch',
            'category': 'default',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['event']['triggered'] is True  # 3/3 = 100% > 10%
        assert data['delivery']['status_code'] == 200


def test_webhook_delivery_recording(client):
    """Test that webhook deliveries are recorded."""
    login(client)

    # Add webhook config
    resp = client.post('/api/webhooks', json={
        'url': 'http://example.com/webhook',
        'secret': 'supersecretkey123456',
        'categories': {'default': 0.1},
        'enabled': True,
    })
    webhook_id = resp.json()['id']

    # Check that delivery table exists and is empty initially
    rows = client.app.state.db.query('SELECT * FROM webhook_deliveries')
    assert len(rows) == 0

    # Add images first
    from PIL import Image, ImageDraw, ImageFilter
    from io import BytesIO

    def make_blurry_image():
        img = Image.new('L', (32, 32), 128)
        draw = ImageDraw.Draw(img)
        draw.rectangle([5, 5, 15, 15], fill=200)
        draw.rectangle([20, 20, 27, 27], fill=50)
        img = img.filter(ImageFilter.GaussianBlur(5))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    img_blurry_bytes = make_blurry_image()
    client.app.state.catalog.ingest(img_blurry_bytes, 'blurry.png', 'test_batch2', 'tester')

    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'
        mock_post.return_value = mock_response

        client.post(f'/api/webhooks/{webhook_id}/test', json={
            'batch': 'test_batch2',
            'category': 'default',
        })

    rows = client.app.state.db.query('SELECT * FROM webhook_deliveries')
    assert len(rows) == 1
    assert rows[0]['webhook_id'] == webhook_id
    assert rows[0]['status_code'] == 200