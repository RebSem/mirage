# Mirage: everyday commands. Run `make` to list them.

PY := venv/bin/python
RUFF_VERSION := 0.15.7
RUFF := $(or $(wildcard venv/bin/ruff),$(shell command -v ruff 2>/dev/null),uvx ruff@$(RUFF_VERSION))

.DEFAULT_GOAL := help
.PHONY: help install run classic app install-app icon test lint bench clean

help: ## Show this list
	@printf "\033[1mMirage\033[0m, real-time face swap for macOS\n\n"
	@awk 'BEGIN { FS = ":.*## " } /^[a-z-]+:.*## / { printf "  \033[36mmake %-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\n  Options: make install ARGS=\"--with-enhancer --yes\"\n"

install: ## Set up Python, packages, models and OBS (safe to re-run)
	scripts/install.sh $(ARGS)

run: $(PY) ## Start Mirage
	$(PY) -m mirage

classic: $(PY) ## Start the original Deep-Live-Cam window
	$(PY) run.py --execution-provider coreml

app: ## Build dist/Mirage.app
	scripts/build_app.sh

install-app: ## Build Mirage.app and put it in ~/Applications
	scripts/build_app.sh --install

icon: $(PY) ## Redraw the app icon into assets/icon
	$(PY) scripts/make_icon.py

test: $(PY) ## Run the Mirage unit tests (no models or camera needed)
	$(PY) -m pytest -q tests/mirage

lint: ## Lint Python with ruff (and shell scripts with shellcheck, if installed)
	$(RUFF) check mirage tests/mirage scripts
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh; fi

bench: $(PY) ## Time the face-swap model on each CoreML compute unit
	$(PY) scripts/benchmark.py

clean: ## Remove build output and Python caches
	rm -rf dist build
	find . -path ./venv -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +

$(PY):
	@echo "Mirage is not installed yet: run  make install  first." >&2; exit 1
