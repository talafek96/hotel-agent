"""LLM-based hotel name matching verification."""

from __future__ import annotations

import logging

from ..config import AppConfig
from .client import call_llm_json

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a hotel identity verifier. Given a hotel we are looking for and a "
    "candidate hotel from search results, determine if they are the SAME hotel. "
    "Hotels may have slightly different names across platforms (e.g. abbreviations, "
    "missing suffixes, different transliterations of Japanese names). "
    'Respond with JSON: {"match": true/false, "reason": "brief explanation"}'
)


def verify_hotel_match(
    config: AppConfig,
    our_name: str,
    our_city: str,
    candidate_name: str,
    candidate_address: str = "",
) -> bool:
    """Use LLM to verify that a SerpAPI result matches our hotel.

    Returns True if the LLM judges them to be the same hotel.
    """
    prompt = (
        f"Hotel we are looking for:\n"
        f"  Name: {our_name}\n"
        f"  City: {our_city}\n"
        f"\n"
        f"Candidate from search results:\n"
        f"  Name: {candidate_name}\n"
    )
    if candidate_address:
        prompt += f"  Address: {candidate_address}\n"

    prompt += "\nAre these the same hotel?"

    try:
        result = call_llm_json(config, prompt, system_prompt=_SYSTEM_PROMPT)
        is_match = bool(result.get("match", False))
        reason = result.get("reason", "")
        log.info(
            "Hotel match check: '%s' vs '%s' -> %s (%s)",
            our_name,
            candidate_name,
            is_match,
            reason,
        )
        return is_match
    except Exception:
        log.exception("LLM hotel match verification failed, falling back to name overlap")
        return _fallback_match(our_name, candidate_name)


def _fallback_match(our_name: str, candidate_name: str) -> bool:
    """Simple word-overlap fallback if LLM is unavailable."""
    ours = set(our_name.lower().split())
    theirs = set(candidate_name.lower().split())
    if not ours:
        return False
    overlap = ours & theirs
    return len(overlap) >= len(ours) * 0.5
