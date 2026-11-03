# Review policy — pnp-export-data

Read by `/review-pr` (`.claude/commands/review-pr.md`) and by human reviewers.
Hooks already block an agent running the upload (`.claude/hooks/guard.ps1`);
review catches the code changes that would weaken it. Ruff and CI catch style
and broken tests: don't repeat them.

## Always report

1. **The review gate.** `config.DRY_RUN` defaulting to False, `--apply`
   hardcoded or implied, a write path that skips `wiki_client`'s dry-run
   handling, or a direct POST. CLAUDE.md "The review gate".
2. **Overwriting human edits.** Stage 4 must send `basetimestamp` /
   `starttimestamp` and `nocreate=1` from the `<stem>.base.json` sidecar; an
   update without one is skipped. Anything that can overwrite a hand-written
   page after a wiki outage or a stale index (plans E1, E2).
3. **Creating pages.** The agent never creates pages; `create` proposals go to
   `proposals/NEW_PAGES.md` for a human.
4. **The KB boundary.** This repo is a pure client of the KB API. Reading
   `pnp-knowledge/knowledge/` files directly, or adding knowledge here, breaks
   the three-repo split. A wiki-only merge belongs in `wiki_pages.toml`, never
   in the bundle.
5. **Honest results.** An API `{"error": ...}` body or `edit.result != "Success"`
   counted as an upload; run log or report claiming more than happened.
6. **Determinism.** `md2wiki.py` output must be stable for the same input; a
   change that reorders or reflows unchanged pages makes every diff noisy.
7. **Guards.** Changes to `.claude/hooks/` or `.claude/settings.json` that
   remove or loosen a rule.
8. **Tests.** New behaviour without an offline test; a bug fix without a test
   that failed before it.

## Skip

Formatting and import order (ruff), naming taste, refactors the PR didn't
attempt. At most 3 nits, after everything else. Wikitext stays German; docs
English.

## Output

One review comment. Findings most severe first, one per line:
`path:line — problem — fix`. No praise, no summary of the diff. Last line:
`Merge: yes` / `Merge: after fixes` / `Merge: no`, and why in one clause.
The human merges.
