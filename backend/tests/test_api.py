import io
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from fastapi.responses import Response
from PIL import Image
from app.main import create_app
from app.core.config import Settings, ConfigError
from app.core.auth import COOKIE, create_session, digest


@pytest.fixture
def client():
    settings = Settings(environment='test', database_path=':memory:', auth_mode='demo', cookie_secure=False)
    with TestClient(create_app(settings)) as client:yield client


def login(client):
    response = client.post('/api/auth/demo')
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response


def picture(value=120):
    buffer = io.BytesIO();Image.new('L', (32,32), value).save(buffer,format='PNG');return buffer.getvalue()


def test_unauthenticated_data_access_rejected(client):
    assert client.get('/api/images').status_code == 401
    assert client.get('/api/policy').status_code == 401
    assert client.get('/api/health').status_code == 200


def test_full_image_review_lifecycle(client):
    login(client)
    response = client.post('/api/images', files={'file': ('sample.png',picture(),'image/png')}, data={'batch':'qa'})
    assert response.status_code == 200,response.text
    row = response.json()['image'];assert response.json()['created']
    assert client.get('/api/images',params={'batch':'qa'}).json()['total'] == 1
    assert client.patch(f"/api/images/{row['id']}/label",json={'label':'bad'}).json()['label']=='bad'
    assert client.get('/api/analysis/groups').status_code==200
    assert client.get('/api/analysis/clusters').json()['k']==1
    assert client.delete(f"/api/images/{row['id']}").status_code==204
    assert client.get(f"/api/images/{row['id']}").status_code==404
    assert len(client.get('/api/audit').json()['events'])==3


def test_csrf_required_for_mutations_and_logout(client):
    client.post('/api/auth/demo')
    assert client.put('/api/policy',json={}).status_code==403
    assert client.post('/api/auth/logout').status_code==403
    assert client.get('/api/images').status_code==200


def test_logout_invalidates_captured_session(client):
    login(client);token=client.cookies[COOKIE]
    assert client.post('/api/auth/logout').status_code==204
    client.cookies.set(COOKIE,token)
    assert client.get('/api/auth/me').status_code==401


def test_session_cookie_httponly_and_database_contains_hash(client):
    response=login(client)
    assert 'HttpOnly' in response.headers['set-cookie']
    token=client.cookies[COOKIE]
    assert client.app.state.db.query_one('SELECT id FROM sessions')['id']==digest(token)


def test_expired_session_denied(client):
    login(client)
    with client.app.state.db.transaction() as conn:
        conn.execute('UPDATE sessions SET expires_at=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    assert client.get('/api/images').status_code==401


def test_viewer_can_read_but_cannot_change_policy(client):
    response=Response();user=create_session(client.app.state.db,client.app.state.settings,response,'reader','Reader',['viewer'])
    token=response.headers['set-cookie'].split(';')[0].split('=',1)[1]
    client.cookies.set(COOKIE,token);client.headers['X-CSRF-Token']=user['csrf_token']
    assert client.get('/api/images').status_code==200
    assert client.put('/api/policy',json={}).status_code==403
    assert client.post('/api/images',files={'file':('a.png',picture())}).status_code==403
    assert client.get('/api/audit').status_code==403


def test_calibration_requires_labels(client):
    login(client)
    assert client.post('/api/analysis/calibrate').status_code==422


def test_invalid_upload_and_policy_are_rejected(client):
    login(client)
    assert client.post('/api/images',files={'file':('image.png',b'garbage')}).status_code==422
    assert client.put('/api/policy',json={'luma_min':200,'luma_max':100}).status_code==422
    assert client.get('/api/images').json()['total']==0


def test_cross_site_demo_login_is_rejected(client):
    assert client.post('/api/auth/demo',headers={'Origin':'https://untrusted.example'}).status_code==403


def test_demo_is_not_allowed_in_production():
    with pytest.raises(ConfigError):create_app(Settings(environment='production',auth_mode='demo'))


def test_duplicate_http_upload_is_idempotent(client):
    login(client)
    payload=picture()
    a=client.post('/api/images',files={'file':('a.png',payload)}).json()
    b=client.post('/api/images',files={'file':('b.png',payload)}).json()
    assert a['created'] and not b['created'] and a['image']['id']==b['image']['id']


@pytest.mark.parametrize('size', [101, 70000])
def test_upload_limit_rejects_without_persisting(size):
    settings = Settings(environment='test', database_path=':memory:', auth_mode='demo',
                        cookie_secure=False, max_upload_bytes=100)
    with TestClient(create_app(settings)) as client:
        login(client)
        response = client.post('/api/images', files={'file': ('large.png', b'x' * size)})
        assert response.status_code == 413, response.text
        assert client.get('/api/images').json()['total'] == 0
