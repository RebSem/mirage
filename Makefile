# Mirage: everyday commands. Run `make` to list them.

PY := venv/bin/python
RUFF_VERSION := 0.15.7
RUFF := $(or $(wildcard venv/bin/ruff),$(shell command -v ruff 2>/dev/null),uvx ruff@$(RUFF_VERSION))

.DEFAULT_GOAL := help
.PHONY: help install dev run classic app install-app icon test lint bench clean update-engine

help: ## Show this list
	@printf "\033[1mMirage\033[0m, real-time face swap for macOS\n\n"
	@awk 'BEGIN { FS = ":.*## " } /^[a-z-]+:.*## / { printf "  \033[36mmake %-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\n  Options: make install ARGS=\"--with-enhancer --yes\"\n"

install: ## Set up Python, packages, models and OBS (safe to re-run)
	scripts/install.sh $(ARGS)

dev: $(PY) ## Install test/lint tools (pytest, ruff) into the venv
	$(PY) -m pip install -q -r requirements-dev.txt

run: $(PY) ## Start Mirage
	$(PY) -m mirage

classic: $(PY) ## Start the classic Deep-Live-Cam window (the engine Mirage is built on)
	$(PY) third_party/deep-live-cam/run.py --execution-provider coreml

app: ## Build dist/Mirage.app
	scripts/build_app.sh

install-app: ## Build Mirage.app, put it in ~/Applications and a Mirage shortcut in this folder
	scripts/build_app.sh --install

icon: $(PY) ## Redraw the app icon into assets/icon
	$(PY) scripts/make_icon.py

test: $(PY) ## Run the unit tests, Mirage's and the engine's (no models or camera needed)
	@$(PY) -c "import pytest" 2>/dev/null || $(MAKE) --no-print-directory dev
	$(PY) -m pytest -q tests/mirage third_party/deep-live-cam/tests

lint: ## Lint Python with ruff (and shell scripts with shellcheck, if installed)
	$(RUFF) check mirage tests scripts third_party
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh; fi

bench: $(PY) ## Time the face-swap model on each CoreML compute unit
	$(PY) scripts/benchmark.py

clean: ## Remove build output and Python caches (keeps the installed app)
	rm -rf dist build
	find . -path ./venv -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +
	@# the engine used to live in ./modules; git leaves its empty folders behind
	@if [ -d modules ] && [ ! -e modules/__init__.py ]; then find modules -depth -type d -empty -delete; fi

update-engine: ## Merge upstream Deep-Live-Cam changes into third_party/deep-live-cam (REF=<commit>)
	scripts/update_engine.sh $(REF)

$(PY):
	@echo "Mirage is not installed yet: run  make install  first." >&2; exit 1
