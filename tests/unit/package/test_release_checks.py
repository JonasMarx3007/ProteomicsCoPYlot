"""Reject incomplete or mismatched release bundles before CI offers downloads."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

spec = importlib.util.spec_from_file_location(
    'release_checks', Path(__file__).resolve().parents[3] / 'packaging/check_release.py'
)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def make_bundle(tmp_path, fault=None):
    executable = tmp_path / 'ProteomicsCoPYlot'
    executable.write_bytes(b'application')
    source = b'corresponding source'
    manifest = {
        'revision': 'a' * 40,
        'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256(source).hexdigest(),
    }
    bundle = tmp_path / 'release.zip'
    with zipfile.ZipFile(bundle, 'w') as archive:
        info = zipfile.ZipInfo(executable.name)
        info.external_attr = 0o100755 << 16
        archive.writestr(info, b'wrong executable' if fault == 'executable' else executable.read_bytes())
        archive.writestr('CoPYlot-source.zip', b'wrong source' if fault == 'source' else source)
        archive.writestr('release-manifest.json', json.dumps(manifest))
        for name in ['LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.txt', 'README.txt', 'build-requirements.txt']:
            if not (fault == 'missing licence' and name == 'LICENSE'):
                archive.writestr(name, 'release information')
    return bundle, executable


def test_accepts_matching_bundle(tmp_path):
    bundle, executable = make_bundle(tmp_path)
    checks.check_bundle(bundle, executable, 'a' * 40)


@pytest.mark.parametrize('fault', ['executable', 'source', 'missing licence', 'revision'])
def test_rejects_mismatched_bundle(tmp_path, fault):
    bundle, executable = make_bundle(tmp_path, fault)
    with pytest.raises(ValueError):
        checks.check_bundle(bundle, executable, ('b' if fault == 'revision' else 'a') * 40)
