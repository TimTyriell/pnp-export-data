# E3 — Stage 5 reports the right run, in fewer round trips

| | |
|---|---|
| Branch | `fix/report-telemetry` |
| Depends on | — (rebase on E2 if E2 merged first; it touches `EDIT_SUMMARY`) |
| Size | S |

## Problems (`05_report.py`)

1. `_last_run_counts` (~lines 299-320) folds the **newest log file by
   mtime**. Stage 5 writes its own log, so the newest log is always the
   report run itself. `status/history.jsonl` entries right after real uploads
   (2026-08-09 16:51:47 and 21:13:36) recorded `uploaded=0`, and `ok`/`error`
   only reflect stage 5.
2. `collect()` reads every page with `client.read(title)`, one request per
   page, although `WikiClient.read_many` batches 50 per request.
3. `latest_anomalies()` calls `json.loads` on every line with no guard. One
   truncated log line (a killed run) crashes the report.

## Steps

1. `_last_run_counts` → `_last_pipeline_counts`:
   - walk `run_logs_newest_first()`;
   - skip any log whose records all have `stage == "05_report"`;
   - fold the first log that contains a `stage_end` from `04_upload` (for
     the upload counts) and, separately, the first containing `stage_end`
     from `03_generate` (for warnings);
   - return
     `{"upload": {...counts, "run_id", "ts"}, "generate": {...}, "ok": bool, "error": str|None}`
     where `ok`/`error` come from **those** logs, not from stage 5's;
   - keep the old top-level keys the status schema needs. Check
     `../pnp-knowledge/docs/architecture/status-schema.md` for the dashboard
     contract, and **don't change the JSON shape the dashboard reads**. Add
     fields, never rename.
2. A tolerant line reader shared by `_last_pipeline_counts` and
   `latest_anomalies`:
   ```python
   def _records(path: str) -> list[dict]:
       out = []
       with open(path, encoding="utf-8") as fh:
           for line in fh:
               line = line.strip()
               if not line:
                   continue
               try:
                   out.append(json.loads(line))
               except json.JSONDecodeError:
                   continue  # a killed run leaves a half line; skip it, don't crash the report
       return out
   ```
3. `collect()`: replace the per-title `client.read` with one
   `client.read_many(titles)` and a lookup. A title absent from the result
   is "page missing", the same as `read()` returning `None`.
4. Tests (`test_report.py`, new, or extend `test_runlog.py` if that is where
   05 is tested today):
   - With three logs in a tmp `LOGS_DIR` (03 run, 04 run with
     `uploaded=5`, 05 run, newest last), `_last_pipeline_counts()["upload"]["uploaded"] == 5`.
     Set mtimes with `os.utime`.
   - A log with a truncated last line doesn't raise.
   - `collect` calls `read_many` once for 3 titles (fake client).
5. Verify, commit, PR: `fix(report): count the pipeline's last run, not the report's own`.

## Done when

- [ ] `status/history.jsonl` from a fresh 05 run shows the real last upload counts.
- [ ] One `read_many` call per 50 pages.
