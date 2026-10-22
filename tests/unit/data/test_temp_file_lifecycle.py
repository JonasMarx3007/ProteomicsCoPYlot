import gc
import io
from pathlib import Path

import pandas as pd
import pytest
from fastapi import UploadFile

from app.api import routes_datasets
from app.services import dataset_store as store, managed_temp, restore_state
from app.services.session_context import set_session_id, reset_session_id
from app.services.temp_file_lifecycle import temporary_file_scope


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(managed_temp, 'managed_temp_root', lambda: tmp_path / 'managed')
    yield tmp_path / 'managed'
    store.reset_all_datasets(all_sessions=True)
    gc.collect()


def owned_file(directory='table_uploads', name='data.csv'):
    path = managed_temp.private_temp_dir(directory) / name
    managed_temp.write_private_bytes(path, b'ProteinNames,A1\nP1,10\n')
    return path


def save(path, package=None):
    return store.save_table_dataset('data.csv', 'protein', pd.DataFrame({'A1': [10]}),
                                    source_path=str(path), package_name=package)


@pytest.mark.parametrize('kind', ['protein', 'peptide'])
def test_replacing_dataset_releases_only_its_old_owned_file(temp_root, kind):
    old = owned_file(name='old.csv')
    new = owned_file(name='new.csv')
    if kind == 'protein':
        save(old)
        save(new)
    else:
        store.save_peptide_path(str(old))
        store.save_peptide_path(str(new))
    gc.collect()
    assert not old.exists()
    assert new.exists()
    store.reset_all_datasets()
    gc.collect()
    assert not new.exists()


def test_shared_file_survives_other_package_and_session(temp_root, monkeypatch):
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    path = owned_file()
    save(path, 'first')
    save(path, 'second')
    save(owned_file(name='replacement.csv'), 'first')
    assert path.exists()
    token = set_session_id('another-session')
    try:
        save(path)
    finally:
        reset_session_id(token)
    store.reset_all_datasets()
    gc.collect()
    assert path.exists()
    token = set_session_id('another-session')
    try:
        store.reset_all_datasets()
    finally:
        reset_session_id(token)
    gc.collect()
    assert not path.exists()


def test_in_flight_reference_and_snapshot_keep_files_until_released(temp_root):
    path = owned_file()
    current = save(path)
    snapshot = store.snapshot_dataset_session_state()
    store.reset_all_datasets()
    assert path.exists()
    store.restore_dataset_session_state(snapshot)
    del snapshot
    store.reset_all_datasets()
    assert path.exists()
    del current
    gc.collect()
    assert not path.exists()


def test_external_and_unowned_files_are_never_removed(temp_root, tmp_path):
    external = tmp_path / 'original.csv'
    external.write_text('original')
    save(external)
    local = managed_temp.private_temp_dir('table_uploads') / 'not-created-by-app.csv'
    local.write_text('original')
    save(local)
    store.reset_all_datasets()
    gc.collect()
    assert external.read_text() == local.read_text() == 'original'


def test_file_replaced_at_same_path_is_not_deleted(temp_root):
    path = owned_file()
    save(path)
    replacement = path.with_name('replacement')
    replacement.write_text('user replacement')
    replacement.replace(path)
    store.reset_all_datasets()
    gc.collect()
    assert path.read_text() == 'user replacement'


def test_scope_removes_failed_unattached_writes(temp_root):
    with pytest.raises(ValueError), temporary_file_scope():
        path = owned_file()
        raise ValueError('failed parsing')
    assert not path.exists()


def test_bad_upload_does_not_leave_file(temp_root, monkeypatch):
    monkeypatch.setattr(routes_datasets, 'read_dataframe', lambda *args: (_ for _ in ()).throw(ValueError('bad table')))
    with pytest.raises(Exception, match='bad table'):
        routes_datasets.upload_dataset(UploadFile(filename='bad.csv', file=io.BytesIO(b'bad')), 'protein', None)
    assert not list((temp_root / 'table_uploads').iterdir())


def test_export_backup_is_removed_when_dataset_is_discarded(temp_root):
    store.save_table_dataset('derived.csv', 'protein', pd.DataFrame({'A1': [10]}))
    blob = restore_state.export_state_blob()
    path = Path(store.get_current_dataset('protein').source_path)
    assert path.exists()
    state = restore_state.decode_restore_blob(blob)
    store.reset_all_datasets()
    gc.collect()
    assert not path.exists()
    # Derived tables are embedded, so their exports remain restorable.
    restore_state.apply_restore_state(state, {})
    assert store.get_current_dataset('protein').frame.A1.tolist() == [10]


def test_successful_restore_releases_previous_files(temp_root):
    path = owned_file()
    save(path)
    restore_state.apply_restore_state({'backend': {'packages': []}}, {})
    gc.collect()
    assert not path.exists()


def test_restore_reusing_current_file_keeps_it(temp_root):
    path = owned_file()
    save(path)
    state = restore_state.decode_restore_blob(restore_state.export_state_blob())
    restore_state.apply_restore_state(state, {})
    gc.collect()
    assert path.exists()
    assert store.get_current_dataset('protein').source_path == str(path)


def test_peptide_read_keeps_file_during_replacement(temp_root, monkeypatch):
    from app.services import peptide_tools
    path = owned_file('peptide_uploads')
    store.save_peptide_path(str(path))

    def read_while_replaced(path_str, modified_ns):
        store.save_peptide_path(str(owned_file('peptide_uploads', 'replacement.csv')))
        gc.collect()
        assert path.exists()
        return pd.read_csv(path_str)

    monkeypatch.setattr(peptide_tools, '_load_peptide_frame_cached', read_while_replaced)
    assert peptide_tools.get_peptide_frame().ProteinNames.tolist() == ['P1']
    gc.collect()
    assert not path.exists()


def test_restore_rollback_retains_previous_file_and_removes_new_file(temp_root, monkeypatch):
    old = owned_file()
    save(old)
    state = {'backend': {'packages': [{'name': 'Data', 'datasets': {'peptide': {'filename': 'peptide.csv'}}}]}}
    replacement = restore_state.ReplacementInput(UploadFile(filename='peptide.csv', file=io.BytesIO(b'new')))

    def fail_after_saving(state, prepared):
        store.reset_all_datasets()
        new_path = prepared.peptide_path_by_package['Data'][0]
        store.save_peptide_path(new_path)
        assert old.exists()  # rollback snapshot retains the original dataset
        raise ValueError('restore failed')

    monkeypatch.setattr(restore_state, '_apply_prepared_restore_state', fail_after_saving)
    with pytest.raises(ValueError, match='restore failed'):
        restore_state.apply_restore_state(state, {('Data', 'peptide'): replacement}, allow_local_paths=False)
    gc.collect()
    assert old.exists()
    assert store.get_current_dataset('protein').source_path == str(old)
    assert not list((temp_root / 'restore_uploads').iterdir())


def test_session_discard_releases_owned_files(temp_root, monkeypatch):
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    from app.services.session_cleanup import _discard_session
    token = set_session_id('discard-test')
    try:
        path = owned_file()
        save(path)
    finally:
        reset_session_id(token)
    _discard_session('discard-test')
    gc.collect()
    assert not path.exists()


def test_restore_preparation_failure_removes_unattached_peptide_file(temp_root):
    state = {'backend': {'packages': [
        {'name': 'First', 'datasets': {'peptide': {'filename': 'peptide.csv'}}},
        {'name': 'Second', 'datasets': {'protein': {'filename': 'missing.csv'}}},
    ]}}
    replacement = restore_state.ReplacementInput(UploadFile(filename='peptide.csv', file=io.BytesIO(b'new')))
    with pytest.raises(restore_state.RestoreStateError, match='Missing replacement'):
        restore_state.apply_restore_state(state, {('First', 'peptide'): replacement}, allow_local_paths=False)
    assert not list((temp_root / 'restore_uploads').iterdir())


def test_restored_peptide_file_lasts_until_discard(temp_root):
    state = {'backend': {'packages': [{'name': 'Data', 'datasets': {'peptide': {'filename': 'peptide.csv'}}}]}}
    replacement = restore_state.ReplacementInput(UploadFile(filename='peptide.csv', file=io.BytesIO(b'new')))
    restore_state.apply_restore_state(state, {('Data', 'peptide'): replacement}, allow_local_paths=False)
    path = Path(store.get_current_dataset('peptide').path)
    assert path.read_bytes() == b'new'
    store.reset_all_datasets()
    gc.collect()
    assert not path.exists()


def test_redirected_directory_is_never_followed_for_deletion(temp_root, monkeypatch):
    import stat
    from types import SimpleNamespace
    path = owned_file()
    save(path)
    original_lstat = Path.lstat

    def reparse_directory(candidate):
        info = original_lstat(candidate)
        if candidate == path.parent:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(Path, 'lstat', reparse_directory)
    store.reset_all_datasets()
    gc.collect()
    assert path.exists()
