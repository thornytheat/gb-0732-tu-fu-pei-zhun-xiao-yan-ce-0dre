import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.config import RunOptions
from app.main import create_app
from app.modules.baseline.decisions import sheet_decisions
from app.modules.baseline.mosaic import mosaic_seams
from app.modules.baseline.policy import adjudicate
from app.modules.baseline.service import build_baseline
from app.pipeline import Survey
from app.store import Store
from conftest import by_key


@pytest.fixture
def baseline(settings):
    field = Survey(settings, RunOptions(dataset='field'))
    reference = Survey(settings, RunOptions(dataset='reference'))
    rulings = adjudicate(field.catalog, field, reference)
    mosaic = mosaic_seams(field, reference, rulings, 1.5)
    decisions = sheet_decisions(rulings, mosaic)
    return field, reference, rulings, mosaic, decisions


def test_each_sheet_adopts_a_single_edition_and_never_mixes(baseline):
    _, _, rulings, _, _ = baseline
    adopted = {row['code']: row['adopted']['edition'] for row in rulings}
    assert adopted == {'0421': 'field', '0422': 'field', '0431': 'field', '0432': 'reference'}
    assert all(row['mixing_allowed'] is False for row in rulings)


def test_field_correction_is_kept_on_fit_sheets_and_documented(baseline):
    _, _, rulings, _, _ = baseline
    for code in ('0421', '0422', '0431'):
        row = by_key(rulings, code)
        assert row['adopted_reason'] == 'FIELD_CORRECTION_PRIORITY'
        assert row['rejected']['edition'] == 'reference'
        assert row['rejected_reason'] == 'REFERENCE_SOURCE_MIX'
        assert row['adopted']['fit_status'] == 'FIT'


def test_collar_sheet_falls_back_to_reference_because_field_is_collinear(baseline):
    _, _, rulings, _, _ = baseline
    collar = by_key(rulings, '0432')
    assert collar['adopted']['edition'] == 'reference'
    assert collar['adopted_reason'] == 'FIELD_MODEL_BLOCKED'
    assert collar['rejected']['edition'] == 'field'
    assert collar['rejected_reason'] == 'COLLINEAR_PIXELS'


def test_mosaic_reuses_field_witness_table_and_keeps_its_quarantine(baseline):
    field, _, _, mosaic, _ = baseline
    assert mosaic['witness_edition'] == 'field'
    assert mosaic['input_count'] == 19
    assert {row['reason'] for row in mosaic['quarantine']} == {'UNKNOWN_EDGE'}
    assert sum(edge['count'] for edge in mosaic['edges']) == 18


def test_mosaic_seam_conclusions_cover_every_registered_edge(baseline):
    _, _, _, mosaic, decisions = baseline
    edges = {edge['code']: edge for edge in mosaic['edges']}
    assert edges['HX-LW']['status'] == 'PASS'
    assert edges['HX-QS']['status'] == 'FAIL' and edges['HX-QS']['reason'] == 'GAP_OVER_LIMIT'
    # QS-SJ now has two real FIT models, so it is measured rather than blocked.
    assert edges['QS-SJ']['status'] == 'FAIL' and edges['QS-SJ']['reason'] == 'GAP_OVER_LIMIT'
    assert (edges['QS-SJ']['a_edition'], edges['QS-SJ']['b_edition']) == ('field', 'reference')
    statuses = {row['code']: row['status'] for row in decisions}
    assert statuses == {'0421': 'RETURN', '0422': 'RETURN', '0431': 'READY', '0432': 'RETURN'}


def test_only_liwan_is_signable_under_the_ruling(baseline):
    _, _, _, _, decisions = baseline
    liwan = by_key(decisions, '0431')
    assert liwan['status'] == 'READY' and liwan['reason'] is None
    assert all(by_key(decisions, code)['status'] != 'READY' for code in ('0421', '0422', '0432'))


def test_create_ruling_endpoint_shape_and_idempotency(client):
    first = client.post('/api/baseline/rulings', json={})
    assert first.status_code == 200
    payload = first.json()
    assert payload['reused'] is False
    assert len(payload['rulings']) == 4 and len(payload['mosaic']['edges']) == 3
    rid = payload['manifest']['ruling_id']
    again = client.post('/api/baseline/rulings', json={})
    assert again.json()['reused'] is True
    assert again.json()['manifest']['ruling_id'] == rid
    # Same comparison rerun must not create another ruling volume.
    with sqlite3.connect(client.app.state.settings.database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM baseline_rulings').fetchone() == (1,)


def test_threshold_change_is_a_new_comparison_and_creates_a_new_ruling(client):
    first = client.post('/api/baseline/rulings', json={}).json()
    widened = client.post('/api/baseline/rulings', json={'seam_limit_m': 3}).json()
    assert first['manifest']['ruling_id'] != widened['manifest']['ruling_id']
    edges = {edge['code']: edge for edge in widened['mosaic']['edges']}
    assert edges['HX-QS']['status'] == 'PASS' and edges['QS-SJ']['status'] == 'PASS'
    with sqlite3.connect(client.app.state.settings.database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM baseline_rulings').fetchone() == (2,)


def test_ruling_signatures_only_recognize_the_ruling(client):
    payload = client.post('/api/baseline/rulings', json={}).json()
    rid = payload['manifest']['ruling_id']
    url = f'/api/baseline/rulings/{rid}/signatures'
    blocked = client.post(url, json={'sheet': '0421', 'reviewer': '周测绘'})
    assert blocked.status_code == 409
    assert blocked.json()['detail'] == {'code': 'SIGNATURE_BLOCKED',
                                        'message': '图幅未通过基准裁定，不能签审',
                                        'evidence': 'MOSAIC_GAP'}
    signed = client.post(url, json={'sheet': '0431', 'reviewer': ' 周测绘 '})
    assert signed.status_code == 200 and signed.json()['reviewer'] == '周测绘'
    # The first reviewer stays authoritative for that sheet.
    stale = client.post(url, json={'sheet': '0431', 'reviewer': '陈测绘'})
    assert (stale.status_code, stale.json()['detail']['code']) == (409, 'SIGNATURE_VERSION_CONFLICT')
    readback = client.get(f'/api/baseline/rulings/{rid}').json()
    assert readback['signatures'] == [signed.json()]


def test_rerun_keeps_recorded_signatures(client):
    payload = client.post('/api/baseline/rulings', json={}).json()
    rid = payload['manifest']['ruling_id']
    client.post(f'/api/baseline/rulings/{rid}/signatures',
                json={'sheet': '0431', 'reviewer': '周测绘'})
    rerun = client.post('/api/baseline/rulings', json={}).json()
    assert rerun['reused'] is True
    assert rerun['signatures'][0]['reviewer'] == '周测绘'


def test_save_failure_rolls_back_and_leaves_no_partial_volume(settings, monkeypatch):
    store = Store(settings.database)
    store.initialize()

    def broken_insert(snapshot):
        with store.connect('IMMEDIATE') as connection:
            # Simulate a write failure inside the ruling write transaction.
            connection.execute('INSERT INTO no_such_table VALUES (1)')

    monkeypatch.setattr(store, 'insert_ruling', broken_insert)
    with pytest.raises(sqlite3.OperationalError):
        build_baseline(settings, store, RunOptions())
    # The transaction rolled back: no ruling volume and no signatures were left behind.
    with sqlite3.connect(settings.database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM baseline_rulings').fetchone() == (0,)
        assert connection.execute('SELECT COUNT(*) FROM ruling_signatures').fetchone() == (0,)
    # The same comparison then succeeds and produces exactly one volume.
    monkeypatch.undo()
    saved, reused = build_baseline(settings, store, RunOptions())
    assert reused is False and len(saved['rulings']) == 4
    with sqlite3.connect(settings.database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM baseline_rulings').fetchone() == (1,)


def test_failed_save_of_a_new_comparison_restores_the_previous_volume(settings, monkeypatch):
    store = Store(settings.database)
    store.initialize()
    first, _ = build_baseline(settings, store, RunOptions())
    first_id = first['manifest']['ruling_id']

    # A different comparison (new threshold) would get a new ruling id; force its save to fail.
    original = store.insert_ruling
    seen_ids = set()

    def fail_once(snapshot):
        seen_ids.add(snapshot['manifest']['ruling_id'])
        if snapshot['manifest']['ruling_id'] != first_id:
            with store.connect('IMMEDIATE') as connection:
                connection.execute('INSERT INTO no_such_table VALUES (1)')
        return original(snapshot)

    monkeypatch.setattr(store, 'insert_ruling', fail_once)
    with pytest.raises(sqlite3.OperationalError):
        build_baseline(settings, store, RunOptions(seam_limit_m=2.5))
    # Rollback leaves the previous volume intact and adds nothing half-written.
    with sqlite3.connect(settings.database) as connection:
        rows = connection.execute('SELECT ruling_id FROM baseline_rulings').fetchall()
        assert rows == [(first_id,)]
    assert store.get_ruling(first_id)['manifest']['ruling_id'] == first_id


def test_concurrent_builds_store_one_ruling(settings):
    store = Store(settings.database)
    store.initialize()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: build_baseline(settings, store, RunOptions()), range(4)))
    assert sum(not reused for _, reused in results) == 1
    assert len({snapshot['manifest']['ruling_id'] for snapshot, _ in results}) == 1
    with sqlite3.connect(settings.database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM baseline_rulings').fetchone() == (1,)


def test_input_byte_change_changes_the_ruling_identity(settings, tmp_path):
    new_root = tmp_path / 'copies'
    shutil.copytree(settings.sample_root, new_root)
    settings.sample_root = new_root
    store = Store(settings.database)
    store.initialize()
    first, _ = build_baseline(settings, store, RunOptions())
    with (new_root / 'reference' / 'pixels.csv').open('ab') as stream:
        stream.write(b'\n')
    second, reused = build_baseline(settings, store, RunOptions())
    assert reused is False
    assert first['manifest']['ruling_id'] != second['manifest']['ruling_id']


def test_ruling_export_is_self_contained(client):
    payload = client.post('/api/baseline/rulings', json={}).json()
    rid = payload['manifest']['ruling_id']
    response = client.get(f'/api/baseline/rulings/{rid}/export')
    assert response.status_code == 200
    assert response.headers['content-disposition'] == f'attachment; filename="baseline-ruling-{rid[:12]}.json"'
    bundle = response.json()
    assert bundle['format'] == 'map-register/baseline-ruling-1'
    assert set(bundle['manifest']['inputs']) == {
        f'{edition}/{name}' for edition in ('field', 'reference')
        for name in ('catalog.json', 'pixels.csv', 'ground.csv', 'witness.csv')}
    assert 'FIELD_CORRECTION_PRIORITY' in bundle['reason_dictionary']
    assert bundle['policy']['mixing_allowed'] is False


def test_unknown_ruling_and_invalid_threshold_are_rejected(client):
    missing = client.get('/api/baseline/rulings/' + '0' * 64)
    assert (missing.status_code, missing.json()['detail']['code']) == (404, 'RULING_NOT_FOUND')
    invalid = client.post('/api/baseline/rulings', json={'seam_limit_m': 0})
    assert (invalid.status_code, invalid.json()['detail']['code']) == (422, 'INVALID_INPUT')


def test_ruling_survives_application_restart(settings):
    with TestClient(create_app(settings)) as first:
        payload = first.post('/api/baseline/rulings', json={}).json()
        rid = payload['manifest']['ruling_id']
        response = first.post(f'/api/baseline/rulings/{rid}/signatures',
                              json={'sheet': '0431', 'reviewer': '丁复核'})
        assert response.status_code == 200
    with TestClient(create_app(settings)) as second:
        persisted = second.get(f'/api/baseline/rulings/{rid}/export').json()
        assert persisted['signatures'][0]['reviewer'] == '丁复核'
        assert by_key(persisted['rulings'], '0432')['adopted']['edition'] == 'reference'


def test_baseline_page_is_reachable(client):
    home = client.get('/').text
    assert '基准对照裁定' in home and 'data-section="baseline"' in home
    assert client.get('/static/baseline.js').status_code == 200
    assert client.get('/health').status_code == 200
