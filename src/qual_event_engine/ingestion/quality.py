from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    total_characters: int
    printable_ratio: float
    entropy: float
    gibberish_score: float
    quality_grade: str  # GOOD, PARTIAL, OCR_REQUIRED, FAILED, UNSUPPORTED


def calculate_shannon_entropy(text: str) -> float:
    """Calculate the Shannon entropy of text to detect encryption or compressed junk."""
    if not text:
        return 0.0
    frequencies: dict[str, int] = {}
    for char in text:
        frequencies[char] = frequencies.get(char, 0) + 1
    length = len(text)
    entropy = 0.0
    for count in frequencies.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def evaluate_text_quality(text: str) -> QualityMetrics:
    """Evaluate extraction quality based on length, printable character ratio, and entropy."""
    if not text or not text.strip():
        return QualityMetrics(
            total_characters=0,
            printable_ratio=0.0,
            entropy=0.0,
            gibberish_score=1.0,
            quality_grade="FAILED",
        )

    clean = text.strip()
    total = len(clean)
    printable = sum(1 for c in clean if c.isprintable() or c in "\n\r\t")
    printable_ratio = printable / total if total > 0 else 0.0
    entropy = calculate_shannon_entropy(clean)

    # Count alphanumeric vs total
    alnum = sum(1 for c in clean if c.isalnum())
    alnum_ratio = alnum / total if total > 0 else 0.0

    # High gibberish if printable ratio is low or entropy is excessively high
    gibberish_score = max(0.0, 1.0 - printable_ratio)
    if alnum_ratio < 0.2:
        gibberish_score = max(gibberish_score, 0.6)

    if total < 100:
        grade = "OCR_REQUIRED" if total < 50 else "PARTIAL"
    elif printable_ratio >= 0.95 and alnum_ratio >= 0.4 and entropy >= 3.0:
        grade = "GOOD"
    elif printable_ratio >= 0.8:
        grade = "PARTIAL"
    else:
        grade = "OCR_REQUIRED"

    return QualityMetrics(
        total_characters=total,
        printable_ratio=round(printable_ratio, 4),
        entropy=round(entropy, 4),
        gibberish_score=round(gibberish_score, 4),
        quality_grade=grade,
    )
