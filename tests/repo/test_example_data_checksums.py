"""Example-data downloads/checkouts match their documented LF-byte checksums."""
from pathlib import Path
import hashlib
import re


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'proteomicscopylot' / 'example_data'


def test_example_data_checksums_and_line_endings():
    readme = (EXAMPLES / 'README.md').read_text(encoding='utf-8')
    entries = re.findall(r'\| `([^`]+\.(?:csv|tsv))` \|.*?\| `([a-f0-9]{64})` \|', readme)
    assert len(entries) == 5
    assert len({name for name, _ in entries}) == 5
    for name, checksum in entries:
        data = (EXAMPLES / name).read_bytes()
        assert b'\r' not in data, f'{name}: expected LF line endings'
        assert hashlib.sha256(data).hexdigest() == checksum, f'{name}: README checksum mismatch'
