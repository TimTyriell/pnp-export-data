# Implementation plans — pnp-export-data

Written 2026-10-19 from the toolchain review (workspace root `status.md`,
`toWorkOn.md`; not tracked here). One plan = one branch = one PR.

| # | Plan | Branch | Needs | Who |
|---|---|---|---|---|
| E0 | Land the open branch (below) | `chore/docs-ci-and-instrumentation` | — | human |
| E1 | [E1-fail-closed-generate.md](E1-fail-closed-generate.md) | `fix/fail-closed-generate` | E0 | agent |
| E2 | [E2-safe-upload.md](E2-safe-upload.md) | `fix/safe-upload` | E1 | agent |
| E3 | [E3-report-telemetry.md](E3-report-telemetry.md) | `fix/report-telemetry` | — | agent |
| E4 | [E4-small-correctness.md](E4-small-correctness.md) | `fix/small-correctness` | — | agent |
| E5 | [E5-ci-lint-and-pins.md](E5-ci-lint-and-pins.md) | `chore/ci-lint-and-pins` | — | agent |
| E6 | [E6-catch-up-sync.md](E6-catch-up-sync.md) | runbook | E1, E2, pnp-knowledge T1 | human |
| E7 | [E7-thread-pages.md](E7-thread-pages.md) | `feat/thread-pages` | pnp-knowledge T6 | agent + human |

**E1 and E2 come before any further live upload.** E1 fixes two data-loss
paths, where a wiki outage during stage 3 leads stage 4 to overwrite
hand-written pages. E2 closes the edit-conflict window.

## E0 — land the open branch (human)

`chore/docs-ci-and-instrumentation` is one commit ahead of `origin/main`
(`3f8dc12`, CI and docs) and has uncommitted changes:

- `README.md`: a mermaid block;
- `wiki_pages.toml`: removes `deities/ezhura`, which pnp-knowledge confirmed
  removed on 2026-09-05.

Commit them (two commits: docs, then the toml), push, and open the PR. The
`ezhura` line must stay out. The README's "Entities are not pages" example
and the `pagemap.py:26` docstring still show `ezhura`; fix both in the same
toml commit.

## Rules for the implementing agent

1. `git fetch origin && git switch -c <branch> origin/main` once E0 is
   merged. Before that, base on `chore/docs-ci-and-instrumentation` and say
   so in the PR.
2. Tests: `fandom_env/Scripts/python.exe -m pytest -q` (67 offline tests
   today). There are **no network calls in tests**: fake `WikiClient._get`,
   `_post` and `requests` as `test_export.py` does.
3. **Never run `04_upload.py --apply`** or set `FANDOM_DRY_RUN=0`. Never
   call the live wiki or the KB API from a plan step unless the step says
   HUMAN.
4. The pipeline holds no knowledge; never write into `../pnp-knowledge`.
5. German for any generated wiki text and the `NEW_PAGES.md` copy; English
   for code and comments.
6. Commits: Conventional Commits, with a body that explains why, then the
   session's attribution line.
