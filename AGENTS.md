# Repository Guidelines

## Project Structure & Module Organization
`newsaggregator/` contains production modules: `config/settings.py` (feeds, API keys, throttles), `core/aggregator.py` (run loop), `fetchers/` (RSS, NewsAPI, Exa, ESPN), `processors/` (Gemini summaries plus weekly/game flows), `storage/` (file, Firestore, R2), `utils/` (retry + rate limits), and `web/app.py`. Root entry points (`main.py`, `main_sports.py`, `main_live_sports.py`, `weekly_summary.py`, `run_article_manager.py`) compose those modules. Artifacts live under `data/`; executable `test_*.py` scripts stay at the root.

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate`: isolate a Python 3.10+ runtime.
- `pip install -r requirements.txt`: install AI, Firebase, Exa, and storage deps.
- `python main.py`: rotate configured topics and write summaries defined by `core/aggregator.py`.
- `python main_sports.py` / `python main_live_sports.py`: ingest schedules or live updates via `storage/sports_storage.py`.
- `python weekly_summary.py`, `python run_article_manager.py`: produce weekly briefs and migrate historical assets.
- `python test_retry_logic.py`, `python test_sports_data.py`, etc.: run targeted smoke tests; see each file’s docstring for options.

## Coding Style & Naming Conventions
Stick to 4-space indents, sub-100-character lines, and type hints mirroring existing signatures. Modules + functions stay snake_case, classes CamelCase, constants UPPER_SNAKE (cf. `config/settings.py`). No formatter is enforced, but assume `black`-compatible spacing so diffs stay minimal. Route new helpers through `newsaggregator.utils` instead of duplicating HTTP, caching, or rate limiting logic, and keep docstrings/actionable logs brief.

## Testing Guidelines
Tests are script-based; each `test_*.py` module validates one subsystem (retry logic, sports data, image optimization). New coverage should follow that pattern, exit non-zero on failure, and avoid hard dependencies on production credentials. Keep helpers pytest-friendly (`pytest test_retry_logic.py`), seed deterministic payloads under `data/`, and guard network-heavy sections with environment checks for `GEMINI_API_KEY`, `EXA_API_KEY`, and Firebase credentials.

## Commit & Pull Request Guidelines
History shows short, imperative subjects (“Improve news and sports pipeline performance”). Continue that style, keep subjects ≤70 chars, and move rationale or rollout notes to the body. PRs should link the BriefSnap issue, list impacted modules, enumerate validation commands, and attach sanitized snippets from `data/` or console output. Include screenshots when touching `newsaggregator/web/app.py` or other user-facing assets.

## Security & Configuration Tips
Do not commit credentials (`firebase-credentials.json`, `.env`). Load secrets via environment variables or GitHub Actions (GEMINI_API_KEY, GEMINI_API_KEY_2, EXA_API_KEY, FIREBASE_CREDENTIALS). Treat `data/` exports as sensitive; scrub PII before sharing. Any change that shifts call volume must update throttles in `config/settings.py` (`REQUEST_DELAY`, `MAX_CONCURRENT_ARTICLE_FETCHES`) and mention the impact in the PR. When experimenting against Firestore or Gemini, target staging projects and limit `main_live_sports.py` runs to avoid quota churn.
