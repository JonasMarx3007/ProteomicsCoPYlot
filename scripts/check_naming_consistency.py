from __future__ import annotations

import sys
from pathlib import Path


def _expect_exists(path: Path, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"Missing required file: {path}")


def _expect_missing(path: Path, errors: list[str]) -> None:
    if path.exists():
        errors.append(f"Unexpected legacy/duplicate file present: {path}")


def _expect_contains(path: Path, needle: str, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"Cannot validate missing file: {path}")
        return
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        errors.append(f"Expected text not found in {path}: {needle}")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []

    report_service = repo_root / "backend" / "app" / "services" / "report_function.py"
    report_service_legacy = repo_root / "backend" / "app" / "services" / "report_functions.py"

    completeness_page = (
        repo_root / "frontend" / "src" / "features" / "completeness" / "CompletenessPage.tsx"
    )
    completeness_page_legacy = (
        repo_root / "frontend" / "src" / "features" / "data" / "CompletenessPage.tsx"
    )

    summary_duplicates = [
        repo_root / "frontend" / "src" / "features" / "summary" / "SummaryTablesPage.tsx",
        repo_root / "frontend" / "src" / "features" / "summary" / "SummaryTextPage.tsx",
        repo_root / "frontend" / "src" / "features" / "summary" / "SummaryReportPage.tsx",
    ]

    completeness_wrappers = [
        repo_root / "frontend" / "src" / "features" / "completeness" / "MissingValuePlotPage.tsx",
        repo_root
        / "frontend"
        / "src"
        / "features"
        / "completeness"
        / "MissingValueHeatmapPage.tsx",
        repo_root / "frontend" / "src" / "features" / "completeness" / "CompletenessTablesPage.tsx",
    ]

    _expect_exists(report_service, errors)
    _expect_missing(report_service_legacy, errors)

    _expect_exists(completeness_page, errors)
    _expect_missing(completeness_page_legacy, errors)

    for duplicate in summary_duplicates:
        _expect_missing(duplicate, errors)

    for wrapper in completeness_wrappers:
        _expect_contains(wrapper, 'from "./CompletenessPage"', errors)

    if errors:
        print("Naming consistency check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Naming consistency check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
