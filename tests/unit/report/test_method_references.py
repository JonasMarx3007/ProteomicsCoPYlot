"""One list of outside references: the README table and the report cite the same entries."""
from pathlib import Path

from app.services.method_references import REFERENCES, cite, markdown_table

ROOT = Path(__file__).resolve().parents[3]


def test_readme_table_is_generated_from_the_reference_list():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert markdown_table() in readme, (
        "README 'Methods and citations' table differs from method_references.py; regenerate it "
        "with `python -c \"from app.services.method_references import markdown_table; print(markdown_table())\"`")


def test_report_sentences_cite_from_the_list():
    from app.services import report_function

    assert cite("quantile_normalization") in report_function._NORMALIZATION_REPORT_LABELS["quantile"]
    assert cite("vsn") in report_function._NORMALIZATION_REPORT_LABELS["vsn"]
    assert cite("welch_t") in report_function._TEST_TYPE_REPORT_LABELS["unpaired_welch"]
    assert cite("localization_class_i") in report_function.CLASS_I_SENTENCE


def test_every_reference_is_citable():
    for key, reference in REFERENCES.items():
        assert reference.doi or reference.detail, key
        assert cite(key)
