"""Shared test fixtures."""

from unittest.mock import patch

import pytest

from hotel_agent.config import AppConfig
from hotel_agent.db import Database
from hotel_agent.models import Booking, Hotel, PriceSnapshot, TravelerComposition


@pytest.fixture(autouse=True)
def _no_dotenv():
    """Prevent load_dotenv from reading real .env files during tests.

    Without this, secrets from the developer's .env leak into test output
    on assertion failures.
    """
    with patch("hotel_agent.config.load_dotenv"):
        yield


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


@pytest.fixture
def config(tmp_path):
    """Create a test config with a temp database."""
    cfg = AppConfig(_env_file=None)
    cfg.db_path = str(tmp_path / "test.db")
    cfg.travelers = TravelerComposition(adults=2, children_ages=[4, 7])
    return cfg


@pytest.fixture
def sample_hotel():
    """Create a sample hotel."""
    return Hotel(
        name="Namba Oriental Hotel",
        city="Osaka",
        country="Japan",
        address="2-10 Nanbasennichimae, Chuo Ward",
        url="https://www.booking.com/hotel/jp/namba-oriental.html",
        platform="Booking.com",
    )


@pytest.fixture
def sample_booking():
    """Create a sample booking."""
    from datetime import date

    return Booking(
        check_in=date(2026, 8, 31),
        check_out=date(2026, 9, 3),
        travelers=TravelerComposition(adults=2, children_ages=[4, 7]),
        room_type="Standard Double",
        booked_price=135833,
        currency="JPY",
        is_cancellable=True,
        cancellation_deadline=date(2026, 8, 29),
        breakfast_included=False,
        platform="Agoda",
        booking_reference="628875015",
    )


@pytest.fixture
def sample_snapshot():
    """Create a sample price snapshot."""
    from datetime import date

    return PriceSnapshot(
        check_in=date(2026, 8, 31),
        check_out=date(2026, 9, 3),
        travelers=TravelerComposition(adults=2),
        room_type="Standard Double",
        platform="Booking.com",
        price=120000,
        currency="JPY",
        is_cancellable=True,
        breakfast_included=False,
    )
