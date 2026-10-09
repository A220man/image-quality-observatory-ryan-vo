import pytest
from app.core.config import Settings, ConfigError, load_settings, validate_settings


@pytest.mark.parametrize('name,value', [
    ('max_image_pixels', 0), ('max_upload_bytes', -1), ('session_ttl_seconds', 0),
    ('llm_timeout_seconds', float('nan')), ('llm_timeout_seconds', float('inf')),
    ('frontend_url', 'https://example.com/path'), ('frontend_url', 'https://example.com?x=1'),
    ('frontend_url', 'https://user:password@example.com'), ('oidc_redirect_uri', 'javascript:alert(1)'),
])
def test_unsafe_settings_rejected(name, value):
    with pytest.raises(ConfigError):
        validate_settings(Settings(environment='test').with_overrides(**{name:value}))


@pytest.mark.parametrize('name', ['frontend_url', 'oidc_redirect_uri', 'oidc_discovery_url'])
def test_production_auth_urls_require_https(name):
    settings = Settings(environment='production', oidc_client_id='observatory',
                        frontend_url='https://images.example.com',
                        oidc_redirect_uri='https://images.example.com/api/auth/callback',
                        oidc_discovery_url='https://identity.example.com/.well-known/openid-configuration')
    validate_settings(settings)
    with pytest.raises(ConfigError):
        validate_settings(settings.with_overrides(**{name:'http://example.com'}))


def test_pixel_limit_loaded_from_environment(monkeypatch):
    monkeypatch.setenv('MAX_IMAGE_PIXELS', '4096')
    assert load_settings().max_image_pixels == 4096
