from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GroundingEvidence:
    verbatim_quote: str
    page_number: int | None
    bounding_box: tuple[float, float, float, float] | None  # (x0, y0, x1, y1)
    is_verbatim: bool
    context_window: str


class EvidenceValidator:
    """Verifies that extracted facts are strictly grounded in the verbatim text of the source document."""

    @staticmethod
    def normalize_snippet(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip().lower()
        # Remove punctuation for fuzzy comparison
        return re.sub(r"[^\w\s]", "", cleaned)

    @classmethod
    def verify_grounding(
        cls,
        quote: str,
        document_text: str,
        page_texts: list[str] | None = None,
    ) -> GroundingEvidence:
        if not quote or not document_text:
            return GroundingEvidence(
                verbatim_quote=quote,
                page_number=None,
                bounding_box=None,
                is_verbatim=False,
                context_window="",
            )

        # 1. Exact substring check
        if quote in document_text:
            idx = document_text.find(quote)
            start = max(0, idx - 100)
            end = min(len(document_text), idx + len(quote) + 100)
            ctx = document_text[start:end]

            page_num = None
            if page_texts:
                for p_idx, p_text in enumerate(page_texts, start=1):
                    if quote in p_text:
                        page_num = p_idx
                        break

            return GroundingEvidence(
                verbatim_quote=quote,
                page_number=page_num,
                bounding_box=None,
                is_verbatim=True,
                context_window=ctx,
            )

        # 2. Normalized check (ignoring case, whitespace, punctuation differences)
        norm_quote = cls.normalize_snippet(quote)
        norm_doc = cls.normalize_snippet(document_text)

        if norm_quote and norm_quote in norm_doc:
            return GroundingEvidence(
                verbatim_quote=quote,
                page_number=None,
                bounding_box=None,
                is_verbatim=True,
                context_window="Normalized match found in document text",
            )

        return GroundingEvidence(
            verbatim_quote=quote,
            page_number=None,
            bounding_box=None,
            is_verbatim=False,
            context_window="",
        )
