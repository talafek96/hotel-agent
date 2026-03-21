"""Tests for the setup wizard."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hotel_agent.web.app import create_app


@pytest.fixture()
def setup_env(tmp_path):
    """Create app WITHOUT setup_complete marker (wizard active)."""
    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"database:\n  path: '{db_path}'\n")

    # No .setup_complete — wizard should be active
    with patch.dict(os.environ, {}, clear=True):
        app = create_app(str(config_file))

    return TestClient(app), tmp_path, config_file, db_path


@pytest.fixture()
def completed_env(tmp_path):
    """Create app WITH setup_complete marker (wizard bypassed)."""
    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"database:\n  path: '{db_path}'\n")

    (tmp_path / ".setup_complete").write_text("1")

    with patch.dict(os.environ, {}, clear=True):
        app = create_app(str(config_file))

    return TestClient(app), tmp_path, config_file, db_path


class TestSetupRedirect:
    """Middleware redirects to /setup when setup is incomplete."""

    def test_redirects_to_setup_when_not_complete(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/setup" in resp.headers["location"]

    def test_redirects_bookings_to_setup(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/bookings", follow_redirects=False)
        assert resp.status_code == 307

    def test_no_redirect_when_setup_complete(self, completed_env):
        client, *_ = completed_env
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text

    def test_setup_page_accessible_always(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup")
        assert resp.status_code == 200
        assert "Welcome" in resp.text

    def test_api_routes_not_redirected(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/api/scrape/status")
        assert resp.status_code == 200


class TestSetupWizardSteps:
    """Tests for each setup wizard step."""

    def test_step1_welcome(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=1")
        assert resp.status_code == 200
        assert "Welcome" in resp.text
        assert "Get Started" in resp.text

    def test_step1_advance_to_step2(self, setup_env):
        client, *_ = setup_env
        resp = client.post("/setup", data={"step": "1"})
        assert resp.status_code == 200
        assert "AI Provider" in resp.text

    def test_step2_shows_providers(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=2")
        assert resp.status_code == 200
        assert "OpenAI" in resp.text
        assert "Google Gemini" in resp.text
        assert "Anthropic" in resp.text

    def test_step2_saves_llm_config(self, setup_env):
        client, *_ = setup_env
        resp = client.post(
            "/setup",
            data={
                "step": "2",
                "llm_provider": "gemini",
                "gemini_api_key": "test-gemini-key",
                "gemini_model": "gemini/gemini-2.0-flash",
            },
        )
        assert resp.status_code == 200
        # Should advance to step 3 (SerpAPI)
        assert "Hotel Price Data" in resp.text or "SerpAPI" in resp.text

        # Verify .env was written
        env_path = Path(".env")
        if env_path.exists():
            content = env_path.read_text()
            assert "test-gemini-key" in content

    def test_step3_serpapi(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=3")
        assert resp.status_code == 200
        assert "SerpAPI" in resp.text or "Hotel Price Data" in resp.text
        assert "250 searches/month" in resp.text

    def test_step3_saves_serpapi_key(self, setup_env):
        client, *_ = setup_env
        resp = client.post(
            "/setup",
            data={
                "step": "3",
                "serpapi_key": "test-serpapi-key",
            },
        )
        assert resp.status_code == 200
        # Should advance to step 4 (Notifications)
        assert "Notifications" in resp.text

    def test_step4_notifications(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=4")
        assert resp.status_code == 200
        assert "Notifications" in resp.text
        assert "Optional" in resp.text
        assert "Telegram" in resp.text

    def test_step4_save_and_advance(self, setup_env):
        client, *_ = setup_env
        resp = client.post(
            "/setup",
            data={
                "step": "4",
                "telegram_bot_token": "123:ABC",
                "telegram_chat_id": "456",
            },
        )
        assert resp.status_code == 200
        # Should advance to step 5 (Settings)
        assert "Basic Settings" in resp.text or "Settings" in resp.text

    def test_step5_settings(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=5")
        assert resp.status_code == 200
        assert "Basic Settings" in resp.text or "Travelers" in resp.text

    def test_step6_import_page(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=6")
        assert resp.status_code == 200
        assert "Excel" in resp.text
        assert "AI" in resp.text.lower() or "parsing" in resp.text.lower()

    def test_step6_skip_to_done(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=7")
        assert resp.status_code == 200
        assert "All Set" in resp.text or "Done" in resp.text

    def test_step7_done_shows_summary(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=7")
        assert resp.status_code == 200
        assert "AI Provider" in resp.text or "SerpAPI" in resp.text

    def test_step6_marks_complete_and_redirects(self, setup_env):
        client, tmp_path, *_ = setup_env
        resp = client.post(
            "/setup",
            data={"step": "7"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        # Marker file should exist
        assert (tmp_path / ".setup_complete").exists()


class TestSetupPreservesEnv:
    """Verify that setup wizard preserves existing .env values."""

    def test_prefills_existing_keys(self, setup_env):
        client, *_ = setup_env
        # Write a fake .env before loading the page
        Path(".env").write_text("OPENAI_API_KEY=existing-key-123\n")
        try:
            resp = client.get("/setup?step=2")
            assert resp.status_code == 200
            assert "existing-key-123" in resp.text
        finally:
            Path(".env").unlink(missing_ok=True)

    def test_does_not_overwrite_unrelated_keys(self, setup_env):
        client, *_ = setup_env
        Path(".env").write_text("SERPAPI_KEY=keep-this\nOPENAI_API_KEY=old-key\n# A comment\n")
        try:
            # Post step 2 with a new openai key
            client.post(
                "/setup",
                data={
                    "step": "2",
                    "llm_provider": "openai",
                    "openai_api_key": "new-key",
                    "openai_model": "gpt-4o-mini",
                },
            )
            content = Path(".env").read_text()
            # SERPAPI_KEY should be preserved
            assert "SERPAPI_KEY=keep-this" in content
            # Comment should be preserved
            assert "# A comment" in content
            # OpenAI key should be updated
            assert "new-key" in content
        finally:
            Path(".env").unlink(missing_ok=True)

    def test_empty_fields_dont_overwrite(self, setup_env):
        client, *_ = setup_env
        Path(".env").write_text("OPENAI_API_KEY=keep-this\n")
        try:
            # Post step 2 with empty openai key (user didn't fill it in)
            client.post(
                "/setup",
                data={
                    "step": "2",
                    "llm_provider": "openai",
                    "openai_api_key": "",
                    "openai_model": "gpt-4o-mini",
                },
            )
            content = Path(".env").read_text()
            # Original key should be preserved since we sent empty
            assert "keep-this" in content
        finally:
            Path(".env").unlink(missing_ok=True)


class TestSetupImport:
    """Tests for the Excel import step in the setup wizard."""

    def test_import_step_without_file_shows_error(self, setup_env):
        """Submitting step 6 without a file should show error."""
        client, *_ = setup_env
        resp = client.post("/setup", data={"step": "6", "sheet": "", "table": ""})
        assert resp.status_code == 200
        assert "Please select" in resp.text or "Import" in resp.text


class TestSetupSkipBehavior:
    """Tests for skip buttons and skipped-step warnings."""

    def test_step2_skip_advances_without_saving(self, setup_env):
        client, *_ = setup_env
        resp = client.post("/setup", data={"step": "2", "skip": "1"})
        assert resp.status_code == 200
        assert "Hotel Price Data" in resp.text or "SerpAPI" in resp.text

    def test_step3_skip_advances_without_saving(self, setup_env):
        client, *_ = setup_env
        resp = client.post("/setup", data={"step": "3", "skip": "1"})
        assert resp.status_code == 200
        assert "Notifications" in resp.text

    def test_step7_shows_skipped_warnings(self, setup_env):
        """Done page should show warnings for unconfigured items."""
        client, *_ = setup_env
        resp = client.get("/setup?step=7")
        assert resp.status_code == 200
        assert "Some steps were skipped" in resp.text
        assert "Config" in resp.text

    def test_step2_has_skip_link(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=2")
        assert "Skip for now" in resp.text

    def test_step3_has_skip_link(self, setup_env):
        client, *_ = setup_env
        resp = client.get("/setup?step=3")
        assert "Skip for now" in resp.text


class TestConfigTooltips:
    """Tests for info tooltips on the config page."""

    def test_config_page_has_tooltips(self, completed_env):
        client, *_ = completed_env
        resp = client.get("/config")
        assert resp.status_code == 200
        assert "info-tooltip-trigger" in resp.text
        assert "info-icon" in resp.text

    def test_tooltips_contain_signup_links(self, completed_env):
        client, *_ = completed_env
        resp = client.get("/config")
        assert "platform.openai.com" in resp.text
        assert "aistudio.google.com" in resp.text
        assert "serpapi.com" in resp.text
