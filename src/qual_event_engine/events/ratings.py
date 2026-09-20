from __future__ import annotations

import re

_GRADES = {
    "D": 0,
    "C": 1,
    "B-": 2,
    "B": 3,
    "B+": 4,
    "BB-": 5,
    "BB": 6,
    "BB+": 7,
    "BBB-": 8,
    "BBB": 9,
    "BBB+": 10,
    "A-": 11,
    "A": 12,
    "A+": 13,
    "AA-": 14,
    "AA": 15,
    "AA+": 16,
    "AAA": 17,
}


def ordinal(rating: str | None) -> int | None:
    if not rating:
        return None
    normalised = rating.upper().replace(" ", "")
    candidates = re.findall(r"AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|C|D", normalised)
    if not candidates:
        return None
    return _GRADES.get(candidates[0])


def verified_upgrade(previous_rating: str | None, new_rating: str | None) -> bool:
    previous = ordinal(previous_rating)
    new = ordinal(new_rating)
    return previous is not None and new is not None and new > previous
