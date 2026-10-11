# NEUROGRID developer shortcuts. Uses the repository's existing workflow (venv + npm).
PY ?= python3
BACKEND := backend
FRONTEND := frontend

.PHONY: install backend frontend test test-backend test-frontend e2e lint build demo-data

install:
	cd $(BACKEND) && $(PY) -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd $(FRONTEND) && npm install

backend:
	cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd $(FRONTEND) && npm run dev

demo-data:  ## load the official scenario into a running backend
	curl -s -X POST localhost:8000/api/datasets/import $(foreach f,$(wildcard data/*.csv),-F files=@$(f)) | head -c 300; echo

test: test-backend test-frontend

test-backend:
	cd $(BACKEND) && .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .

test-frontend:
	cd $(FRONTEND) && npx tsc --noEmit && npm run lint && npm test

e2e:  ## starts its own backend on a fresh DB (stop anything on :8000 first)
	cd $(FRONTEND) && npx playwright install chromium && npx playwright test

build:
	cd $(FRONTEND) && npm run build
