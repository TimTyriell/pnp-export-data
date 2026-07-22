# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The **output repo** of the three-repo campaign toolchain (input: `pnp-crawl`,
memory: `pnp-graph-service`, output: this). An agent service that **reads and
maintains the campaign's Fandom/MediaWiki wiki** from the Knowledge-Base — it
is a *client of the KB API*, never a knowledge store of its own (ADR-001 in
`../pnp-graph-service/docs/architecture/`).

Its input is the read-only KB API served from the memory repo
(`config.KB_URL`, default `http://127.0.0.1:8070` — start via
`cd ../pnp-graph-service/services/kb && python -m pnp_okf.api`). The old
`reports/` input path is gone.

The campaign and all generated content are **German** (`LANGUAGE = "de"`). Write
example data, prompts, and generated Wikitext in German, not English.

## Architecture

A 4-stage CLI pipeline, scripts numbered `01`–`04` to match stage order. Each
stage reads the previous stage's output directory and is idempotent — re-running
after adding new reports is safe.

```
01_inventory.py  Wiki → page index in wiki_cache/          (what already exists)
02_extract.py    KB API vs page index → entities.json      (create|update plan;
                                                            deterministic, no LLM)
03_generate.py   plan + KB bodies → proposals/ Wikitext     (md2wiki.py converts
                                                            deterministically:
                                                            .wikitext per page,
                                                            .diff for updates,
                                                            NEW_PAGES.md list)
04_upload.py     reviewed proposals/ → wiki                 (gated; see below)
```

Stages 2/3 are **deterministic** — the KB bodies are already synthesized,
cited German markdown, so conversion cannot hallucinate. [md2wiki.py](md2wiki.py)
maps headings/bold/lists/links to Wikitext; concept links resolve via the
plan's concept→wiki-title map, links to concepts without a wiki page degrade
to plain text. New pages are never created by the agent: `NEW_PAGES.md` lists
them for a human to create manually, after which the next sync fills them via
the update path.

**Updates are an additive section-merge, never a replace**
([wikimerge.py](wikimerge.py)). The live wiki pages are hand-curated
(infoboxes, images, prose, categories); a full replace would destroy that.
So for `action: update` the proposal keeps the live page verbatim and only
*appends* KB sections whose heading isn't already present (plus the `Belege`
citations), and unions categories. Nothing hand-written is ever deleted — the
`.diff` a reviewer sees is additions-only. Redundant sections (a human
"Persönlichkeit" and a KB one worded differently) both survive; the reviewer
trims overlap. Do not change this to overwrite existing pages.

- **[config.py](config.py)** is the single source of truth for all tunables
  (wiki URL, bot creds via env, Ollama host/model, directories, `DRY_RUN`).
  Scripts import from it directly; there are no CLI flags for these values.
  When asked to change behaviour, edit `config.py`, not the stage scripts —
  unless the change is structural. This mirrors pnp-crawl's convention.
- **[wiki_client.py](wiki_client.py)** is the shared MediaWiki Action API client:
  bot login (two-step token dance), `all_pages`, `read`, and `edit`. **`edit()`
  honours `config.DRY_RUN`** — when set it returns the would-be payload instead
  of POSTing, so generation/review can run without touching live content.
- Stage 1 builds the **page index** that later stages feed to the LLM so it can
  emit valid `[[Page]]` links and decide create-vs-update. This index is the
  mechanism that makes cross-references resolve — keep it fresh before
  generating.

## The review gate (important)

This service writes to a live wiki, so writes are gated by design:

- `config.DRY_RUN` defaults to **True** (env `FANDOM_DRY_RUN=1`). Stage 4 then
  only prints what it *would* upload.
- Uploading requires **both** `--apply` on stage 4 **and** `FANDOM_DRY_RUN=0`.
- Generated pages are meant to land in a draft/sandbox namespace
  (`config.DRAFT_NAMESPACE`, default `User`) for human review before promotion to
  live, to guard against hallucinations.

Do not weaken or bypass this gate (e.g. defaulting `DRY_RUN` to False, hardcoding
`--apply`, or POSTing directly) without the user explicitly asking.

## Status

All four stages implemented. Stage 2 writes `wiki_cache/entities.json` with
per-entity `action: create|update` (title/alias match against the page
index); stage 3 writes `proposals/<Title>.wikitext` (+ `.diff` for updates,
`NEW_PAGES.md` for creates). Offline tests: `python -m pytest`
([test_export.py](test_export.py) — converter, planning, proposal cores; no
network/wiki needed). The wiki itself is not yet configured
(`WIKI_API_URL` placeholder) — stage 1/DIFFS need a real wiki.

## Conventions & setup

- **Python**, no LLM in the pipeline (deterministic conversion; the Ollama
  settings in config are kept only for a possible future prose-polish pass —
  don't add an OpenAI/Anthropic dependency unless asked).
- Secrets (bot password, wiki URL) come from `.env` via `python-dotenv`
  (optional, falls back to shell env), same pattern as pnp-crawl. Never hardcode
  them into `config.py`. `.env.example` documents the keys.
- `reports/`, `wiki_cache/`, and `proposals/` are gitignored generated/cached
  data — don't propose committing their contents.
- No system Python is on PATH in this environment (the sibling pnp-crawl
  installs into a venv). Set up a venv (`fandom_env/`, gitignored) per the
  README before running anything.
- No test suite yet. Validate API/generation changes by running the relevant
  stage with `DRY_RUN` on and inspecting `wiki_cache/` / `proposals/` output —
  never test write paths against the live wiki.
- Be courteous to the Fandom API: a contact `User-Agent` is set in config and
  required by their policy; respect rate limits when adding bulk operations.
