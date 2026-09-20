from __future__ import annotations

from dataclasses import dataclass

from qual_event_engine.domain.enums import RelationshipType


@dataclass(frozen=True, slots=True)
class EntityRelationship:
    parent_isin: str
    child_isin: str
    relationship_type: RelationshipType
    ownership_pct: float | None = None
    pass_through_confidence: float = 0.85


class RelationshipGraph:
    """Tracks parent-subsidiary, joint venture, and promoter relationships."""

    def __init__(self) -> None:
        self._parent_to_children: dict[str, list[EntityRelationship]] = {}
        self._child_to_parents: dict[str, list[EntityRelationship]] = {}

    def add_relationship(
        self,
        parent_isin: str,
        child_isin: str,
        relationship_type: RelationshipType,
        ownership_pct: float | None = None,
        pass_through_confidence: float = 0.85,
    ) -> None:
        rel = EntityRelationship(
            parent_isin=parent_isin,
            child_isin=child_isin,
            relationship_type=relationship_type,
            ownership_pct=ownership_pct,
            pass_through_confidence=pass_through_confidence,
        )
        self._parent_to_children.setdefault(parent_isin, []).append(rel)
        self._child_to_parents.setdefault(child_isin, []).append(rel)

    def get_children(self, parent_isin: str) -> list[EntityRelationship]:
        return self._parent_to_children.get(parent_isin, [])

    def get_parents(self, child_isin: str) -> list[EntityRelationship]:
        return self._child_to_parents.get(child_isin, [])

    def resolve_listed_parent(self, unlisted_isin_or_entity: str) -> tuple[str, float] | None:
        """If an event occurs at an unlisted subsidiary, find the listed parent and confidence factor."""
        parents = self.get_parents(unlisted_isin_or_entity)
        if not parents:
            return None
        # Return first primary parent
        primary = parents[0]
        return primary.parent_isin, primary.pass_through_confidence
