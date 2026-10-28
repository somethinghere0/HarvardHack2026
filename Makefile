.PHONY: start demo stop test

# One command to set up and run everything locally (same as ./start.sh).
start demo:
	./start.sh

# Free the dev ports if a run got stuck.
stop:
	-@lsof -t -i tcp:3000 -i tcp:8000 -i tcp:8001 -i tcp:9000 | xargs kill 2>/dev/null || true
	@echo "stopped"

test:
	cd proxy && PYTHONPATH=. ../.venv/bin/python -m pytest -q
	cd backend && PYTHONPATH=. ../.venv/bin/python -m pytest tests -q
