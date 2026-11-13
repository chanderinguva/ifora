# Local quality and security gates (IFORA-20). No GitHub Actions: everything runs on your machine.
#
#   make check        every gate; exits non-zero if any gate fails (paste the output into the PR)
#   make check-fast   lint, types on changed files, secret scan; the pre-push hook runs this
#   make hooks        install the pre-push hook (sets core.hooksPath for THIS checkout)
#   make tools        print install instructions for every tool a gate needs
#
# Gates run all the way through even after one fails, so one run shows every problem.

SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
BASE ?= origin/main

# Where the tools come from. Default: your PATH. Override with e.g. PY_RUN="docker run --rm -v $$PWD:/src -w /src ifora-tools".
RUFF ?= ruff
MYPY ?= mypy
BANDIT ?= bandit
PIP_AUDIT ?= pip-audit
GITLEAKS ?= gitleaks
SEMGREP ?= semgrep
TRIVY ?= trivy

GATES_ALL := lint-py types-py secrets sast-bandit sast-semgrep deps-py test-backend lint-web types-web deps-web no-workflows image-pins
GATES_FAST := lint-py types-py secrets lint-web types-web no-workflows image-pins

.PHONY: check check-fast hooks tools e2e images-scan lock $(GATES_ALL)

check:
	@failed=""; \
	for g in $(GATES_ALL); do \
	  echo; echo "=== $$g ==="; \
	  $(MAKE) --no-print-directory $$g || failed="$$failed $$g"; \
	done; \
	echo; \
	if [ -n "$$failed" ]; then echo "FAILED gates:$$failed"; exit 1; fi; \
	echo "All gates passed."

check-fast:
	@failed=""; \
	for g in $(GATES_FAST); do \
	  echo; echo "=== $$g ==="; \
	  $(MAKE) --no-print-directory $$g || failed="$$failed $$g"; \
	done; \
	echo; \
	if [ -n "$$failed" ]; then echo "FAILED gates:$$failed"; exit 1; fi; \
	echo "Fast gates passed."

hooks:
	git config core.hooksPath .githooks
	@echo "pre-push hook installed for this checkout (core.hooksPath=.githooks)."

tools:
	@cat scripts/TOOLS.txt

# ---- Python ---------------------------------------------------------------------------------------------------
# Lint: real errors only (see backend/ruff.toml). `ruff format --check` is reported by `make format-report`, not gated,
# because the existing code base is not ruff-formatted (baseline recorded in the IFORA-20 PR).
lint-py:
	@scripts/need.sh $(RUFF) "pip install -r backend/requirements-dev.txt"
	cd $(BACKEND) && $(RUFF) check .
	@files=$$( (git diff --name-only --diff-filter=AM $(BASE)...HEAD -- '$(BACKEND)/app/*.py' '$(BACKEND)/app/**/*.py'; \
	            git diff --name-only --diff-filter=AM -- '$(BACKEND)/app/*.py' '$(BACKEND)/app/**/*.py') | sort -u | sed 's#^$(BACKEND)/##' | grep . || true); \
	if [ -z "$$files" ]; then echo "no changed backend/app files against $(BASE); strict pass skipped"; \
	else echo "strict pass (F, minus F811) on changed files:"; echo "$$files"; cd $(BACKEND) && $(RUFF) check --select F --ignore F811 $$files; fi

format-report:
	@scripts/need.sh $(RUFF) "pip install -r backend/requirements-dev.txt"
	-cd $(BACKEND) && $(RUFF) format --check . | tail -5

# Types: mypy is gated on files changed against $(BASE) only. The existing code base is not typed; widening is a follow-up.
types-py:
	@scripts/need.sh $(MYPY) "pip install -r backend/requirements-dev.txt"
	@files=$$(git diff --name-only --diff-filter=AM $(BASE)...HEAD -- '$(BACKEND)/app/*.py' '$(BACKEND)/app/**/*.py'; \
	          git diff --name-only --diff-filter=AM -- '$(BACKEND)/app/*.py' '$(BACKEND)/app/**/*.py'); \
	files=$$(echo "$$files" | sort -u | grep . || true); \
	if [ -z "$$files" ]; then echo "no changed backend/app files against $(BASE); nothing to type-check"; exit 0; fi; \
	echo "$$files"; \
	$(MYPY) --config-file $(BACKEND)/mypy.ini $$files

# Static analysis: bandit gates on HIGH severity; medium findings are a recorded baseline (see PR) and not gated yet.
sast-bandit:
	@scripts/need.sh $(BANDIT) "pip install -r backend/requirements-dev.txt"
	$(BANDIT) -q -r $(BACKEND)/app -lll -c $(BACKEND)/bandit.yaml

# Semgrep community rules. --metrics=off and --config p/python only: rule download, no code upload.
sast-semgrep:
	@scripts/need.sh $(SEMGREP) "pip install semgrep==1.97.0   (or: brew install semgrep)"
	$(SEMGREP) scan --config p/python --metrics=off --error --quiet $(BACKEND)/app

# Dependency vulnerabilities: fails on any advisory unless it is in .security-allowlist with a reason and an unexpired date.
deps-py:
	@scripts/need.sh $(PIP_AUDIT) "pip install -r backend/requirements-dev.txt"
	python3 scripts/pip_audit_gate.py --requirements $(BACKEND)/requirements.txt --allowlist .security-allowlist --pip-audit $(PIP_AUDIT)

# ---- Secrets ----------------------------------------------------------------------------------------------------
# Whole-history baseline scan (slower) is `make secrets-history`; day to day we scan the working tree and staged changes.
secrets:
	@scripts/need.sh $(GITLEAKS) "brew install gitleaks   (v8.x)"
	$(GITLEAKS) detect --no-git --source . --config .gitleaks.toml --redact --no-banner

secrets-history:
	@scripts/need.sh $(GITLEAKS) "brew install gitleaks   (v8.x)"
	$(GITLEAKS) detect --source . --config .gitleaks.toml --redact --no-banner

# ---- Dependency lock (IFORA-21) ---------------------------------------------------------------------------------
# requirements.in / requirements-dev.in are the human-edited inputs; the .txt files are generated with hashes and
# installed with --require-hashes. Edit a .in file, run `make lock`, commit both. Needs uv (brew install uv).
# To upgrade everything: make lock UV_LOCK_ARGS=--upgrade
UV_LOCK_ARGS ?=
lock:
	@scripts/need.sh uv "brew install uv"
	cd $(BACKEND) && uv pip compile requirements.in --universal --python-version 3.12 --generate-hashes $(UV_LOCK_ARGS) -o requirements.txt
	cd $(BACKEND) && uv pip compile requirements-dev.in --universal --python-version 3.12 --generate-hashes $(UV_LOCK_ARGS) -o requirements-dev.txt

# ---- Backend tests ----------------------------------------------------------------------------------------------
# Needs the compose stack and a rebuilt backend-api image (see README "Testing"): tests use the ifora_test database.
test-backend:
	@scripts/need.sh docker "install Docker Desktop"
	scripts/test_backend.sh $(PYTEST_ARGS)

# ---- Frontend ---------------------------------------------------------------------------------------------------
lint-web:
	@scripts/need.sh npm "brew install node"
	cd $(FRONTEND) && npm run lint < /dev/null

types-web:
	@scripts/need.sh npm "brew install node"
	cd $(FRONTEND) && npm run type-check

deps-web:
	@scripts/need.sh npm "brew install node"
	cd $(FRONTEND) && npm audit --omit=dev --audit-level=high

# ---- Policy: no hosted CI ---------------------------------------------------------------------------------------
no-workflows:
	@if [ -d .github/workflows ] && [ -n "$$(ls -A .github/workflows 2>/dev/null)" ]; then \
	  echo "FAIL: .github/workflows must stay empty (no paid GitHub Actions). Found:"; ls .github/workflows; exit 1; \
	else echo "ok: no workflow files"; fi

# Every FROM / image: must carry an @sha256 digest (IFORA-21). Refresh procedure: README "Image pins".
image-pins:
	python3 scripts/check_image_pins.py

# ---- Optional ---------------------------------------------------------------------------------------------------
e2e:
	cd $(FRONTEND) && npx playwright test

images-scan:
	@scripts/need.sh $(TRIVY) "brew install trivy"
	$(TRIVY) fs --scanners vuln,secret --severity HIGH,CRITICAL --exit-code 1 .
