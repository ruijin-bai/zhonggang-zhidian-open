import csv

from scripts.validate_business_handoff import FILE_SPECS, validate_handoff


def _write_headers(root):
    for _, (filename, headers) in FILE_SPECS.items():
        with (root / filename).open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(sorted(headers))


def test_business_handoff_blank_templates_fail_with_no_fake_evidence(tmp_path):
    _write_headers(tmp_path)
    result = validate_handoff(tmp_path)
    assert result["ready_for_import_review"] is False
    assert result["error_count"] == 0
    assert all(gate["current"] == 0 for gate in result["gates"])


def test_business_handoff_reports_missing_files_without_exposing_rows(tmp_path):
    result = validate_handoff(tmp_path)
    assert result["ready_for_import_review"] is False
    assert result["error_count"] == len(FILE_SPECS)
    assert "rows" not in result
