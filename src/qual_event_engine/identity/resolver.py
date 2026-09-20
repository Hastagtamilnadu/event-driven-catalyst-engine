from __future__ import annotations

import logging
from dataclasses import dataclass
from difflib import SequenceMatcher

from qual_event_engine.identity.aliases import AliasManager
from qual_event_engine.identity.relationships import RelationshipGraph

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    isin: str | None
    symbol: str | None
    legal_name: str
    confidence: float
    match_method: str  # EXACT_ISIN, EXACT_SYMBOL, EXACT_NAME, ALIAS_MATCH, FUZZY_NAME, UNRESOLVED
    requires_review: bool = False


class EntityResolver:
    """Resolves arbitrary corporate mentions to canonical security identifiers (ISIN / Symbol)."""

    def __init__(
        self,
        alias_manager: AliasManager | None = None,
        relationship_graph: RelationshipGraph | None = None,
    ) -> None:
        self.aliases = alias_manager or AliasManager()
        self.relationships = relationship_graph or RelationshipGraph()
        self._isin_to_meta: dict[str, dict[str, str]] = {}
        self._symbol_to_isin: dict[str, str] = {}
        self._name_to_isin: dict[str, str] = {}

    def register_security(self, isin: str, symbol: str, legal_name: str) -> None:
        meta = {"isin": isin, "symbol": symbol.upper(), "legal_name": legal_name}
        self._isin_to_meta[isin] = meta
        self._symbol_to_isin[symbol.upper()] = isin
        norm_name = self.aliases.normalize_name(legal_name)
        if norm_name:
            self._name_to_isin[norm_name] = isin
        self.aliases.register_alias(isin, symbol)
        self.aliases.register_alias(isin, legal_name)

    def resolve(
        self,
        raw_name: str,
        symbol_hint: str | None = None,
        isin_hint: str | None = None,
    ) -> ResolvedEntity:
        # 1. Exact ISIN match
        if isin_hint and isin_hint in self._isin_to_meta:
            meta = self._isin_to_meta[isin_hint]
            return ResolvedEntity(
                isin=isin_hint,
                symbol=meta.get("symbol"),
                legal_name=meta.get("legal_name", raw_name),
                confidence=1.0,
                match_method="EXACT_ISIN",
                requires_review=False,
            )

        # 2. Exact Symbol match
        if symbol_hint:
            sym_clean = symbol_hint.upper().strip()
            if sym_clean in self._symbol_to_isin:
                isin = self._symbol_to_isin[sym_clean]
                meta = self._isin_to_meta.get(isin, {})
                return ResolvedEntity(
                    isin=isin,
                    symbol=sym_clean,
                    legal_name=meta.get("legal_name", raw_name),
                    confidence=1.0,
                    match_method="EXACT_SYMBOL",
                    requires_review=False,
                )

        # 3. Exact Normalized Name match
        norm = self.aliases.normalize_name(raw_name)
        if norm in self._name_to_isin:
            isin = self._name_to_isin[norm]
            meta = self._isin_to_meta.get(isin, {})
            return ResolvedEntity(
                isin=isin,
                symbol=meta.get("symbol"),
                legal_name=meta.get("legal_name", raw_name),
                confidence=0.98,
                match_method="EXACT_NAME",
                requires_review=False,
            )

        # 4. Alias lookup
        alias_isin = self.aliases.lookup(raw_name)
        if alias_isin and alias_isin in self._isin_to_meta:
            meta = self._isin_to_meta[alias_isin]
            return ResolvedEntity(
                isin=alias_isin,
                symbol=meta.get("symbol"),
                legal_name=meta.get("legal_name", raw_name),
                confidence=0.92,
                match_method="ALIAS_MATCH",
                requires_review=False,
            )

        # 5. Fuzzy Match against known names
        best_match_isin: str | None = None
        best_ratio = 0.0
        for known_norm, isin in self._name_to_isin.items():
            ratio = SequenceMatcher(None, norm, known_norm).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_isin = isin

        if best_ratio >= 0.85 and best_match_isin:
            meta = self._isin_to_meta.get(best_match_isin, {})
            return ResolvedEntity(
                isin=best_match_isin,
                symbol=meta.get("symbol"),
                legal_name=meta.get("legal_name", raw_name),
                confidence=round(best_ratio, 2),
                match_method="FUZZY_NAME",
                requires_review=best_ratio < 0.90,
            )

        if best_ratio >= 0.65 and best_match_isin:
            meta = self._isin_to_meta.get(best_match_isin, {})
            return ResolvedEntity(
                isin=best_match_isin,
                symbol=meta.get("symbol"),
                legal_name=meta.get("legal_name", raw_name),
                confidence=round(best_ratio, 2),
                match_method="FUZZY_NAME",
                requires_review=True,
            )

        # Unresolved
        return ResolvedEntity(
            isin=None,
            symbol=symbol_hint,
            legal_name=raw_name,
            confidence=0.0,
            match_method="UNRESOLVED",
            requires_review=True,
        )
