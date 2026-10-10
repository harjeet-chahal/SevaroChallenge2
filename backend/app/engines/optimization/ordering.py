"""Deterministic display ordering. IDs are compared as text with digit runs as numbers
("P9" before "P10"); this is ordering only and never feeds an eligibility decision."""

from __future__ import annotations

import re

_DIGITS = re.compile(r"(\d+)")


def natural_key(value: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in _DIGITS.split(value))
