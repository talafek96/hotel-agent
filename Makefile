.PHONY: install install-gui lint format typecheck test check build dist dist-ci dist-docker clean

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

# ── Version ───────────────────────────────────────────
# Format: YYYY.MM.DD[+N.gSHA] where N = commits since last tag
# Tagged commit:  2026.03.21
# Dev build:      2026.03.21+5.gabc1234
# No tags:        0.0.0+abc1234

VERSION := $(shell V=$$(git describe --tags --match 'v*' 2>/dev/null | sed 's/^v//' | sed 's/-/+/' | sed 's/-/./'); if [ -z "$$V" ]; then V="0.0.0+$$(git rev-parse --short HEAD)"; fi; echo "$$V")

# ── Build & Distribution ──────────────────────────────

DIST_NAME := HotelPriceTracker
PORT      := 8470

# Detect platform
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    PLATFORM := macos-arm64
    ICON     := assets/icon.icns
else ifeq ($(OS),Windows_NT)
    PLATFORM := windows-x86_64
    ICON     := assets/icon.ico
else
    PLATFORM := linux-x86_64
    ICON     := assets/icon.png
endif

DIST_ZIP  := $(DIST_NAME)-$(VERSION)-$(PLATFORM).zip
DIST_DIR  := dist/$(DIST_NAME)

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

# Build distribution for current platform
dist: build
	@mkdir -p $(DIST_DIR)/tools $(DIST_DIR)/assets
	cp -r src $(DIST_DIR)/
	cp pyproject.toml uv.lock $(DIST_DIR)/
	cp config.example.yaml $(DIST_DIR)/
	cp .env.example $(DIST_DIR)/
	cp -r assets $(DIST_DIR)/
	cp -r dist/$(DIST_NAME)/* $(DIST_DIR)/ 2>/dev/null || true
	cd dist && python3 -m zipfile -c $(DIST_ZIP) $(DIST_NAME)/
	@echo ""
	@echo "Distribution ready: dist/$(DIST_ZIP)"
	@echo "Note: add the platform-specific uv binary to $(DIST_DIR)/tools/ before shipping."

clean:
	rm -rf build/ dist/ *.spec __pycache__

# ── Multi-platform Distribution ───────────────────────

# Build all platforms via GitHub Actions (requires gh CLI + internet).
# Triggers the release workflow, waits for completion, downloads all zips.
dist-ci:
	@command -v gh >/dev/null 2>&1 || { echo "Error: gh CLI not found. Install: https://cli.github.com"; exit 1; }
	@echo "Triggering multi-platform build on GitHub Actions..."
	@echo "Version: $(VERSION)"
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

# Build Linux variants locally via act + Docker (requires docker/podman).
# macOS and Windows builds require their native OS — use dist-ci for those.
dist-docker:
	@command -v act >/dev/null 2>&1 || command -v $(HOME)/.cache/act-runner/act >/dev/null 2>&1 || \
		{ echo "Error: act not found. Install: https://github.com/nektos/act"; exit 1; }
	@ACT=$$(command -v act 2>/dev/null || echo "$(HOME)/.cache/act-runner/act"); \
	echo "Building Linux distributions locally via act + Docker..."; \
	echo "(macOS/Windows builds require GitHub Actions — use 'make dist-ci')"; \
	echo ""; \
	mkdir -p dist; \
	"$$ACT" -W .github/workflows/release.yml \
		--artifact-server-path dist/act-artifacts \
		--matrix os:ubuntu-latest \
		-j build; \
	echo ""; \
	echo "Linux build artifacts saved to dist/act-artifacts/"
