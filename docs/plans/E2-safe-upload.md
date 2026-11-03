# E2 — Upload with conflict detection, no accidental creates, honest results

| | |
|---|---|
| Branch | `fix/safe-upload` |
| Depends on | E1 |
| Size | M |

## Problems (`wiki_client.py`, `04_upload.py`)

1. **No edit-conflict detection.** `WikiClient.edit` (~lines 161-176) sends
   no `basetimestamp` or `starttimestamp`. Stage 4 uploads text merged from
   the stage-3 read. Any human edit between stage 3 and stage 4 is silently
   overwritten.
2. **Deleted pages get recreated.** No `nocreate=1`, so an update whose page
   was deleted meanwhile is created again. That breaks the "agent never
   creates" rule.
3. **Failures counted as success.** `04_upload.py:157` checks only for an
   `"error"` key. A response with `edit.result != "Success"` (e.g. a
   captcha or abuse-filter `"Failure"`) is counted as uploaded.
4. **Transport.** `_get`/`_post` have no timeout, no HTTP status check and
   no retry, and call `.json()` blindly.
5. The edit summary literal is duplicated: `04_upload.py:153` and
   `05_report.py:43` (whose comment says they must match).

## Steps

### 1. `config.py`

```python
# Every edit this pipeline makes carries this summary; 05_report.py separates
# the bot's edits from human edits of the same account by it. One constant so
# the two stages cannot drift.
EDIT_SUMMARY = "pnp-fandom-service update"

HTTP_TIMEOUT_S = float(os.environ.get("FANDOM_HTTP_TIMEOUT_S", "30"))
```

Use `config.EDIT_SUMMARY` in `04_upload.py` and `05_report.py`, and delete
`05_report.EDIT_SUMMARY`. If tests reference `report.EDIT_SUMMARY`, point
them at `config`.

### 2. Transport in `wiki_client.py`

```python
    def _request(self, method: str, **params) -> dict:
        params["format"] = "json"
        kw = {"params": params} if method == "GET" else {"data": params}
        for attempt in range(3):
            resp = self.session.request(method, self.url, timeout=config.HTTP_TIMEOUT_S, **kw)
            if resp.status_code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("error", {}).get("code") == "ratelimited" and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return data
        return data

    def _get(self, **params) -> dict:
        return self._request("GET", **params)

    def _post(self, **params) -> dict:
        return self._request("POST", **params)
```

- `raise_for_status` raises `requests.HTTPError`, a subclass of
  `RequestException`, which stage 3 (E1) already handles.
- A non-JSON body raises `requests.JSONDecodeError` (also a
  `RequestException` in requests ≥2.27). Good.
- Import `time` at the top.
- Existing tests monkeypatch `_get` directly. Keep `_get`/`_post` as thin
  wrappers so they keep working.

### 3. Revision timestamps from stage 3

Add to `WikiClient`:

```python
    def read_many_with_revs(self, titles: list[str]) -> dict[str, tuple[str, str]]:
        """``title -> (wikitext, revision timestamp)`` for pages that exist (batches of 50)."""
```

Copy `read_many`, with `rvprop="content|timestamp"`, returning
`(text, rev["timestamp"])`. Re-implement `read_many` as
`{t: text for t, (text, _ts) in self.read_many_with_revs(titles).items()}`
so there is one code path. The existing
`test_read_many_batches_and_keeps_empty_pages` must still pass. Extend its
fake to include `timestamp` in the revision dict.

In `03_generate.main()`, call `read_many_with_revs`, derive `live_pages`
from it, and for every written `update` proposal (and the overview), write
a sidecar `proposals/<stem>.base.json`:

```json
{"title": "Die Hexe", "basetimestamp": "2026-08-10T20:27:11Z", "live_sha8": "<runlog.sha8(live)>"}
```

`generate_proposals` stays pure: return the base data in `outputs` as an
extra file, `f"{safe_title}.base.json"`, built from a new optional argument
`live_revs: dict[str, str] | None`. Add `".json"` to `_OURS` (`03_generate.py:121`),
so `prune_proposals` cleans stale sidecars. `NEW_PAGES.md` is handled
separately and is unaffected.

### 4. `WikiClient.edit` signature

```python
    def edit(self, title: str, text: str, summary: str, *,
             basetimestamp: str | None = None, nocreate: bool = True) -> dict:
```

- Add `"nocreate": 1` to the payload when `nocreate`.
- Add `"basetimestamp": basetimestamp` and `"starttimestamp": basetimestamp`
  when given. `starttimestamp` makes MediaWiki also report "page deleted
  since you started".
- The DRY_RUN path returns the payload as before, including the new keys.

### 5. `04_upload.py`

- For each proposal, read the sidecar `path.with_suffix("").with_suffix(".base.json")`.
  Careful: `Path("Die Hexe.wikitext").with_suffix(".base.json")` →
  `Die Hexe.base.json`; check this with a test.
- **No sidecar for an update → skip** with `reason="no_base"` (stage 3
  always writes one now).
- `create` (only with `--create`): `nocreate=False`, no basetimestamp.
- `update`: `client.edit(title, text, config.EDIT_SUMMARY, basetimestamp=..., nocreate=True)`.
- Result handling:
  ```python
  edit = result.get("edit") or {}
  if "error" in result:
      code = result["error"].get("code", "?")      # editconflict, missingtitle, ratelimited...
      ...failure...
  elif edit.get("result") != "Success":
      ...failure with code=edit.get("result", "?"), info=json.dumps(edit)[:300]...
  else:
      ...uploaded; record edit.get("newrevid"), and "nochange" in edit...
  ```
- Add a failure hint: `editconflict` → "page changed since stage 3 — re-run
  01→03 and review the new diff"; `missingtitle` → "page was deleted on the
  wiki — not recreated".

### 6. Tests (`test_export.py`)

1. `edit()` payload under DRY_RUN contains `nocreate: 1` and
   `basetimestamp` when given.
2. Upload loop with a fake client whose `edit` returns
   `{"edit": {"result": "Failure", "captcha": {...}}}` → counted as failed,
   not uploaded.
3. `{"error": {"code": "editconflict"}}` → failed, with the hint printed.
4. An update without `.base.json` → skipped `no_base`.
5. `generate_proposals(..., live_revs={"Die Hexe": "2026-01-01T00:00:00Z"})`
   writes `Die Hexe.base.json` with that timestamp and the live sha8.
6. `_request` retries a 503 then succeeds. Fake `session.request` returns
   objects with `.status_code`, `.raise_for_status()` and `.json()`.
   Monkeypatch `time.sleep` to a no-op.
7. `EDIT_SUMMARY` is identical in the 04 and 05 usage (import `config`;
   assert 05 uses `config.EDIT_SUMMARY` by grepping the source, or by a
   behaviour test of `ki_edits`).

### 7. Verify, commit, PR

```bash
fandom_env/Scripts/python.exe -m pytest -q
```

Message: `fix(upload): detect edit conflicts, never recreate, count real failures`

The PR body describes the new upload contract in 5 lines; also update
CLAUDE.md's "review gate" section.

## Done when

- [ ] Every update edit carries `basetimestamp` + `nocreate`.
- [ ] No `Failure` result is counted as an upload.
- [ ] Transport has a timeout and retries 429/5xx.
- [ ] One `EDIT_SUMMARY` constant.
