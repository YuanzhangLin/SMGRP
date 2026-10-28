"""Data contracts for the MGRP planning pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Gap:
    requirement_id: str
    gap_type: str
    description: str
    query_terms: tuple[str, ...] = ()
    preferred_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceSnippet:
    path: str
    line: int
    text: str
    score: float
    gap_type: str


@dataclass
class GapAnalysis:
    requirements: list[dict[str, Any]] = field(default_factory=list)
    knowledge_chain: list[dict[str, Any]] = field(default_factory=list)
    initial_plan: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirements": self.requirements,
            "knowledge_chain": self.knowledge_chain,
            "initial_plan": self.initial_plan,
            "gaps": [asdict(gap) for gap in self.gaps],
            "confidence": self.confidence,
        }
