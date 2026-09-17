"""PHI regex table used by the no-PHI write guard."""

from __future__ import annotations

import re

PATTERNS: dict[str, re.Pattern[str]] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "mrn": re.compile(r"\bMRN\s*[:#]?\s*\d{5,}\b", re.IGNORECASE),
    "dob": re.compile(
        r"\b(DOB|date of birth)\b\s*[:#]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        re.IGNORECASE,
    ),
    "phone": re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
    "street_address": re.compile(
        r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way)\b\.?"
    ),
}


def find_phi(text: str) -> list[str]:
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]
