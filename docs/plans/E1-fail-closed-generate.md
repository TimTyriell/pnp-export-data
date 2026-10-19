# E1 — Stage 3 fails closed when the live wiki can't be read

| | |
|---|---|
| Branch | `fix/fail-closed-generate` |
| Depends on | E0 |
| Size | S |
| Severity | **Data loss**: hand-written wiki content overwritten |

## The two bugs

**A. Per-page fallback to raw KB text.**
- `03_generate.py` `main()` (~lines 470-482): if `WikiClient().read_many`
  raises `RequestException`, it logs `wiki_unreachable` and continues with
  `live_pages = {}`.
- Then `generate_proposals` (~lines 357-397): for every `update` entity not
  in `live_pages`, the `else` branch writes **raw KB wikitext** as the
  proposal (event `no_live_copy`). Its `.diff` is "everything added".
- Stage 4 uploads `update` titles with a non-empty diff, using `action=edit`
  with the **full text**, which replaces the live page, infobox, images and
  hand-written prose included.
- The same happens for a single page that read_many didn't return. For
  example, a page renamed or deleted on the wiki between stage 1 and stage 3
  is still planned as `update`.

**B. Overview page against an empty live copy.**
- `build_overview_proposal` (~lines 245-275) uses
  `live = live_pages.get(title, "")` and merges against `""`, which produces
  a KI-region-only page.
- `04_upload._update_titles` always adds `STORY_OVERVIEW_PAGE`, so stage 4
  overwrites the whole live "Stream Folgen" page whenever stage 3 couldn't
  read it.

## Fix (fail closed)

### 1. `main()` in `03_generate.py`

If reading live pages fails, **abort stage 3** with a clear message, and
don't write or prune anything. A partial proposal set is worse than none,
because stage 4 can't tell which files are trustworthy.

```python
        try:
            live_pages = WikiClient().read_many(titles)
        except requests.RequestException as exc:
            runlog.log(
                _STAGE, "abort", level="error", reason="wiki_unreachable",
                detail=str(exc), remaining=len(titles),
                echo=f"Wiki unreachable ({exc}) — no proposals written. "
                     "Stage 3 needs the live pages to merge into; re-run when the wiki answers.",
            )
            raise SystemExit(2) from exc
```

### 2. `generate_proposals`: no raw fallback for `update`

Replace the `else` branch (the `no_live_copy` raw-KB fallback) with
**skip and warn**:

```python
            else:
                # Fail closed: an update page we could not read must not get a
                # proposal at all. Stage 4 uploads full text with action=edit, so
                # a raw-KB "proposal" here would replace the live page --
                # infobox, images and hand-written prose included.
                if events is not None:
                    events.append({
                        "event": "skip_no_live_copy", "level": "warn",
                        "title": entity["wiki_title"],
                        "note": "update page not readable live — no proposal written",
                    })
                continue
```

The `continue` must skip writing both `.wikitext` and `.diff` for that
entity. Check the loop structure, since outputs are assigned after the
if/else, and restructure minimally so nothing is written.

### 3. `build_overview_proposal`: require a live copy

```python
    if title not in live_pages:
        # Fail closed (E1): stage 4 always treats the overview as an update,
        # so merging against "" would replace the live page with the table.
        if events is not None:
            events.append({"event": "skip_overview_no_live_copy", "level": "warn", "title": title})
        return {}
```

Delete the `overview_new` branch and its event. Creating the page is a
human action (see `NEW_PAGES.md` and the "agent never creates" rule).

### 4. Stage 4 second line of defence (`04_upload.py`)

In the upload loop, for an `update` title, **skip** when there is no
`.diff` file at all, and log `reason="no_diff"`.

- Today a missing `.diff` "still uploads". That made sense for hand-dropped
  files, but every proposal stage 3 writes for an update now has a `.diff`,
  so a missing one is suspect.
- Update the comment and the existing test
  `test_upload_skips_pages_with_an_empty_diff`: "Hartwacht" (no `.diff`) is
  now **skipped** with reason `no_diff`.
- Also update the CLAUDE.md paragraph ("A *missing* `.diff` still uploads")
  to match.

### 5. Tests (`test_export.py`)

1. `generate_proposals` with an `update` entity absent from `live_pages`:
   no `.wikitext` or `.diff` for it, and a `skip_no_live_copy` event.
2. `build_overview_proposal(plan, {}, events)` returns `{}` with a
   `skip_overview_no_live_copy` event. **Rewrite**
   `test_overview_proposal_creates_the_page_when_it_is_missing`, which
   asserts the old behaviour. Rename it to
   `test_overview_proposal_needs_a_live_copy`.
3. `main()` with `WikiClient.read_many` monkeypatched to raise
   `requests.ConnectionError`:
   - `SystemExit(2)`;
   - `proposals/` untouched: pre-create a sentinel file and assert it
     survives (no prune).
   - Monkeypatch `cached_bodies`, `load_plan` and `config.PROPOSALS_DIR` to a
     tmp dir.
4. Stage 4: an update with no `.diff` is skipped with `no_diff`.

### 6. Verify, commit, PR

```bash
fandom_env/Scripts/python.exe -m pytest -q && ruff check .   # if ruff installed; else skip
```

Message: `fix(generate): fail closed when live pages can't be read`

## Done when

- [ ] No code path writes a proposal for an `update` page without its live text.
- [ ] Stage 3 aborts without writing when the wiki is unreachable.
- [ ] Tests 1–4 green; CLAUDE.md wording updated.
