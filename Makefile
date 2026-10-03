.PHONY: dev test seed drill build-web lint
dev:
	python -m cc_server.main --reload & cd cc_web && npm run dev
test:
	python -m pytest -q && cd cc_web && npm test --silent
seed:
	python scripts/seed_demo.py
drill:
	python scripts/kill_drill.py
build-web:
	cd cc_web && npm ci && npm run build
lint:
	ruff check cc_sdk cc_server bots scripts
