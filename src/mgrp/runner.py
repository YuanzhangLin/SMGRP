"""Two-call maximum implementation of the MGRP planning method."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from mgrp.client import OpenAICompatibleClient

from .anchors import ActionAnchorIndex
from .context import project_ui_map
from .evidence import LocalEvidenceIndex
from .models import EvidenceSnippet, Gap, GapAnalysis
from .prompts import ANALYZE_SYSTEM, ANALYZE_USER, GROUND_SYSTEM, GROUND_USER


@dataclass(frozen=True)
class MGRPPlannerConfig:
    """Independent switches used by MGRP and its controlled ablations."""

    use_anchors: bool = True
    retrieval_query: Literal["gap", "task"] = "gap"
    retrieval_policy: Literal["on_gap", "always"] = "on_gap"


FULL_CONFIG = MGRPPlannerConfig()
ABLATION_CONFIGS = {
    "mgrp_no_anchors": MGRPPlannerConfig(use_anchors=False),
    "mgrp_task_wide": MGRPPlannerConfig(retrieval_query="task"),
    "mgrp_always_retrieve": MGRPPlannerConfig(retrieval_policy="always"),
}


def config_for_method(method_name: str) -> MGRPPlannerConfig:
    if method_name in ABLATION_CONFIGS:
        return ABLATION_CONFIGS[method_name]
    # Planner-model sensitivity runs append a model suffix to the persisted
    # method id.  Preserve the intended ablation configuration for those
    # isolated records instead of silently falling back to the full method.
    for base_method, config in ABLATION_CONFIGS.items():
        if method_name.startswith(base_method + "_"):
            return config
    if method_name.startswith("mgrp"):
        return FULL_CONFIG
    # Custom methods without a named preset use minimal configuration.
    return MGRPPlannerConfig(use_anchors=False)


def _json_object(content: str) -> dict[str, Any]:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    return payload


def _analysis(payload: dict[str, Any]) -> GapAnalysis:
    gaps = []
    for raw in payload.get("gaps") or []:
        gaps.append(Gap(
            requirement_id=str(raw.get("requirement_id") or ""),
            gap_type=str(raw.get("gap_type") or "missing_effect"),
            description=str(raw.get("description") or ""),
            query_terms=tuple(str(item) for item in raw.get("query_terms") or []),
            preferred_artifacts=tuple(str(item) for item in raw.get("preferred_artifacts") or []),
        ))
    return GapAnalysis(
        requirements=list(payload.get("requirements") or []),
        knowledge_chain=list(payload.get("knowledge_chain") or []),
        initial_plan=[str(item) for item in payload.get("initial_plan") or []],
        gaps=gaps,
        confidence=float(payload.get("confidence") or 0.0),
    )


@dataclass(frozen=True)
class MGRPPlannerResult:
    method_name: str
    task_id: str
    app_id: str
    instruction: str
    steps: list[str]
    analysis: dict[str, Any]
    evidence: list[dict[str, Any]]
    requirement_coverage: list[dict[str, Any]]
    unresolved_gaps: list[str]
    route: str
    model: str
    duration_seconds: float
    prompt_tokens: int
    completion_tokens: int
    ui_map_excerpt_chars: int
    repository_files_indexed: int
    planner_config: dict[str, Any]

    def to_generation_record(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "task": {"task_id": self.task_id, "app_id": self.app_id, "instruction": self.instruction},
            "method": self.method_name,
            "generation": {
                "context": {
                    "method": self.method_name,
                    "source": "ui_map+local_action_evidence",
                    "evidence": self.evidence,
                    "metadata": {
                        "route": self.route,
                        "analysis": self.analysis,
                        "requirement_coverage": self.requirement_coverage,
                        "unresolved_gaps": self.unresolved_gaps,
                        "planner_config": self.planner_config,
                    },
                },
                "raw_output": "\n".join(f"{index}. {step}" for index, step in enumerate(self.steps, 1)),
                "steps": self.steps,
            },
            "provenance": {
                "source": f"{self.method_name}",
                "model": self.model,
                "duration_seconds": self.duration_seconds,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "ui_map_excerpt_chars": self.ui_map_excerpt_chars,
                "repository_files_indexed": self.repository_files_indexed,
            },
        }


class MGRPPlanner:
    def __init__(self, client: OpenAICompatibleClient, *, model: str | None = None,
                 method_name: str = "mgrp",
                 config: MGRPPlannerConfig | None = None) -> None:
        self.client = client
        self.model = model or client.model
        self.method_name = method_name
        self.config = config or config_for_method(method_name)

    def run(
        self,
        *,
        task_id: str,
        app_id: str,
        instruction: str,
        ui_map_path: Path,
        repository_root: Path | None = None,
        evidence_index: LocalEvidenceIndex | None = None,
        anchor_index: ActionAnchorIndex | None = None,
    ) -> MGRPPlannerResult:
        started = time.perf_counter()
        map_excerpt = project_ui_map(ui_map_path, instruction)
        if self.config.use_anchors and anchor_index is None and repository_root is not None:
            anchor_index = ActionAnchorIndex(repository_root)
        if not self.config.use_anchors:
            anchor_index = None
        anchor_candidates = anchor_index.search(instruction) if anchor_index else []
        anchors_text = ActionAnchorIndex.render(anchor_candidates)
        first = self.client.complete(
            system=ANALYZE_SYSTEM,
            user=ANALYZE_USER.format(instruction=instruction, ui_map=map_excerpt, anchors=anchors_text),
            model=self.model,
        )
        analysis = _analysis(_json_object(first.content))
        evidence: list[EvidenceSnippet] = []
        files_indexed = 0
        prompt_tokens = first.prompt_tokens or 0
        completion_tokens = first.completion_tokens or 0
        model = first.model

        should_retrieve = bool(analysis.gaps) or self.config.retrieval_policy == "always"
        retrieval_gaps = list(analysis.gaps)
        if should_retrieve and self.config.retrieval_query == "task":
            retrieval_gaps = [Gap(
                requirement_id="R_TASK",
                gap_type="task_wide",
                description=instruction,
                query_terms=tuple(instruction.split()),
                preferred_artifacts=(),
            )]
        elif should_retrieve and not retrieval_gaps:
            retrieval_gaps = [Gap(
                requirement_id="R_CHAIN",
                gap_type="chain_confirmation",
                description="Confirm the application-specific operation chain: "
                            + " ".join(analysis.initial_plan),
                query_terms=tuple(instruction.split()),
                preferred_artifacts=(),
            )]

        if should_retrieve:
            if evidence_index is None:
                if repository_root is None:
                    raise ValueError("repository_root is required when local evidence is requested")
                evidence_index = LocalEvidenceIndex(repository_root)
            files_indexed = evidence_index.files_indexed
            evidence = evidence_index.trace(retrieval_gaps, global_query=instruction)
            if anchor_index:
                gap_query = instruction + " " + " ".join(gap.description for gap in retrieval_gaps)
                gap_anchors = anchor_index.search(gap_query, max_results=10)
                anchor_evidence = [
                    EvidenceSnippet(
                        path=anchor.declaration,
                        line=0,
                        text=ActionAnchorIndex.render([anchor]),
                        score=anchor.score,
                        gap_type="ui_code_anchor",
                    )
                    for anchor in gap_anchors
                ]
                evidence = (anchor_evidence + evidence)[:24]
            evidence_text = "\n".join(
                f"[{item.path}:{item.line}] ({item.gap_type}) {item.text}" for item in evidence
            ) or "No supporting repository evidence found within the retrieval budget."
            second = self.client.complete(
                system=GROUND_SYSTEM,
                user=GROUND_USER.format(
                    instruction=instruction,
                    analysis=json.dumps(analysis.to_dict(), ensure_ascii=False),
                    evidence=evidence_text,
                ),
                model=self.model,
            )
            grounded = _json_object(second.content)
            steps = [str(item) for item in grounded.get("steps") or []]
            coverage = list(grounded.get("requirement_coverage") or [])
            unresolved = [str(item) for item in grounded.get("unresolved_gaps") or []]
            prompt_tokens += second.prompt_tokens or 0
            completion_tokens += second.completion_tokens or 0
            model = second.model
            route = "slow_local_evidence" if analysis.gaps else "always_local_evidence"
        else:
            steps = analysis.initial_plan
            coverage = []
            unresolved = []
            route = "fast_map_only"

        return MGRPPlannerResult(
            method_name=self.method_name,
            task_id=task_id,
            app_id=app_id,
            instruction=instruction,
            steps=steps,
            analysis=analysis.to_dict(),
            evidence=[asdict(item) for item in evidence],
            requirement_coverage=coverage,
            unresolved_gaps=unresolved,
            route=route,
            model=model,
            duration_seconds=round(time.perf_counter() - started, 6),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            ui_map_excerpt_chars=len(map_excerpt),
            repository_files_indexed=files_indexed,
            planner_config=asdict(self.config),
        )
