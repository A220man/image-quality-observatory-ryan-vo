import io
import math
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from app.core.db import Database
from app.services.catalog import Catalog
from app.services.metrics import ImageDecodeError
from app.services.policy import Policy


def png(color=120):
    image = Image.new('L', (32, 32), color)
    buffer = io.BytesIO(); image.save(buffer, format='PNG'); return buffer.getvalue()


@pytest.fixture
def catalog():
    db = Database(':memory:')
    yield Catalog(db)
    db.close()


def test_ingestion_measures_pixels_and_records_actor(catalog):
    row, created = catalog.ingest(png(), '../../sample.png', 'batch-a', 'reviewer')
    assert created and row['filename'] == 'sample.png'
    assert row['width'] == row['height'] == 32
    assert row['mean_luma'] == 120
    assert 'blurry' in row['failures']
    assert row['decision'] == 'reject'
    assert catalog.audit_events()[0]['actor'] == 'reviewer'


def test_duplicate_ingestion_is_idempotent(catalog):
    first, _ = catalog.ingest(png(), 'a.png', 'one', 'first')
    again, created = catalog.ingest(png(), 'renamed.png', 'one', 'second')
    assert not created and again['id'] == first['id']
    assert len(catalog.audit_events()) == 1


def test_same_content_can_belong_to_distinct_batches(catalog):
    a, _ = catalog.ingest(png(), 'a.png', 'one', 'user')
    b, _ = catalog.ingest(png(), 'a.png', 'two', 'user')
    assert a['id'] != b['id']
    assert catalog.list(batch='one')['total'] == 1


def test_concurrent_duplicates_have_one_winner(catalog):
    data = png()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: catalog.ingest(data, 'same.png', 'batch', 'user'), range(12)))
    assert sum(created for _, created in results) == 1
    assert catalog.list()['total'] == 1
    assert len(catalog.audit_events()) == 1


def test_bad_input_does_not_create_records(catalog):
    with pytest.raises(ImageDecodeError):catalog.ingest(b'not an image', 'image.png', 'batch', 'user')
    assert catalog.list()['total'] == 0
    assert catalog.audit_events() == []


def test_pixel_limit_prevents_decoding_oversized_image(catalog):
    with pytest.raises(ImageDecodeError, match='pixel limit'):
        catalog.ingest(png(), 'image.png', 'batch', 'user', max_pixels=10)
    assert catalog.list()['total'] == 0


def test_labels_do_not_overwrite_measured_decisions(catalog):
    row, _ = catalog.ingest(png(), 'image.png', 'batch', 'user')
    updated = catalog.label(row['id'], 'good', 'reviewer')
    assert updated['label'] == 'good' and updated['decision'] == row['decision']
    assert catalog.audit_events()[0]['detail'] == {'before': None, 'after': 'good'}
    assert catalog.label(row['id'], None, 'reviewer')['label'] is None


def test_bad_label_and_missing_id_fail_without_audit(catalog):
    with pytest.raises(ValueError):catalog.label(1, 'unknown', 'user')
    with pytest.raises(KeyError):catalog.label(1, 'bad', 'user')
    assert catalog.audit_events() == []


def test_delete_retains_audit_history(catalog):
    row, _ = catalog.ingest(png(), 'image.png', 'batch', 'user')
    catalog.delete(row['id'], 'admin')
    with pytest.raises(KeyError):catalog.get(row['id'])
    assert catalog.audit_events()[0]['action'] == 'image.delete'
    assert catalog.audit_events()[0]['detail']['sha256'] == row['sha256']


def test_query_inputs_are_bound_parameters(catalog):
    batch = "x' OR 1=1 --"
    catalog.ingest(png(), 'image.png', batch, 'user')
    catalog.ingest(png(121), 'image.png', 'normal', 'user')
    assert catalog.list(batch=batch)['total'] == 1
    assert len(catalog.analytics_rows(batch)) == 1


def test_page_order_and_counts(catalog):
    for value in range(100, 105):catalog.ingest(png(value), 'image.png', 'batch', 'user')
    page = catalog.list(limit=2, offset=1)
    assert page['total'] == 5
    assert [r['id'] for r in page['items']] == [4, 3]


def test_policy_change_reassesses_existing_images(catalog):
    row, _ = catalog.ingest(png(120), 'image.png', 'batch', 'user')
    before = row['quality_score']
    report = catalog.update_policy(Policy(blur_min=0, luma_min=10, luma_max=240), 'admin')
    assert report['reassessed'] == 1
    assert catalog.get(row['id'])['quality_score'] != before
    assert 'blurry' not in catalog.get(row['id'])['failures']
    assert catalog.audit_events()[0]['action'] == 'policy.update'


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_nonfinite_policy_is_rejected_atomically(catalog, value):
    before = catalog.policy()
    with pytest.raises(ValueError, match='finite'):catalog.update_policy(Policy(blur_min=value), 'admin')
    assert catalog.policy() == before
    assert catalog.audit_events() == []


def test_transaction_rollback_does_not_leave_partial_writes(catalog):
    with pytest.raises(RuntimeError):
        with catalog.db.transaction() as conn:
            conn.execute("UPDATE policy SET blur_min=42 WHERE id=1")
            raise RuntimeError('failed operation')
    assert catalog.policy().blur_min == 100


@pytest.mark.parametrize('kwargs', [{'limit':0}, {'limit':501}, {'offset':-1}, {'decision':'other'}])
def test_invalid_pagination_and_filter_rejected(catalog, kwargs):
    with pytest.raises(ValueError):catalog.list(**kwargs)
