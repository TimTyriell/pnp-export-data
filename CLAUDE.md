# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An LLM-driven agent service that **reads and maintains a Fandom/MediaWiki wiki**
from our Pen-&-Paper campaign's session reports. The goal: turn LLM-generated
session reports (eventually sourced from a graph) into well-structured,
cross-linked wiki pages automatically, instead of editing the wiki by hand.

The service is the **downstream consumer of pnp-crawl** — its input are the
session reports that pnp-crawl's planned stage-4 report generator produces (see
`REPORT_TYPES`/`CAMPAIGN_CONTEXT` in `../pnp-crawl/config.py`). It is otherwise
independent of the other repos under `c:\dev\pnp` (separate git remote, own
language/tooling). Don't assume changes here affect them or vice versa.

The campaign and all generated content are **German** (`LANGUAGE = "de"`). Write
example data, prompts, and generated Wikitext in German, not English.

## Architecture

A 4-stage CLI pipeline, scripts numbered `01`–`04` to match stage order. Each
stage reads the previous stage's output directory and is idempotent — re-running
after adding new reports is safe.

```
01_inventory.py  Wiki → page index/plan in wiki_cache/   (what already exists)
02_extract.py    reports/ → entities.json via Ollama       (NPCs/places/events…)
03_generate.py   entities + index → proposals/ Wikitext    (the dry-run output)
04_upload.py     reviewed proposals/ → wiki                 (gated; see below)
```

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

Stages 1 and the wiki client are implemented; **stages 2 and 3 are scaffolded
stubs** that raise `NotImplementedError` with a TODO describing the intended
Ollama call. When implementing them, follow the docstring contract: stage 2
writes `wiki_cache/entities.json` with per-entity `action: create|update`; stage
3 writes `proposals/<Title>.wikitext` (+ `.diff` for updates).

## Conventions & setup

- **Python**, local LLM via **Ollama** (`config.OLLAMA_HOST`/`OLLAMA_MODEL`);
  no cloud LLM API. Talk to it via its HTTP API, don't add an OpenAI/Anthropic
  dependency unless asked.
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
