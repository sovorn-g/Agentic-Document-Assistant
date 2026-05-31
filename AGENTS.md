# Agent Instructions

- Default development and verification workflow is the local Python virtualenv (`.venv`).
- Use `./.venv/bin/python ...`, `./.venv/bin/pip ...`, and `cd frontend && npm run build` for normal checks.
- Do **not** build, run, restart, or test Docker (`Dockerfile`, `docker compose`, `docker build`, `docker run`, etc.) unless the user explicitly asks for Docker/container validation.
- Docker/Compose files are for user-triggered container runs only; routine coding work should use the venv app entrypoint:
  - `./.venv/bin/python app.py`
  - or `./.venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 7860`
