"""Blend LLM output with the deterministic heuristic advisor.

The product deliberately keeps two independent views of the same agronomic
evidence:

* the LLM explains the recommendation in natural language, and
* the deterministic heuristic engine derives an auditable answer directly
  from the rule-engine scores.

Neither view is thrown away. This module merges them field by field so the
farmer receives one answer that contains both the human-readable explanation
and the transparent rule-engine check. ``AI_WEIGHT`` remains the authority for
numeric scoring in the recommendation service; here the weight is used to
decide how much room each view gets in the combined confidence signal.
"""

from __future__ import annotations

from typing import Iterable

from app.ai.base import AIAnalysis, AICropAssessment
from app.schemas import AdvicePlan

_CONFIDENCE_VALUE = {"low": 1.0, "medium": 2.0, "high": 3.0}
_VALUE_CONFIDENCE = ((2.5, "high"), (1.5, "medium"), (0.0, "low"))


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _dedupe(items: Iterable[str], limit: int) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = _clean(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _merge_text(
    ai_text: str | None,
    heuristic_text: str | None,
    *,
    marker: str,
    limit: int = 900,
) -> str:
    """Join the two narratives without repeating identical sentences."""

    ai_value = _clean(ai_text)
    heuristic_value = _clean(heuristic_text)
    if not ai_value:
        return heuristic_value
    if not heuristic_value:
        return ai_value
    if heuristic_value.casefold() in ai_value.casefold():
        return ai_value
    if ai_value.casefold() in heuristic_value.casefold():
        return heuristic_value
    combined = f"{ai_value} {marker}{heuristic_value}"
    return combined[:limit].rstrip(" ,;") + ("…" if len(combined) > limit else "")


def _blend_confidence(
    ai_confidence: str,
    heuristic_confidence: str,
    weight: float,
) -> str:
    weight = max(0.0, min(1.0, weight))
    ai_value = _CONFIDENCE_VALUE.get(ai_confidence, 2.0)
    heuristic_value = _CONFIDENCE_VALUE.get(heuristic_confidence, 2.0)
    blended = weight * ai_value + (1.0 - weight) * heuristic_value
    for threshold, label in _VALUE_CONFIDENCE:
        if blended >= threshold:
            return label
    return "low"


def _blend_assessment(
    ai_item: AICropAssessment | None,
    heuristic_item: AICropAssessment | None,
) -> AICropAssessment | None:
    if ai_item is None and heuristic_item is None:
        return None
    if ai_item is None:
        return heuristic_item
    if heuristic_item is None:
        return ai_item

    return AICropAssessment(
        crop_key=ai_item.crop_key,
        ai_score=ai_item.ai_score,
        rationale=_merge_text(
            ai_item.rationale,
            heuristic_item.rationale,
            marker="Rule-engine check: ",
        ),
        risks=_dedupe(
            [*ai_item.risks, *heuristic_item.risks],
            limit=5,
        ),
        actions=_dedupe(
            [*ai_item.actions, *heuristic_item.actions],
            limit=6,
        ),
        planting_window=ai_item.planting_window or heuristic_item.planting_window,
    )


def blend_analysis(
    ai_result: AIAnalysis | None,
    heuristic_result: AIAnalysis,
    weight: float,
) -> AIAnalysis:
    """Return one analysis that contains the AI view and the heuristic check."""

    if ai_result is None:
        return heuristic_result

    ai_items = {item.crop_key: item for item in ai_result.crops}
    heuristic_items = {item.crop_key: item for item in heuristic_result.crops}
    ordered_keys = [*heuristic_items, *[key for key in ai_items if key not in heuristic_items]]

    crops: list[AICropAssessment] = []
    for key in ordered_keys:
        blended = _blend_assessment(ai_items.get(key), heuristic_items.get(key))
        if blended is not None:
            crops.append(blended)

    return AIAnalysis(
        summary=_merge_text(
            ai_result.summary,
            heuristic_result.summary,
            marker="Rule-engine check: ",
        ),
        crops=crops,
        general_risks=_dedupe(
            [*ai_result.general_risks, *heuristic_result.general_risks],
            limit=8,
        ),
        general_actions=_dedupe(
            [*ai_result.general_actions, *heuristic_result.general_actions],
            limit=8,
        ),
        confidence=_blend_confidence(
            ai_result.confidence,
            heuristic_result.confidence,
            weight,
        ),
        notes=_merge_text(
            ai_result.notes,
            heuristic_result.notes,
            marker="Rule-engine check: ",
        ),
    )


def blend_advice(
    ai_plan: AdvicePlan | None,
    heuristic_plan: AdvicePlan,
    weight: float,
) -> AdvicePlan:
    """Combine the AI explanation with the deterministic advice plan."""

    if ai_plan is None:
        return heuristic_plan

    return AdvicePlan(
        # The AI headline reads naturally; fall back to the deterministic one.
        headline=_clean(ai_plan.headline) or _clean(heuristic_plan.headline),
        why=_merge_text(
            ai_plan.why,
            heuristic_plan.why,
            marker="Rule-engine check: ",
        ),
        commentary=_merge_text(
            ai_plan.commentary,
            heuristic_plan.commentary,
            marker="Rule-engine note: ",
            limit=1200,
        ),
        steps=_dedupe([*ai_plan.steps, *heuristic_plan.steps], limit=6),
        grow=_dedupe([*ai_plan.grow, *heuristic_plan.grow], limit=6),
        feed=_dedupe([*ai_plan.feed, *heuristic_plan.feed], limit=5),
        care=_dedupe([*ai_plan.care, *heuristic_plan.care], limit=6),
        risks=_dedupe([*ai_plan.risks, *heuristic_plan.risks], limit=5),
        ask_farmer=_dedupe(
            [*ai_plan.ask_farmer, *heuristic_plan.ask_farmer],
            limit=4,
        ),
        confidence=_blend_confidence(
            ai_plan.confidence,
            heuristic_plan.confidence,
            weight,
        ),
    )
