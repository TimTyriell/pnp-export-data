# E4 — Small correctness fixes

| | |
|---|---|
| Branch | `fix/small-correctness` |
| Depends on | — |
| Size | S–M (six independent items; one commit each) |

## 1. Escape wiki table cells in the episode overview

`03_generate.render_story_overview` (~lines 200-236) interpolates
`description`, `resource` and the season `label` raw.

- A `|` in a KB description splits the table cell.
- A newline ends the row.
- `||` or `!!` at a line start break the markup.

Add:

```python
def _cell(text: str) -> str:
    """Text safe inside a wikitable cell: no pipes, no line breaks."""
    return " ".join((text or "").split()).replace("|", "&#124;")
```

Apply it to the description, the resource, the label in the `<span>`, and
`name` inside `[[title|name]]`. Test: a description with `"a | b\nc"`
renders as one cell, `a &#124; b c`.

## 2. NEW_PAGES.md filename

`03_generate.py:435` builds the filename with
`e['wiki_title'].replace('/', '_')`. Every other path uses
`md2wiki.proposal_filename`, which also replaces `<>:"\|?*`. Use
`proposal_filename(e['wiki_title'])`. Test with a title containing `?`.

## 3. Skipped counter in stage 2

`02_extract.py:275`: `skipped = len(concepts) - len(plan)` counts concepts
folded into a page by `wiki_pages.toml` (subs, equal-weight leads) as
"skipped". Compute three numbers instead:

- `grouped` = members folded into another page (from `pagemap.group`'s
  output, or `len(members) - 1` per page);
- `gated` = dropped by `MIN_SESSIONS`;
- `excluded` = explicit excludes.

Log all three in `stage_end`. Keep `skipped = gated + excluded` for
compatibility. Read `plan_entities` to see where each drop happens. Test
with the existing planning fixtures.

## 4. Validate the KB response shape at the boundary

`02_extract.py:106-108` reads `payload["frontmatter"]` and
`payload.get("body_md")`. `03_generate.fetch_body` reads
`resp.json()["body_md"]`, so a missing key raises a bare `KeyError`.

Add one function in `02_extract.py` and use it from both stages:

```python
def concept_payload(resp_json: dict, concept: str) -> tuple[dict, str]:
    """(frontmatter, body_md) from GET /concepts/{id}, or SystemExit naming the field.

    The KB API is a separate service in a separate repo; a shape change there
    should stop this pipeline with a message, not a KeyError three stages later.
    """
    fm = resp_json.get("frontmatter")
    body = resp_json.get("body_md")
    if not isinstance(fm, dict) or not isinstance(body, str):
        raise SystemExit(f"KB API returned an unexpected shape for {concept}: keys={sorted(resp_json)}")
    return fm, body
```

Also guard the session-count regex dependency. After stage 2 builds the
plan:

- if **zero** non-Session concepts have `sessions >= 1`, abort with a
  message naming `_SESSION_CITE_RE` and the KB's citation format;
- otherwise a KB-side format change silently gates out every concept.

Test both.

## 5. Personal email in the default User-Agent

`config.py:38` defaults `WIKI_USER_AGENT` to a string containing a personal
email, and it is committed.

- Change the default to `"pnp-fandom-service/0.1 (set WIKI_USER_AGENT in .env)"`.
- Add `WIKI_USER_AGENT=pnp-fandom-service/0.1 (contact: <you>)` to
  `.env.example`. Create the file if it doesn't exist; check `ls -a`.
- Also validate that `WIKI_API_URL` isn't the `DEINWIKI` placeholder:
  `WikiClient.__init__` raises `SystemExit("Set WIKI_API_URL in .env")`
  when `"DEINWIKI" in config.WIKI_API_URL`.
- Tests construct `WikiClient()`, so monkeypatch `config.WIKI_API_URL` in a
  conftest fixture (or set it in `test_export.py` before construction) to
  `https://example.invalid/api.php`.

The email stays in git history. Tell the human in the PR; rewriting history
is their call.

## 6. wikimerge: orphan start marker and second region

`wikimerge.split_ki_region` (~lines 105-120): a start marker without an end
marker returns `None`. The state becomes `absent`, and the merge appends a
**second** region beside the orphan marker.

Fix:
- a start without an end → treat the page as `edited` (hands off) and emit
  an anomaly `ki_marker_broken`;
- more than one start marker → also `edited` with an anomaly
  `ki_region_duplicated`.

A human must repair the page; the harvest path already handles `edited`.

Tests (`test_wikimerge.py`):
- a page with `<!-- KI-Abschnitt: ... -->` and no end → state `edited`,
  output == input;
- two complete regions → `edited`.

Check how `detect_anomalies` in `03_generate.py` receives decisions, and add
the anomaly through the same path.

## Verify, commit, PR

```bash
fandom_env/Scripts/python.exe -m pytest -q
```

One PR, six commits:
1. `fix(generate): escape overview table cells`
2. `fix(generate): sanitise NEW_PAGES file names like every other proposal`
3. `fix(extract): count grouped vs gated concepts separately`
4. `fix(extract): validate KB responses at the boundary`
5. `chore(config): no personal email in defaults; refuse the placeholder wiki`
6. `fix(merge): treat broken or doubled KI markers as hands-off`
