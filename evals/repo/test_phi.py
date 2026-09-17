"""Every PHI pattern fires on a sample and none fires on the repo's synthetic vocabulary."""

from __future__ import annotations

import pytest

from c2r.phi import PATTERNS, find_phi

SAMPLES = [
    ("ssn", "patient SSN 123-45-6789 on file"),
    ("mrn", "MRN: 1234567"),
    ("dob", "DOB: 01/02/1980"),
    ("phone", "call 555-867-5309 before pickup"),
    ("street_address", "pickup at 12 Harbor Street"),
]
NON_MATCHES = ["Node 17, Zone C", "06:30", "P14", "V3", "2026-09-17", "240 min"]


def test_every_pattern_has_a_sample() -> None:
    assert [name for name, _ in SAMPLES] == list(PATTERNS)


@pytest.mark.parametrize(("name", "sample"), SAMPLES)
def test_pattern_matches_its_sample(name: str, sample: str) -> None:
    assert find_phi(sample) == [name]


@pytest.mark.parametrize("text", NON_MATCHES)
def test_synthetic_vocabulary_is_clean(text: str) -> None:
    assert find_phi(text) == []


def test_find_phi_returns_names_in_dict_order() -> None:
    combined = "MRN: 1234567 and SSN 123-45-6789"
    assert find_phi(combined) == ["ssn", "mrn"]
