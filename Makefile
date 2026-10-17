.PHONY: start demo stop test

# One command to set up and run everything locally (same as ./start.sh).
start demo:
	./start.sh

# Free the dev ports if a run got stuck.
stop:
	-@lsof -ti tcp:3000 tcp:8000 tcp:8001 tcp:9000 | xargs kill 2>/dev/null || true
	@echo "stopped"

test:
	cd proxy && PYTHONPATH=. ../.venv/bin/python -m pytest -q
	cd backend && PYTHONPATH=. ../.venv/bin/python -m pytest tests -q
