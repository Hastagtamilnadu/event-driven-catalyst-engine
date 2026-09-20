from __future__ import annotations

import re
from collections.abc import Iterable


class AliasManager:
    """Manages legal names, trading symbols, acronyms, and common aliases for entities."""

    def __init__(self) -> None:
        self._alias_to_isin: dict[str, str] = {}
        self._isin_to_aliases: dict[str, set[str]] = {}

    def normalize_name(self, name: str) -> str:
        """Standardize corporate name by stripping suffixes, punctuation, and extra spaces."""
        cleaned = name.upper().strip()
        cleaned = re.sub(r"\b(LIMITED|LTD\.?|PVT\.?|PRIVATE|CORP\.?|CORPORATION|INC\.?|LLP|PLC)\b", "", cleaned)
        cleaned = re.sub(r"[^\w\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def register_alias(self, isin: str, alias: str) -> None:
        norm = self.normalize_name(alias)
        if norm:
            self._alias_to_isin[norm] = isin
            self._isin_to_aliases.setdefault(isin, set()).add(norm)
        # Also register raw uppercase
        raw_upper = alias.upper().strip()
        if raw_upper:
            self._alias_to_isin[raw_upper] = isin
            self._isin_to_aliases.setdefault(isin, set()).add(raw_upper)

    def register_aliases(self, isin: str, aliases: Iterable[str]) -> None:
        for alias in aliases:
            self.register_alias(isin, alias)

    def lookup(self, name_or_alias: str) -> str | None:
        raw_upper = name_or_alias.upper().strip()
        if raw_upper in self._alias_to_isin:
            return self._alias_to_isin[raw_upper]
        norm = self.normalize_name(name_or_alias)
        return self._alias_to_isin.get(norm)

    def get_aliases_for_isin(self, isin: str) -> set[str]:
        return self._isin_to_aliases.get(isin, set())
