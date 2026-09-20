from __future__ import annotations

import re

from qual_event_engine.domain.schemas import FactExtraction
from qual_event_engine.events.evidence import EvidenceValidator


class FactExtractor:
    """Extracts structured financial and operational facts from filing text."""

    @classmethod
    def extract_order_win_facts(cls, text: str, symbol: str) -> FactExtraction:
        # Regex heuristics for contract value
        val_match = re.search(r"(?:Rs\.?|INR|worth|value of)\s*([\d,]+(?:\.\d+)?)\s*(?:Cr(?:ore)?|lakh|million)?", text, re.IGNORECASE)
        contract_val = None
        if val_match:
            try:
                num = float(val_match.group(1).replace(",", ""))
                if "cr" in val_match.group(0).lower():
                    contract_val = num * 1e7
                elif "lakh" in val_match.group(0).lower():
                    contract_val = num * 1e5
                else:
                    contract_val = num
            except ValueError:
                contract_val = None

        # Look for excerpt
        excerpt = text[:200].strip() if text else ""
        grounding = EvidenceValidator.verify_grounding(excerpt, text)

        return FactExtraction(
            entity_name=symbol,
            event_type="ORDER_WIN",
            firmness_level=4 if contract_val else 3,
            headline=excerpt[:100],
            verbatim_quote=excerpt,
            contract_value_inr=contract_val,
            grounding_score=1.0 if grounding.is_verbatim else 0.0,
        )
