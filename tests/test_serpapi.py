"""Tests for hotel_agent.api.serpapi_client module."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from hotel_agent.api.serpapi_client import (
    SerpAPIError,
    SerpAPIResult,
    _build_query,
    _extract_number,
    _parse_first_property,
    _parse_property_detail,
    search_hotel_prices,
)
from hotel_agent.models import Hotel, TravelerComposition

# ── Helpers ────────────────────────────────────────────────


def _make_hotel(**kwargs) -> Hotel:
    defaults = {
        "id": 1,
        "name": "Hotel Gracery Shinjuku",
        "city": "Tokyo",
        "country": "Japan",
    }
    defaults.update(kwargs)
    return Hotel(**defaults)


# ── _extract_number ────────────────────────────────────────


class TestExtractNumber:
    def test_yen_format(self):
        assert _extract_number("¥12,345") == 12345.0

    def test_dollar_format(self):
        assert _extract_number("$1,234.56") == 1234.56

    def test_plain_number(self):
        assert _extract_number("5000") == 5000.0

    def test_no_number(self):
        assert _extract_number("no price") is None

    def test_empty_string(self):
        assert _extract_number("") is None


# ── _build_query ────────────────────────────────────────────


class TestBuildQuery:
    def test_full_query(self):
        hotel = _make_hotel(name="Hotel Gracery", city="Tokyo", country="Japan")
        assert _build_query(hotel) == "Hotel Gracery Tokyo Japan"

    def test_name_only(self):
        hotel = _make_hotel(name="Hotel Gracery", city="", country="")
        assert _build_query(hotel) == "Hotel Gracery"

    def test_name_and_city(self):
        hotel = _make_hotel(name="Hotel Gracery", city="Tokyo", country="")
        assert _build_query(hotel) == "Hotel Gracery Tokyo"


# ── _parse_first_property ──────────────────────────────────


class TestParseFirstProperty:
    """Tests for the new first-result parsing logic."""

    def test_takes_first_property(self):
        """Should take the first property regardless of name."""
        data = {
            "properties": [
                {
                    "name": "Some Hotel Name",
                    "property_token": "tok123",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 30000},
                        },
                    ],
                },
                {
                    "name": "Hotel Gracery Shinjuku",
                    "property_token": "tok456",
                    "prices": [
                        {
                            "source": "Agoda",
                            "total_rate": {"extracted_lowest": 28000},
                        },
                    ],
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert isinstance(result, SerpAPIResult)
        assert len(result.snapshots) == 1
        assert result.snapshots[0].price == 30000.0
        assert result.matched_name == "Some Hotel Name"
        assert result.property_token == "tok123"

    def test_extracts_property_token(self):
        data = {
            "properties": [
                {
                    "name": "Hotel Gracery Shinjuku",
                    "property_token": "abc_xyz_123",
                    "hotel_address": "1-2-3 Kabukicho, Shinjuku",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 30000},
                        },
                    ],
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert result.property_token == "abc_xyz_123"
        assert result.matched_name == "Hotel Gracery Shinjuku"
        assert result.matched_address == "1-2-3 Kabukicho, Shinjuku"
        assert result.used_cached_token is False

    def test_multiple_prices_from_first_property(self):
        data = {
            "properties": [
                {
                    "name": "Hotel Gracery Shinjuku",
                    "property_token": "tok",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 30000},
                        },
                        {
                            "source": "Agoda",
                            "total_rate": {"extracted_lowest": 28000},
                        },
                    ],
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert len(result.snapshots) == 2
        assert result.snapshots[0].platform == "booking.com"
        assert result.snapshots[1].platform == "agoda"

    def test_top_level_prices_fallback(self):
        """When no properties, fall back to top-level prices."""
        data = {
            "prices": [
                {
                    "source": "Expedia",
                    "total_rate": {"extracted_lowest": 50000},
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert len(result.snapshots) == 1
        assert result.snapshots[0].price == 50000.0
        assert result.property_token == ""

    def test_direct_property_detail_extracts_token_and_name(self):
        """SerpAPI direct property detail: top-level name/token/prices."""
        data = {
            "name": "Dormy inn Abashiri",
            "address": "3 Chome, Abashiri, Hokkaido",
            "property_token": "ChkI9eyA24WlxLVK",
            "prices": [
                {
                    "source": "Booking.com",
                    "total_rate": {"extracted_lowest": 46000},
                },
                {
                    "source": "Agoda",
                    "total_rate": {"extracted_lowest": 43000},
                },
            ],
        }
        hotel = _make_hotel(name="Dormy Inn Abashiri", city="Abashiri")
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 9, 10),
            date(2025, 9, 11),
            TravelerComposition(),
            "JPY",
        )
        assert result.matched_name == "Dormy inn Abashiri"
        assert result.matched_address == "3 Chome, Abashiri, Hokkaido"
        assert result.property_token == "ChkI9eyA24WlxLVK"
        assert len(result.snapshots) == 2

    def test_direct_property_detail_no_prices(self):
        """SerpAPI direct property detail with 0 prices (e.g. children)."""
        data = {
            "name": "Dormy inn Abashiri",
            "property_token": "ChkI9eyA24WlxLVK",
        }
        hotel = _make_hotel(name="Dormy Inn Abashiri")
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 9, 10),
            date(2025, 9, 11),
            TravelerComposition(),
            "JPY",
        )
        assert result.matched_name == "Dormy inn Abashiri"
        assert result.property_token == "ChkI9eyA24WlxLVK"
        assert result.snapshots == []

    def test_rate_per_night_multiplied(self):
        """When only rate_per_night is given, multiply by nights."""
        data = {
            "properties": [
                {
                    "name": "Hotel Gracery Shinjuku",
                    "prices": [
                        {
                            "source": "Hotels.com",
                            "rate_per_night": {"extracted_lowest": 10000},
                        },
                    ],
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert len(result.snapshots) == 1
        assert result.snapshots[0].price == 20000.0  # 2 nights * 10000

    def test_empty_data(self):
        result = _parse_first_property(
            {},
            _make_hotel(),
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert result.snapshots == []

    def test_rate_per_night_summary_fallback(self):
        """Property with rate_per_night summary but no per-OTA prices."""
        data = {
            "properties": [
                {
                    "name": "Hotel Gracery Shinjuku",
                    "rate_per_night": {"extracted_lowest": 12000},
                    "prices": [],
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert len(result.snapshots) == 1
        assert result.snapshots[0].platform == "google_hotels"
        assert result.snapshots[0].price == 12000.0

    def test_features_cancellation_breakfast(self):
        data = {
            "properties": [
                {
                    "name": "Hotel Gracery Shinjuku",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 30000},
                            "features": [
                                "Free cancellation",
                                "Breakfast included",
                            ],
                        },
                    ],
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert len(result.snapshots) == 1
        assert result.snapshots[0].is_cancellable is True
        assert result.snapshots[0].breakfast_included is True

    def test_free_cancellation_boolean(self):
        """Top-level prices with boolean free_cancellation field."""
        data = {
            "prices": [
                {
                    "source": "Agoda",
                    "total_rate": {"extracted_lowest": 64000},
                    "free_cancellation": True,
                    "free_cancellation_until_date": "Aug 28",
                },
            ],
        }
        hotel = _make_hotel()
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert len(result.snapshots) == 1
        assert result.snapshots[0].is_cancellable is True
        assert result.snapshots[0].cancellation_deadline == date(2025, 8, 28)

    def test_snapshot_fields_populated(self):
        data = {
            "properties": [
                {
                    "name": "Hotel Gracery Shinjuku",
                    "prices": [
                        {
                            "source": "Trip.com",
                            "total_rate": {"extracted_lowest": 25000},
                            "room_type": "Deluxe Twin",
                        },
                    ],
                },
            ],
        }
        hotel = _make_hotel()
        travelers = TravelerComposition(adults=2, children_ages=[4])
        result = _parse_first_property(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            travelers,
            "JPY",
        )
        snap = result.snapshots[0]
        assert snap.hotel_id == 1
        assert snap.check_in == date(2025, 8, 1)
        assert snap.check_out == date(2025, 8, 3)
        assert snap.travelers.adults == 2
        assert snap.travelers.children_ages == [4]
        assert snap.room_type == "Deluxe Twin"
        assert snap.currency == "JPY"
        assert snap.scraped_at is not None


# ── _parse_property_detail ─────────────────────────────────


class TestParsePropertyDetail:
    """Tests for property_token detail view parsing."""

    def test_parses_top_level_prices(self):
        data = {
            "prices": [
                {
                    "source": "Booking.com",
                    "total_rate": {"extracted_lowest": 45000},
                    "free_cancellation": True,
                },
                {
                    "source": "Agoda",
                    "total_rate": {"extracted_lowest": 42000},
                },
            ],
        }
        hotel = _make_hotel(serpapi_property_token="cached_tok")
        result = _parse_property_detail(
            data,
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert result.used_cached_token is True
        assert result.property_token == "cached_tok"
        assert len(result.snapshots) == 2

    def test_empty_prices(self):
        hotel = _make_hotel(serpapi_property_token="cached_tok")
        result = _parse_property_detail(
            {"prices": []},
            hotel,
            date(2025, 8, 1),
            date(2025, 8, 3),
            TravelerComposition(),
            "JPY",
        )
        assert result.snapshots == []
        assert result.used_cached_token is True


# ── search_hotel_prices ────────────────────────────────────


class TestSearchHotelPrices:
    def test_missing_api_key_raises(self):
        with pytest.raises(SerpAPIError, match="not configured"):
            search_hotel_prices(
                api_key="",
                hotel=_make_hotel(),
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
            )

    def test_successful_request_returns_result(self):
        mock_json = {
            "properties": [
                {
                    "name": "Hotel Gracery Shinjuku",
                    "property_token": "tok",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 30000},
                        },
                    ],
                },
            ],
        }

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return mock_json

        with patch("hotel_agent.api.serpapi_client.requests.get", return_value=MockResponse()):
            result = search_hotel_prices(
                api_key="test-key",
                hotel=_make_hotel(),
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
            )
        assert isinstance(result, SerpAPIResult)
        assert len(result.snapshots) == 1
        assert result.snapshots[0].price == 30000.0
        assert result.property_token == "tok"

    def test_uses_property_token_when_cached(self):
        """When hotel has a property_token, should include both q and property_token."""
        mock_json = {
            "prices": [
                {
                    "source": "Booking.com",
                    "total_rate": {"extracted_lowest": 30000},
                },
            ],
        }

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return mock_json

        hotel = _make_hotel(serpapi_property_token="my_token")
        with patch(
            "hotel_agent.api.serpapi_client.requests.get", return_value=MockResponse()
        ) as mock_get:
            result = search_hotel_prices(
                api_key="test-key",
                hotel=hotel,
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
            )
            url = mock_get.call_args[0][0]
            assert "property_token=my_token" in url
            assert "q=" in url
        assert result.used_cached_token is True
        assert len(result.snapshots) == 1

    def test_request_includes_children(self):
        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"properties": []}

        with patch(
            "hotel_agent.api.serpapi_client.requests.get", return_value=MockResponse()
        ) as mock_get:
            search_hotel_prices(
                api_key="test-key",
                hotel=_make_hotel(),
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
                travelers=TravelerComposition(adults=2, children_ages=[4, 7]),
            )
            # First call should include children params
            first_url = mock_get.call_args_list[0][0][0]
            assert "children=2" in first_url
            assert "children_ages=4%2C7" in first_url

    def test_network_error_raises(self):
        import requests as req

        with (
            patch(
                "hotel_agent.api.serpapi_client.requests.get",
                side_effect=req.ConnectionError("timeout"),
            ),
            pytest.raises(SerpAPIError, match="request failed"),
        ):
            search_hotel_prices(
                api_key="test-key",
                hotel=_make_hotel(),
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
            )

    def test_retries_children_as_adults(self):
        """When children params yield 0 prices, retry with children as adults."""
        empty_response = {"properties": []}
        prices_response = {
            "properties": [
                {
                    "name": "Hotel X",
                    "property_token": "tok",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 46000},
                        },
                    ],
                },
            ],
        }

        class MockResponse:
            status_code = 200

            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        def mock_get(url, **kwargs):
            # First call has children= param → empty; second is 4 adults → prices
            if "children=" in url:
                return MockResponse(empty_response)
            return MockResponse(prices_response)

        travelers = TravelerComposition(adults=2, children_ages=[8, 13])
        with patch(
            "hotel_agent.api.serpapi_client.requests.get", side_effect=mock_get
        ) as mock_get_patch:
            result = search_hotel_prices(
                api_key="test-key",
                hotel=_make_hotel(name="Dormy Inn Abashiri"),
                check_in=date(2025, 9, 10),
                check_out=date(2025, 9, 11),
                travelers=travelers,
            )
        assert mock_get_patch.call_count == 2
        retry_url = mock_get_patch.call_args_list[1][0][0]
        assert "adults=4" in retry_url
        assert "children=" not in retry_url
        assert len(result.snapshots) == 1
        assert result.snapshots[0].price == 46000.0
        assert result.snapshots[0].travelers.children_ages == [8, 13]

    def test_retries_simplified_query(self):
        """When full query returns no results, retry with hotel name only."""
        no_results_response = {
            "error": "Google Hotels hasn't returned any results for this search."
        }
        prices_response = {
            "properties": [
                {
                    "name": "Kussharo Prince Hotel",
                    "property_token": "tok",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 18000},
                        },
                    ],
                },
            ],
        }

        class MockResponse:
            status_code = 200

            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            # Full query (with city) returns "no results"; simple query works
            if "Kussharo+Onsen" in url or "Kussharo%20Onsen" in url:
                return MockResponse(no_results_response)
            return MockResponse(prices_response)

        hotel = _make_hotel(name="Kussharo Prince Hotel", city="Kussharo Onsen")
        with patch("hotel_agent.api.serpapi_client.requests.get", side_effect=mock_get):
            result = search_hotel_prices(
                api_key="test-key",
                hotel=hotel,
                check_in=date(2025, 9, 10),
                check_out=date(2025, 9, 11),
            )
        assert len(result.snapshots) == 1
        assert result.snapshots[0].price == 18000.0

    def test_no_results_error_returns_empty(self):
        """SerpAPI 'no results' error should return empty result, not raise."""

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"error": "Google Hotels hasn't returned any results for this search."}

        # Hotel with no city/country so simplified query = full query (no retry)
        hotel = _make_hotel(city="", country="")
        with patch("hotel_agent.api.serpapi_client.requests.get", return_value=MockResponse()):
            result = search_hotel_prices(
                api_key="test-key",
                hotel=hotel,
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
            )
        assert result.snapshots == []

    def test_non_retryable_error_still_raises(self):
        """Non-'no results' errors like 'Invalid API key' should still raise."""

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"error": "Invalid API key"}

        with (
            patch("hotel_agent.api.serpapi_client.requests.get", return_value=MockResponse()),
            pytest.raises(SerpAPIError, match="Invalid API key"),
        ):
            search_hotel_prices(
                api_key="bad-key",
                hotel=_make_hotel(),
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
            )

    def test_no_retry_when_prices_found_with_children(self):
        """When children params yield prices, no retry needed."""
        data = {
            "properties": [
                {
                    "name": "Hotel X",
                    "property_token": "tok",
                    "prices": [
                        {
                            "source": "Booking.com",
                            "total_rate": {"extracted_lowest": 30000},
                        },
                    ],
                },
            ],
        }

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return data

        travelers = TravelerComposition(adults=2, children_ages=[5])
        with patch(
            "hotel_agent.api.serpapi_client.requests.get", return_value=MockResponse()
        ) as mock_get:
            result = search_hotel_prices(
                api_key="test-key",
                hotel=_make_hotel(),
                check_in=date(2025, 8, 1),
                check_out=date(2025, 8, 3),
                travelers=travelers,
            )
        assert mock_get.call_count == 1
        assert len(result.snapshots) == 1
