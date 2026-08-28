# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The **output repo** of the three-repo campaign toolchain (input: `pnp-crawl`,
memory: `pnp-knowledge`, output: this). An agent service that **reads and
maintains the campaign's Fandom/MediaWiki wiki** from the Knowledge-Base — it
is a *client of the KB API*, never a knowledge store of its own (ADR-001 in
`../pnp-knowledge/docs/architecture/`).

Its input is the read-only KB API served from the memory repo
(`config.KB_URL`, default `http://127.0.0.1:8070` — start via
`cd ../pnp-knowledge/services/kb && python -m pnp_okf.api`). The old
`reports/` input path is gone.

The campaign and all generated content are **German** (`LANGUAGE = "de"`). Write
example data, prompts, and generated Wikitext in German, not English.

## Architecture

A 4-stage CLI pipeline, scripts numbered `01`–`04` to match stage order. Each
stage reads the previous stage's output directory and is idempotent — re-running
after adding new reports is safe.

```
01_inventory.py  Wiki → page index in wiki_cache/          (what already exists)
02_extract.py    KB API + wiki_pages.toml vs page index    (create|update plan;
                 → entities.json + bodies.json              deterministic, no LLM)
03_generate.py   plan + KB bodies → proposals/ Wikitext     (md2wiki.py converts
                                                            deterministically:
                                                            .wikitext per page,
                                                            .diff for updates,
                                                            NEW_PAGES.md list)
04_upload.py     reviewed proposals/ → wiki                 (gated; see below)
```

There is **no LLM anywhere in this pipeline**, so a re-run costs no tokens —
only HTTP round trips. Those are kept down by three things, don't undo them:
stage 2 saves the concept bodies its alias/session call already returned into
`wiki_cache/bodies.json` (stage 3 reads that instead of re-fetching, and the
plan beside it comes from the same snapshot); stage 3 reads live pages through
`WikiClient.read_many` in batches of 50 rather than one request per page; and
stage 4 skips any proposal whose `.diff` is empty, because that edit would be a
`nochange` round trip plus `EDIT_DELAY_S`. A *missing* `.diff` still uploads —
absence is not proof the page is unchanged.

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
*appends* KB sections whose heading isn't already present, and unions
categories. The KB's `# Belege` citation list itself is never proposed — it is
dropped in `pagemap.compose_body`; the wiki cites inline instead, via
`md2wiki` resolving each `[P-08]`/`[[P-08]]` marker in the text to that
episode's own wiki page. Nothing hand-written is ever deleted — the
`.diff` a reviewer sees is additions-only. Redundant sections (a human
"Persönlichkeit" and a KB one worded differently) both survive; the reviewer
trims overlap. Do not change this to overwrite existing pages.

**Entities are not pages** ([pagemap.py](pagemap.py) + the committed
[wiki_pages.toml](wiki_pages.toml)). The KB wants one node per entity, the wiki
wants readable articles, so a page can gather several concepts: a `lead` owns
the page's identity (id, type, category, aliases, harvest attribution), a `sub`
only ever appears as a section on it, and several leads are an equal-weight
merge under a name of its own. **The merge exists only here** — never propose
folding concepts together in `../pnp-knowledge/knowledge/`, that bundle is the
system of record and presentation is not knowledge (ADR-001). Only exceptions
are listed; unmapped concepts keep the 1:1 path and `compose_body` passes a
lone lead through byte-identically, so the map cannot change a page it says
nothing about.

A composed page is **one markdown level per member**: each member gets its own
heading and keeps its sections nested below it, so the page reads as one
article with sub-entries. A sole lead has no heading — it *is* the page — so
its sections are promoted to that level instead. This only survives because
stage 3 passes `structured=True` into the merge for multi-member pages:
`wikimerge._flatten_kb` normally flattens every heading to level 2 (right for a
single concept, whose sections are the merge units), which on a composed page
dissolves the nesting and leaves four articles glued end to end. If a merged
page ever reads as a flat run of sections again, that flag is where to look.

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

## Logging & debugging (read this before touching output)

Every stage writes structured events to `logs/<run_id>.jsonl` via
[runlog.py](runlog.py) — one JSON object per line, one file per run, gitignored.
`proposals/` is flat, so **the run log is the only record of which run wrote
which file** (`write` events carry `name`, `bytes`, `sha8`) and of *why* a page
came out the way it did.

Stage 3 **prunes** `proposals/` at the end of each run: its own leftovers
(`.wikitext`, `.diff`, `NEW_PAGES.md`) that this run did not write are deleted,
with a `prune` event per file so the record outlives the file. Anything else in
the directory is left alone — a `notizen.md` or a `.bak` is not this stage's to
delete. Everything pruned is regenerable by re-running the stage, so review
what you care about before the next run rather than treating the directory as
an archive.

- `run_id` = UTC timestamp + pid, or `PNP_RUN_ID` if set. One file per run means
  parallel agents never contend for the same log — each just sets its own
  `PNP_RUN_ID`.
- The `merge` event per updated page is the main debug hook: `live_bytes`,
  `live_headings` (level-2 sections), `live_headings_all` (everything matched
  against), `kb_headings`, `appended`, `skipped`, `out_sha8`. A bad merge is
  visible from that one line without opening the file.
- `anomaly` events (`level: "warn"`) report smells, they never change a merge:
  `live_headings_empty` (live page has no heading to match → whole article gets
  appended again), `full_reappend`, `dup_heading`, `dup_content` (two proposal
  files with identical bytes — stale near-duplicate titles). Detectors live in
  [03_generate.py](03_generate.py) next to `generate_proposals`.
- Stage 2 logs a `plan_entry` per exported entity **and** a `skip` per dropped
  one with its reason — `entities.json` only shows the survivors.

Read it with plain tools; there is no query CLI on purpose:

```bash
ls logs/                                        # runs, newest last
grep '"level": "warn"' logs/<run_id>.jsonl      # everything suspicious
grep '"title": "Cookie"' logs/<run_id>.jsonl    # one page's whole story
```

**Rules for agents working in this repo:**

1. Set `PNP_RUN_ID=agent-<kurzslug>` at the start of your session.
2. Look at `logs/` before you touch anything — don't guess which proposal file
   is current, check the `write` event.
3. After every article you write or edit by hand, log it into the same stream:
   ```bash
   python runlog.py --stage agent --event edit --target "Slix" \
       --note "KB-Dublette unter 'Persönlichkeit' entfernt"
   ```
4. Never share a `PNP_RUN_ID` with another agent running at the same time.

## The review gate (important)

This service writes to a live wiki, so writes are gated by design:

- `config.DRY_RUN` defaults to **True** (env `FANDOM_DRY_RUN=1`). Stage 4 then
  only prints what it *would* upload.
- Uploading requires **both** `--apply` on stage 4 **and** `FANDOM_DRY_RUN=0`.
- Generated pages are meant to land in a draft/sandbox namespace
  (`config.DRAFT_NAMESPACE`, default `User`) for human review before promotion to
  live, to guard against hallucinations.
- The VS Code launch config for stage 4 runs `01→02→03` first
  (`.vscode/tasks.json`, `preLaunchTask`). Stage 4 only edits titles the plan
  marks `update`, and that verdict comes from the page index — so a page a human
  created since the last inventory stays empty forever unless the index is
  refreshed first. The trade-off: proposals are rebuilt in the same click, so
  read the `.diff` files after the tasks finish, not before.

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
- `reports/`, `wiki_cache/`, `proposals/`, and `logs/` are gitignored
  generated/cached data — don't propose committing their contents.
- No system Python is on PATH in this environment (the sibling pnp-crawl
  installs into a venv). Set up a venv (`fandom_env/`, gitignored) per the
  README before running anything.
- No test suite yet. Validate API/generation changes by running the relevant
  stage with `DRY_RUN` on and inspecting `wiki_cache/` / `proposals/` output —
  never test write paths against the live wiki.
- Be courteous to the Fandom API: a contact `User-Agent` is set in config and
  required by their policy; respect rate limits when adding bulk operations.
