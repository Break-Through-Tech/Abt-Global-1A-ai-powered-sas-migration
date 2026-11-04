
import csv
from collections import Counter
from pathlib import Path

# Locate the repository root relative to this test file.
ROOT = Path(__file__).resolve().parents[1]

ARTIFACT = (
    ROOT
    / "data"
    / "Project_1"
    / "SAS Output CSV"
    / "STAR_2025JUL.csv"
)

EXPECTED_PEER_GROUPS = {
    "1) # of groups=3": 141,
    "2) # of groups=4": 515,
    "3) # of groups=5": 2235,
}


def load_rows():
    with ARTIFACT.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def test_rated_hospital_count():
    rows = load_rows()

    rated = [
        row for row in rows
        if row["report_indicator"] == "1"
    ]

    assert len(rated) == 2891


def test_peer_group_counts():
    rows = load_rows()

    rated = [
        row for row in rows
        if row["report_indicator"] == "1"
    ]

    counts = Counter(row["cnt_grp"] for row in rated)

    assert counts == EXPECTED_PEER_GROUPS


def test_rated_hospitals_have_star_ratings():
    rows = load_rows()

    rated = [
        row for row in rows
        if row["report_indicator"] == "1"
    ]

    assert all(row["star"] in {"1", "2", "3", "4", "5"} for row in rated)


def test_unrated_hospitals_have_no_star_rating():
    rows = load_rows()

    unrated = [
        row for row in rows
        if row["report_indicator"] == "0"
    ]

    assert all(row["star"] == "" for row in unrated)


def test_rated_hospital_ids_are_unique():
    rows = load_rows()

    rated_ids = [
        row["PROVIDER_ID"]
        for row in rows
        if row["report_indicator"] == "1"
    ]

    assert len(rated_ids) == len(set(rated_ids))
