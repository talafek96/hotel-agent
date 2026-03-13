"""Tests for hotel_agent.llm.hotel_matcher module."""

from __future__ import annotations

from unittest.mock import patch

from hotel_agent.config import AppConfig
from hotel_agent.llm.hotel_matcher import _fallback_match, verify_hotel_match


class TestFallbackMatch:
    """Tests for the word-overlap fallback matcher."""

    def test_exact_match(self):
        assert _fallback_match("Hotel Gracery Shinjuku", "Hotel Gracery Shinjuku")

    def test_partial_overlap(self):
        assert _fallback_match("Dormy Inn Abashiri", "Dormy Inn Abashiri Natural Hot Spring")

    def test_no_overlap(self):
        assert not _fallback_match("Hilton Tokyo", "Marriott Osaka")

    def test_empty_our_name(self):
        assert not _fallback_match("", "Some Hotel")

    def test_case_insensitive(self):
        assert _fallback_match("HOTEL AMANEK", "Hotel Amanek Asahikawa")

    def test_single_word(self):
        assert _fallback_match("Hilton", "Hilton Tokyo Bay")


class TestVerifyHotelMatch:
    """Tests for the LLM-based verify_hotel_match function."""

    def test_llm_confirms_match(self):
        config = AppConfig()
        with patch(
            "hotel_agent.llm.hotel_matcher.call_llm_json",
            return_value={"match": True, "reason": "Same hotel"},
        ):
            assert verify_hotel_match(
                config,
                our_name="Dormy Inn Abashiri",
                our_city="Abashiri",
                candidate_name="Dormy Inn Abashiri Natural Hot Spring",
                candidate_address="1-2-3 Abashiri",
            )

    def test_llm_rejects_match(self):
        config = AppConfig()
        with patch(
            "hotel_agent.llm.hotel_matcher.call_llm_json",
            return_value={"match": False, "reason": "Different hotels"},
        ):
            assert not verify_hotel_match(
                config,
                our_name="Dormy Inn Abashiri",
                our_city="Abashiri",
                candidate_name="Hilton Tokyo",
            )

    def test_llm_failure_falls_back(self):
        """If LLM call fails, should fall back to word overlap."""
        config = AppConfig()
        with patch(
            "hotel_agent.llm.hotel_matcher.call_llm_json",
            side_effect=Exception("API error"),
        ):
            # Should fall back and match on word overlap
            assert verify_hotel_match(
                config,
                our_name="Dormy Inn Abashiri",
                our_city="Abashiri",
                candidate_name="Dormy Inn Abashiri Natural Hot Spring",
            )

    def test_llm_failure_falls_back_no_match(self):
        """If LLM fails and fallback doesn't match, returns False."""
        config = AppConfig()
        with patch(
            "hotel_agent.llm.hotel_matcher.call_llm_json",
            side_effect=Exception("API error"),
        ):
            assert not verify_hotel_match(
                config,
                our_name="Dormy Inn Abashiri",
                our_city="Abashiri",
                candidate_name="Hilton Tokyo Bay",
            )
