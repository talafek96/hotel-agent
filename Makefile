.PHONY: install install-gui lint format typecheck test check build dist clean

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
