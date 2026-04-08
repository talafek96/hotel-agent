"""Tests for hotel_agent.llm.excel_parser — model conversion logic."""

from hotel_agent.llm.excel_parser import excel_to_models
from hotel_agent.models import TravelerComposition


class TestExcelToModels:
    """Tests for converting LLM-parsed dicts to Hotel + Booking pairs."""

    def test_basic_conversion(self):
        parsed = [
            {
                "name": "Namba Oriental Hotel",
                "city": "Osaka",
                "country": "Japan",
                "check_in": "2026-08-31",
                "check_out": "2026-09-03",
                "price": 135833,
                "currency": "JPY",
                "platform": "Agoda",
                "booking_reference": "628875015",
            }
        ]
        pairs = excel_to_models(parsed)
        assert len(pairs) == 1
        hotel, booking = pairs[0]
        assert hotel.name == "Namba Oriental Hotel"
        assert booking.booked_price == 135833
        assert booking.currency == "JPY"

    def test_null_currency_defaults_to_usd(self):
        """When LLM returns null for currency, it should default to USD."""
        parsed = [
            {
                "name": "Atha Resort Sigiriya",
                "city": "Sigiriya",
                "check_in": "2026-08-24",
                "check_out": "2026-08-26",
                "price": 716,
                "currency": None,
            }
        ]
        pairs = excel_to_models(parsed)
        _, booking = pairs[0]
        assert booking.currency == "USD"

    def test_missing_currency_key_defaults_to_usd(self):
        """When LLM omits the currency key entirely, it should default to USD."""
        parsed = [
            {
                "name": "Some Hotel",
                "check_in": "2026-01-01",
                "check_out": "2026-01-02",
                "price": 100,
            }
        ]
        pairs = excel_to_models(parsed)
        _, booking = pairs[0]
        assert booking.currency == "USD"

    def test_empty_string_currency_defaults_to_usd(self):
        """Empty string currency should also default to USD."""
        parsed = [
            {
                "name": "Some Hotel",
                "price": 100,
                "currency": "",
            }
        ]
        pairs = excel_to_models(parsed)
        _, booking = pairs[0]
        assert booking.currency == "USD"

    def test_currency_symbol_normalized_to_iso(self):
        """LLM returning a symbol like ¥ should be normalised to JPY."""
        parsed = [
            {"name": "Hotel A", "price": 50000, "currency": "¥"},
            {"name": "Hotel B", "price": 100, "currency": "₪"},
            {"name": "Hotel C", "price": 200, "currency": "€"},
            {"name": "Hotel D", "price": 300, "currency": "$"},
        ]
        pairs = excel_to_models(parsed)
        assert pairs[0][1].currency == "JPY"
        assert pairs[1][1].currency == "ILS"
        assert pairs[2][1].currency == "EUR"
        assert pairs[3][1].currency == "USD"

    def test_currency_word_normalized_to_iso(self):
        """LLM returning a word like 'euro' should be normalised to EUR."""
        parsed = [
            {"name": "Hotel A", "price": 100, "currency": "euro"},
            {"name": "Hotel B", "price": 100, "currency": "yen"},
            {"name": "Hotel C", "price": 100, "currency": "shekel"},
        ]
        pairs = excel_to_models(parsed)
        assert pairs[0][1].currency == "EUR"
        assert pairs[1][1].currency == "JPY"
        assert pairs[2][1].currency == "ILS"

    def test_valid_iso_code_passes_through(self):
        """Already-valid ISO codes should pass through unchanged."""
        parsed = [
            {"name": "Hotel A", "price": 100, "currency": "JPY"},
            {"name": "Hotel B", "price": 100, "currency": "usd"},
            {"name": "Hotel C", "price": 100, "currency": "Eur"},
        ]
        pairs = excel_to_models(parsed)
        assert pairs[0][1].currency == "JPY"
        assert pairs[1][1].currency == "USD"
        assert pairs[2][1].currency == "EUR"

    def test_null_price_defaults_to_zero(self):
        """Null price should default to 0."""
        parsed = [{"name": "Hotel", "price": None, "currency": "USD"}]
        pairs = excel_to_models(parsed)
        _, booking = pairs[0]
        assert booking.booked_price == 0.0

    def test_multi_currency_bookings(self):
        """Bookings from different countries should preserve their currencies."""
        parsed = [
            {"name": "Sri Lanka Hotel", "price": 726, "currency": "USD"},
            {"name": "Japan Hotel", "price": 135833, "currency": "JPY"},
            {"name": "Vienna Hotel", "price": 4219, "currency": "EUR"},
        ]
        pairs = excel_to_models(parsed)
        assert len(pairs) == 3
        assert pairs[0][1].currency == "USD"
        assert pairs[1][1].currency == "JPY"
        assert pairs[2][1].currency == "EUR"

    def test_travelers_applied_to_all_bookings(self):
        """Default travelers should be applied to every booking."""
        parsed = [
            {"name": "Hotel A", "price": 100, "currency": "USD"},
            {"name": "Hotel B", "price": 200, "currency": "EUR"},
        ]
        travelers = TravelerComposition(adults=2, children_ages=[4, 7])
        pairs = excel_to_models(parsed, travelers)
        for _, booking in pairs:
            assert booking.travelers.adults == 2
            assert booking.travelers.children_ages == [4, 7]
