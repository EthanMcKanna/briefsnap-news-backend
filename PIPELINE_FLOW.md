# BriefSnap Daily Brief Pipeline (V9)

The daily brief pipeline lives in `newsaggregator/briefs/` and runs three
times a day from GitHub Actions (`.github/workflows/news-aggregator.yml`,
13:00 / 18:00 / 23:00 UTC). Entry point: `python main.py`.

## Design principle

**Deterministic curation, LLM writing.**

The previous pipeline (V8) asked Gemini to both *select* and *write* the
brief, then patched its output with ~1,650 lines of repair heuristics and
a 183-check publish gate. V9 splits the responsibilities:

- What's in the brief is decided by auditable Python: feed gathering,
  junk screening, cross-outlet clustering, and consensus ranking.
- The model only writes prose over an already-curated packet, under a
  strict JSON schema. A compact (~25 check) gate validates the copy; a
  failure sends the specific issues back to the model for one corrective
  rewrite before falling back to the next model.

## Stages

```
gather -> screen -> cluster -> rank/select -> enrich -> write -> validate -> publish
```

| Stage | Module | What it does |
|---|---|---|
| Gather | `fetch.py` | ~47 sources in parallel: curated publisher RSS per topic, Google News topic/search feeds, ESPN league news. Feed failures are non-fatal. |
| Screen | `screen.py` | Canonicalize URLs (strip tracking params), reject opinion/liveblog/press-release/gambling/explainer junk, classify topics from content signals, map publisher display names. |
| Cluster | `cluster.py` | Union-find grouping of same-story coverage across outlets (stemmed token overlap, 48h window). Cluster breadth = consensus. |
| Rank | `rank.py` | Score = cross-outlet consensus (log-scaled trusted domains) + source tier + recency decay + quality. Select ~20 with per-topic targets, domain caps, and near-duplicate suppression. Topics are never padded with weak clusters. |
| Enrich | `enrich.py` | Scrape only the selected ~20 leads (via `ArticleFetcher`): body text for grounding + validated article image. Resolves Google News redirects. |
| Sports | `sports.py` | ESPN scoreboard packet (max 6 cards, 2/league, live-first) — same card shape the iOS app has always consumed. |
| Write | `writer.py` | One structured Gemini call (`gemini-3-flash-preview`, fallback `gemini-2.5-flash`) with the packet. No search grounding needed — the packet is the ground truth. Custom widgets use search grounding since user topics fall outside the packet. |
| Validate | `validate.py` | ~25 checks: complete headline (no truncation), prose dek, resolvable story ids, section coverage, word budgets, banned filler. Issues feed back verbatim as a corrective prompt. |
| Publish | `publish.py` | `daily_briefs/{YYYY-MM-DD}` + `daily_brief_history` + legacy `news_summaries` shim + custom widget refresh. |

## Firestore contract (unchanged from V8)

`daily_briefs/{date}`: `id, generated_at, model_used, headline, dek,
summary, quick_hits[], hero_image_url, sections[{topic, title, summary,
why_it_matters, story_ids[]}], stories[{id, topic, title, source, url,
summary, why_it_matters, urgency, published_at, image_url}],
sports_scores[], source_count, coverage_report{}`.

Sports scores are refreshed independently of brief generation:
`main_sports.py` (hourly) and `main_live_sports.py` (every 5 min) call
`DailyBriefPipeline.refresh_latest_firestore_sports_scores()`, and a
Firebase scheduled function does the same every 5 minutes.

## Running locally

```bash
python main.py --dry-run          # no Gemini, no Firestore; writes local artifact
python main.py --skip-firestore   # real Gemini writing, no publish
python main.py                    # full run + publish
python verify_daily_brief_release.py --brief-json data/daily_briefs/daily_brief_<date>.json
python -m pytest test_daily_brief_pipeline.py
```

Secrets: `GEMINI_API_KEY` (+ optional `GEMINI_API_KEY_2` failover) and
`firebase-credentials.json` (or `FIREBASE_CREDENTIALS` inline JSON).
Local runs load `.env` automatically.

## Tuning

Everything tunable lives in `config.py` (feeds, trusted domains, topic
targets, thresholds, copy budgets); most values have `BRIEFSNAP_*` env
overrides.
