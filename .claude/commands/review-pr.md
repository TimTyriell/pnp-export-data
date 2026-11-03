---
description: Review a PR against REVIEW.md and post one review comment
argument-hint: <pr-number>
allowed-tools: Read, Grep, Glob, Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr review:*), Bash(git log:*), Bash(git show:*)
---

Review pull request #$ARGUMENTS of this repo. You are the reviewer, not the
author: if this session wrote the change, say so in the comment's first line.
For a clean context run it headless instead: `claude -p "/review-pr <n>"`.

1. Read `REVIEW.md` (the policy) and `CLAUDE.md`.
2. `gh pr view $ARGUMENTS` and `gh pr diff $ARGUMENTS`. If the PR names a plan
   in `docs/plans/`, read it and judge the diff against its *Intent* and
   *Done when*, not just against itself.
3. Before reporting a finding, read the surrounding code and confirm it. Drop
   anything you can't anchor to a line in the diff.
4. Post exactly one comment, formatted per REVIEW.md "Output":
   `gh pr review $ARGUMENTS --comment --body-file -` with the body on stdin.
   Never `--approve` or `--request-changes`: merging is the human's call.
