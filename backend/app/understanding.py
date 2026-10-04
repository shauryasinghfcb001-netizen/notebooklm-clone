"""Deterministic, source-grounded planning for the personal Understanding Agent.

This module intentionally does not call a model. It makes the first useful
decision locally, remains auditable, and can later be replaced by a configured
provider without changing the API contract.
"""
from __future__ import annotations

import re

BEGINNER_SIGNALS = {"new", "beginner", "simple", "basics", "start", "first time", "explain"}
ADVANCED_SIGNALS = {"advanced", "expert", "technical", "implementation", "deep dive", "research"}
STOP_WORDS = {"about", "after", "again", "also", "and", "are", "ask", "can", "for", "from", "have", "how", "into", "its", "more", "need", "not", "that", "the", "this", "what", "with", "your"}


def _level(goal: str) -> str:
    text = goal.lower()
    if any(word in text for word in ADVANCED_SIGNALS):
        return "advanced"
    if any(word in text for word in BEGINNER_SIGNALS):
        return "beginner"
    return "general"


def _terms(passages: list[dict]) -> list[str]:
    words: dict[str, int] = {}
    for passage in passages:
        for word in re.findall(r"[A-Za-z][A-Za-z-]{3,}", passage.get("text", "").lower()):
            if word not in STOP_WORDS:
                words[word] = words.get(word, 0) + 1
    return [word for word, _ in sorted(words.items(), key=lambda item: (-item[1], item[0]))[:6]]


def build_brief(goal: str, passages: list[dict]) -> dict:
    """Create an inspectable personal learning plan from retrieved passages."""
    goal = (goal or "Understand the key ideas clearly").strip()
    level = _level(goal)
    terms = _terms(passages)
    sources, seen = [], set()
    for passage in passages:
        source_id = passage.get("source_id")
        if source_id and source_id not in seen:
            seen.add(source_id)
            sources.append({"source_id": source_id, "source_title": passage.get("stitle", "Source"), "chunk_id": passage.get("id")})
    if level == "beginner":
        format_name, steps = "plain-language guide", ["Start with a plain-language overview and define unfamiliar terms.", "Work through one concrete example from the sources.", "Use a short quiz or flashcards to check the foundation."]
    elif level == "advanced":
        format_name, steps = "decision brief", ["Map the central claims, assumptions, and evidence.", "Compare tensions or alternatives across the sources.", "Create a report with open questions and next actions."]
    else:
        format_name, steps = "guided explainer", ["Get a concise overview of the key ideas and their relationships.", "Explore the strongest supporting passages and examples.", "Turn the result into a mind map, quiz, or report based on what helps most."]
    return {"goal": goal, "audience_level": level, "recommended_format": format_name,
            "why": f"The agent selected a {format_name} for a {level} learner and kept the plan grounded in the enabled sources.",
            "learning_path": steps, "key_terms": terms, "grounding": sources[:5], "provider": "local-planner"}
