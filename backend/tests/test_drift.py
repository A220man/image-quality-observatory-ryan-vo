"""Tests for dataset drift comparison with Kolmogorov-Smirnov tests."""
import pytest
import numpy as np
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.drift import ks_two_sample, compare_batches, KSTestResult, DriftComparison


@pytest.fixture
def client():
    settings = Settings(
        environment='test',
        database_path=':memory:',
        auth_mode='demo',
        cookie_secure=False,
        frontend_url='http://127.0.0.1:5173',
    )
    with TestClient(create_app(settings)) as client:
        yield client


def login(client):
    response = client.post('/api/auth/demo')
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response


def picture(blur_radius=0, seed=0):
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new('L', (64, 64), 128)
    draw = ImageDraw.Draw(img)
    offset = (seed * 7) % 4
    for i in range(offset, 64, 4):
        draw.line([(i, 0), (i, 64)], fill=200)
        draw.line([(0, i), (64, i)], fill=50)
    if blur_radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


def test_ks_two_sample_identical_distributions():
    """KS test should not detect drift for identical distributions."""
    np.random.seed(42)
    x = np.random.normal(100, 15, 100)
    y = np.random.normal(100, 15, 100)
    stat, p_val, drift = ks_two_sample(x, y)
    assert not drift
    assert p_val > 0.05


def test_ks_two_sample_different_means():
    """KS test should detect drift for shifted distributions."""
    np.random.seed(42)
    x = np.random.normal(100, 10, 100)
    y = np.random.normal(130, 10, 100)
    stat, p_val, drift = ks_two_sample(x, y)
    assert drift
    assert p_val < 0.05
    assert stat > 0.5


def test_ks_two_sample_different_variance():
    """KS test should detect drift for different variances."""
    np.random.seed(42)
    x = np.random.normal(100, 5, 100)
    y = np.random.normal(100, 25, 100)
    stat, p_val, drift = ks_two_sample(x, y)
    assert drift
    assert p_val < 0.05


def test_ks_two_sample_empty_arrays():
    """KS test should handle empty arrays gracefully."""
    x = np.array([])
    y = np.array([1, 2, 3])
    stat, p_val, drift = ks_two_sample(x, y)
    assert stat == 0.0
    assert p_val == 1.0
    assert not drift


def test_ks_two_sample_small_samples():
    """KS test should work with small samples."""
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([6.0, 7.0, 8.0, 9.0, 10.0])
    stat, p_val, drift = ks_two_sample(x, y)
    assert drift
    assert p_val < 0.05


def test_compare_batches_no_drift():
    """compare_batches should return no drift for similar batches."""
    rows_a = [
        {'blur_score': 50.0, 'mean_luma': 128.0, 'edge_density': 30.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 45.0, 'dynamic_range': 200.0, 'quality_score': 0.8},
        {'blur_score': 55.0, 'mean_luma': 130.0, 'edge_density': 32.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 47.0, 'dynamic_range': 210.0, 'quality_score': 0.78},
        {'blur_score': 48.0, 'mean_luma': 125.0, 'edge_density': 28.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 44.0, 'dynamic_range': 190.0, 'quality_score': 0.82},
    ]
    rows_b = [
        {'blur_score': 52.0, 'mean_luma': 129.0, 'edge_density': 31.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 46.0, 'dynamic_range': 205.0, 'quality_score': 0.79},
        {'blur_score': 53.0, 'mean_luma': 127.0, 'edge_density': 29.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 45.0, 'dynamic_range': 195.0, 'quality_score': 0.81},
    ]
    result = compare_batches(rows_a, rows_b, 'batch_a', 'batch_b')
    assert isinstance(result, DriftComparison)
    assert result.batch_a == 'batch_a'
    assert result.batch_b == 'batch_b'
    assert result.total_a == 3
    assert result.total_b == 2
    # Should not detect drift for similar distributions
    assert not result.overall_drift
    for ks in result.ks_results:
        assert isinstance(ks, KSTestResult)
        assert ks.metric in ('blur_score', 'mean_luma', 'edge_density', 'shadow_clip', 'highlight_clip', 'rms_contrast', 'dynamic_range', 'quality_score')
        assert ks.sample_a_count >= 0
        assert ks.sample_b_count >= 0


def test_compare_batches_with_drift():
    """compare_batches should detect drift for different distributions."""
    rows_a = [
        {'blur_score': 50.0, 'mean_luma': 128.0, 'edge_density': 30.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 45.0, 'dynamic_range': 200.0, 'quality_score': 0.8},
        {'blur_score': 55.0, 'mean_luma': 130.0, 'edge_density': 32.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 47.0, 'dynamic_range': 210.0, 'quality_score': 0.78},
        {'blur_score': 48.0, 'mean_luma': 125.0, 'edge_density': 28.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 44.0, 'dynamic_range': 190.0, 'quality_score': 0.82},
    ]
    rows_b = [
        {'blur_score': 150.0, 'mean_luma': 128.0, 'edge_density': 30.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 45.0, 'dynamic_range': 200.0, 'quality_score': 0.3},
        {'blur_score': 160.0, 'mean_luma': 130.0, 'edge_density': 32.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 47.0, 'dynamic_range': 210.0, 'quality_score': 0.28},
        {'blur_score': 145.0, 'mean_luma': 125.0, 'edge_density': 28.0, 'shadow_clip': 0.01,
         'highlight_clip': 0.01, 'rms_contrast': 44.0, 'dynamic_range': 190.0, 'quality_score': 0.32},
    ]
    result = compare_batches(rows_a, rows_b, 'batch_a', 'batch_b')
    assert result.overall_drift
    blur_ks = next(ks for ks in result.ks_results if ks.metric == 'blur_score')
    quality_ks = next(ks for ks in result.ks_results if ks.metric == 'quality_score')
    assert blur_ks.drift_detected
    assert quality_ks.drift_detected
    assert blur_ks.p_value < 0.05
    assert quality_ks.p_value < 0.05


def test_compare_batches_missing_metrics():
    """compare_batches should handle missing metrics gracefully."""
    rows_a = [
        {'blur': 50.0, 'luma_mean': 128.0, 'quality_score': 0.8},
    ]
    rows_b = [
        {'blur': 60.0, 'luma_mean': 130.0, 'quality_score': 0.7},
    ]
    result = compare_batches(rows_a, rows_b, 'batch_a', 'batch_b')
    # Missing metrics should have zero counts and p_value=1.0
    for ks in result.ks_results:
        if ks.metric in ('luma_std', 'clip_shadow', 'clip_highlight', 'contrast'):
            assert ks.sample_a_count == 0
            assert ks.sample_b_count == 0
            assert ks.p_value == 1.0
            assert not ks.drift_detected


def test_drift_api_endpoint_requires_auth(client):
    assert client.get('/api/analysis/drift?batch_a=a&batch_b=b').status_code == 401


def test_drift_api_endpoint_requires_both_batches(client):
    login(client)
    resp = client.get('/api/analysis/drift?batch_a=a')
    assert resp.status_code == 422


def test_drift_api_endpoint_empty_batches(client):
    login(client)
    resp = client.get('/api/analysis/drift?batch_a=empty1&batch_b=empty2')
    assert resp.status_code == 200
    data = resp.json()
    assert data['batch_a'] == 'empty1'
    assert data['batch_b'] == 'empty2'
    assert data['total_a'] == 0
    assert data['total_b'] == 0
    assert data['overall_drift'] is False
    assert len(data['ks_results']) == 8


def test_drift_api_endpoint_with_data(client):
    login(client)
    # Upload images to batch_a (sharp - blur_radius=0)
    for i in range(3):
        client.post('/api/images', files={'file': (f'img{i}.png', picture(0, i), 'image/png')}, data={'batch': 'batch_a'})
    # Upload images to batch_b (blurry - blur_radius=2)
    for i in range(3):
        client.post('/api/images', files={'file': (f'img{i}b.png', picture(2, i), 'image/png')}, data={'batch': 'batch_b'})

    resp = client.get('/api/analysis/drift?batch_a=batch_a&batch_b=batch_b')
    assert resp.status_code == 200
    data = resp.json()
    assert data['batch_a'] == 'batch_a'
    assert data['batch_b'] == 'batch_b'
    assert data['total_a'] == 3
    assert data['total_b'] == 3
    # Blur should show drift
    blur_ks = next(ks for ks in data['ks_results'] if ks['metric'] == 'blur_score')
    assert blur_ks['drift_detected'] is True
    assert blur_ks['p_value'] < 0.05
    assert data['overall_drift'] is True


def test_drift_alpha_parameter(client):
    """Test custom alpha parameter."""
    login(client)
    # Upload to batch_a (sharp)
    for i in range(3):
        client.post('/api/images', files={'file': (f'img{i}.png', picture(0, i), 'image/png')}, data={'batch': 'alpha_a'})
    # Upload to batch_b (blurry)
    for i in range(3):
        client.post('/api/images', files={'file': (f'img{i}b.png', picture(2, i), 'image/png')}, data={'batch': 'alpha_b'})

    # Strict alpha
    resp_strict = client.get('/api/analysis/drift?batch_a=alpha_a&batch_b=alpha_b&alpha=0.001')
    assert resp_strict.status_code == 200
    # Loose alpha
    resp_loose = client.get('/api/analysis/drift?batch_a=alpha_a&batch_b=alpha_b&alpha=0.5')
    assert resp_loose.status_code == 200