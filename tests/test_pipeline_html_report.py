"""Standalone HTML report for saved full-pipeline validation runs."""

import json
from pathlib import Path

import pytest
from test_pipeline_report import (  # type: ignore[import-not-found]
    FAKE_KEY,
    _write,
    chain,  # noqa: F401 - pytest fixture reused from the report tests
    report,
    saved_run,
)

from sasguard.data import load_artifact


def html_of(tmp_path: Path) -> str:
    return (tmp_path / "reports/runs/out/report.html").read_text(encoding="utf-8")


def test_verified_run_has_badge_chart_and_matching_counts(
    chain: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    run = saved_run(chain, tmp_path)
    data, _, _ = report(tmp_path, run)
    page = html_of(tmp_path)
    assert "SASGuard pipeline validation" in page
    assert "VERIFIED" in page and "NOT VERIFIED" not in page
    assert 'aria-label="Star rating distribution"' in page
    for count in data["star_distribution"].values():
        assert f"<output>{count:,}</output>" in page
    assert "This is not Abt or CMS approval" in page
    assert "no recorded human review" in page


def test_not_verified_run_withholds_the_distribution(
    chain: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    run = saved_run(chain, tmp_path, keep_program2=False)
    report(tmp_path, run)
    page = html_of(tmp_path)
    assert "NOT VERIFIED" in page
    assert "Star rating distribution" not in page
    assert "Hospital counts are unavailable" in page
    assert "must not be used as such" in page


def test_provider_key_is_not_in_html(
    chain: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    def corrupt(run: Path) -> None:
        path = run / "program1" / "process.csv"
        frame = load_artifact(path, key="PROVIDER_ID").frame
        row = int(frame.index[frame["GRP_SCORE"].notna()][0])
        frame.loc[row, "GRP_SCORE"] = frame.loc[row, "GRP_SCORE"] + 1e-6
        _write(frame, path)

    run = saved_run(chain, tmp_path, before_validate=corrupt)
    key = json.loads((run / "pipeline-validation.json").read_text())["earliest_divergence"]["key"]
    assert key
    report(tmp_path, run)
    page = html_of(tmp_path)
    assert key not in page
    assert "Earliest divergence: Program 1, artifact PROCESS, value; column GRP_SCORE" in page


def test_unexpected_header_is_not_in_html(
    chain: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    def add_header(run: Path) -> None:
        path = run / "program1" / "process.csv"
        frame = load_artifact(path, key="PROVIDER_ID").frame
        frame["010001"] = 1.0
        _write(frame, path)

    run = saved_run(chain, tmp_path, before_validate=add_header)
    report(tmp_path, run)
    page = html_of(tmp_path)
    assert "010001" not in page
    assert "not in the SAS schema" in page


def test_secret_like_note_is_redacted(
    chain: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOME_API_KEY", FAKE_KEY)
    run = saved_run(chain, tmp_path, note=f"used api_key={FAKE_KEY} locally")
    report(tmp_path, run)
    page = html_of(tmp_path)
    assert FAKE_KEY not in page
    assert "[redacted]" in page


def test_note_markup_is_escaped_and_page_is_self_contained(
    chain: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    run = saved_run(chain, tmp_path, note="<script>alert(1)</script>")
    report(tmp_path, run)
    page = html_of(tmp_path)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    lowered = page.lower()
    assert "<script" not in lowered
    assert "http://" not in lowered and "https://" not in lowered
