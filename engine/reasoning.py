from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReasoningDecision:
    requested: str
    effective: str
    score: int
    reason: str


_SIMPLE_PATTERNS = (
    r"^(hi|hey|hello|yo|sup|thanks|thank you|good morning|good afternoon|good evening)[!.?\s]*$",
    r"^(ok|okay|cool|nice|got it|sounds good|test)[!.?\s]*$",
)

_DEEP_TERMS = (
    "root cause", "trade-off", "tradeoff", "edge case", "race condition", "deadlock",
    "concurrency", "architecture", "derive", "prove", "proof", "optimize", "optimization",
    "complexity", "formal", "invariant", "threat model", "failure mode", "debug this",
    "compare approaches", "compare options", "evaluate alternatives", "multi-step",
    "step by step", "reason through", "deep analysis", "deeply analyze", "rigorous",
)

_STANDARD_TERMS = (
    "explain", "why", "how", "analyze", "compare", "debug", "review", "design",
    "plan", "calculate", "estimate", "recommend", "solve", "evaluate", "summarize",
)


def _clean(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def decide(requested_mode: str, prompt: str) -> ReasoningDecision:
    """Resolve one user-selected reasoning mode without an extra model call.

    Explicit Standard/Deep are hard overrides. Auto uses a fast local heuristic to
    choose Direct, Standard, or Deep for this turn. This router never invokes the
    LLM, so Auto does not add a planning round-trip before generation.
    """
    requested = str(requested_mode or "auto").strip().lower()
    if requested not in {"auto", "standard", "deep"}:
        requested = "auto"
    if requested in {"standard", "deep"}:
        return ReasoningDecision(requested, requested, 0, "explicit override")

    raw = str(prompt or "").strip()
    text = _clean(raw)
    words = re.findall(r"[a-z0-9_'-]+", text)
    word_count = len(words)

    if not text:
        return ReasoningDecision("auto", "direct", 0, "empty prompt")
    if word_count <= 10 and any(re.fullmatch(pattern, text) for pattern in _SIMPLE_PATTERNS):
        return ReasoningDecision("auto", "direct", 0, "simple conversational prompt")

    score = 0
    reasons: list[str] = []

    # Length and structure matter, but are deliberately weak signals by themselves.
    if word_count >= 45:
        score += 1; reasons.append("longer prompt")
    if word_count >= 110:
        score += 1; reasons.append("high detail")
    if raw.count("\n") >= 3 or len(re.findall(r"(?:^|\n)\s*(?:[-*]|\d+[.)])\s+", raw)) >= 2:
        score += 1; reasons.append("multi-part structure")
    if text.count("?") >= 2:
        score += 1; reasons.append("multiple questions")
    if "```" in raw or re.search(r"\b(traceback|exception|stack trace|function|class|async|thread|mutex|sql|regex)\b", text):
        score += 2; reasons.append("code/technical reasoning")

    deep_hits = sum(1 for term in _DEEP_TERMS if term in text)
    if deep_hits:
        add = min(4, deep_hits * 2)
        score += add; reasons.append("deep-reasoning cues")

    standard_hits = sum(1 for term in _STANDARD_TERMS if re.search(rf"\b{re.escape(term)}\b", text))
    if standard_hits:
        score += min(2, standard_hits); reasons.append("analysis cue")

    # Explicit multiple constraints/options are a strong signal for deeper search.
    if re.search(r"\b(three|3|multiple|several)\s+(options|approaches|designs|solutions|constraints)\b", text):
        score += 2; reasons.append("multiple alternatives")
    if re.search(r"\b(check|verify|test)\b.*\b(assumptions|edge cases|failure|correctness)\b", text):
        score += 2; reasons.append("verification requested")

    if score >= 5:
        effective = "deep"
    elif score >= 1:
        effective = "standard"
    else:
        effective = "direct"

    return ReasoningDecision("auto", effective, score, ", ".join(reasons[:3]) or "simple prompt")


def display_label(requested: str, effective: str) -> str:
    requested = str(requested or "auto").lower()
    effective = str(effective or requested or "direct").lower()
    if requested == "auto":
        return f"AUTO → {effective.upper()}"
    if effective == "deep":
        return "DEEP REASONING"
    if effective == "standard":
        return "STANDARD THINK"
    return effective.upper()
