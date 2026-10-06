# diplomacy

This is an independent V-engine project. Configuration and trusted project plugins live here; source files, staging transcripts, SQLite, and attempts live in ignored `data/`.

Give your coding assistant [AGENTS.md](AGENTS.md) and your source files. The assistant configures the subject, imports originals or study sources, checks the review queue, and reports uncertain items. You approve questions in the browser.

After the V-engine package is published, run `uv sync` and `uv run python app.py`. Open `http://127.0.0.1:8765`. For a local engine checkout before publication, run `uv venv`, `uv pip install -e /path/to/V-engine`, then `uv run --no-sync python app.py`. Do not commit a local absolute dependency path.
