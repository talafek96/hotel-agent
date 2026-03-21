.PHONY: install install-gui lint format typecheck test check build dist dist-all dist-local clean

# ── Development ────────────────────────────────────────

install:
	uv sync --group dev

install-gui:
	uv sync --group dev --extra gui

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

format-check:
	uv run ruff format --check src/ tests/

typecheck:
	uv run mypy src/hotel_agent/

test:
	uv run pytest

check: lint format-check typecheck test

# ── Build & Distribution ──────────────────────────────

DIST_NAME := HotelPriceTracker
DIST_DIR  := dist/$(DIST_NAME)
PORT      := 8470

# Detect platform
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    PLATFORM := macos
    UV_ASSET := uv-aarch64-apple-darwin.tar.gz
    ICON     := assets/icon.icns
else ifeq ($(OS),Windows_NT)
    PLATFORM := windows
    UV_ASSET := uv-x86_64-pc-windows-msvc.zip
    ICON     := assets/icon.ico
else
    PLATFORM := linux
    UV_ASSET := uv-x86_64-unknown-linux-gnu.tar.gz
    ICON     := assets/icon.png
endif

build: install-gui
	uv run pyinstaller \
		--name $(DIST_NAME) \
		--windowed \
		--icon=$(ICON) \
		--noconfirm \
		--clean \
		--collect-data pystray \
		src/hotel_agent/launcher.py
	@echo "Build complete: dist/$(DIST_NAME)/"

dist: build
	@mkdir -p $(DIST_DIR)/tools $(DIST_DIR)/assets
	# Copy app source and config
	cp -r src $(DIST_DIR)/
	cp pyproject.toml uv.lock $(DIST_DIR)/
	cp config.example.yaml $(DIST_DIR)/
	cp .env.example $(DIST_DIR)/
	cp -r assets $(DIST_DIR)/
	# Copy the built launcher
	cp -r dist/$(DIST_NAME)/* $(DIST_DIR)/ 2>/dev/null || true
	# Create zip
	cd dist && zip -r $(DIST_NAME)-$(PLATFORM).zip $(DIST_NAME)/
	@echo ""
	@echo "Distribution ready: dist/$(DIST_NAME)-$(PLATFORM).zip"
	@echo "Note: add the platform-specific uv binary to $(DIST_DIR)/tools/ before shipping."

clean:
	rm -rf build/ dist/ *.spec __pycache__

# ── Multi-platform Distribution ───────────────────────

# Build all platforms via GitHub Actions (requires gh CLI + internet)
# Triggers the release workflow, waits for completion, downloads all zips.
dist-all:
	@command -v gh >/dev/null 2>&1 || { echo "Error: gh CLI not found. Install: https://cli.github.com"; exit 1; }
	@echo "Triggering multi-platform build on GitHub Actions..."
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	gh workflow run release.yml --ref "$$BRANCH"
	@echo "Waiting for workflow to start..."
	@sleep 10
	@RUN_ID=$$(gh run list -w release.yml -L 1 --json databaseId -q '.[0].databaseId'); \
	echo "Run ID: $$RUN_ID — monitoring at:"; \
	echo "  https://github.com/$$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions/runs/$$RUN_ID"; \
	echo ""; \
	gh run watch "$$RUN_ID"; \
	STATUS=$$(gh run view "$$RUN_ID" --json conclusion -q .conclusion); \
	if [ "$$STATUS" != "success" ]; then \
		echo "Error: workflow failed ($$STATUS). Check the link above."; \
		exit 1; \
	fi; \
	echo ""; \
	echo "Downloading artifacts..."; \
	mkdir -p dist; \
	gh run download "$$RUN_ID" -D dist/; \
	echo ""; \
	echo "All platform builds downloaded to dist/:";\
	ls dist/**/*.zip 2>/dev/null || ls dist/*/*.zip 2>/dev/null

# Build Linux variants locally via act + Docker (requires docker/podman)
# macOS and Windows builds require their native OS — use dist-all for those.
dist-local:
	@command -v act >/dev/null 2>&1 || command -v $(HOME)/.cache/act-runner/act >/dev/null 2>&1 || \
		{ echo "Error: act not found. Install: https://github.com/nektos/act"; exit 1; }
	@ACT=$$(command -v act 2>/dev/null || echo "$(HOME)/.cache/act-runner/act"); \
	echo "Building Linux distributions locally via act..."; \
	echo "(macOS/Windows builds require GitHub Actions — use 'make dist-all')"; \
	echo ""; \
	mkdir -p dist; \
	"$$ACT" -W .github/workflows/release.yml \
		--artifact-server-path dist/act-artifacts \
		--matrix os:ubuntu-latest \
		-j build; \
	echo ""; \
	echo "Linux build artifacts saved to dist/act-artifacts/"
