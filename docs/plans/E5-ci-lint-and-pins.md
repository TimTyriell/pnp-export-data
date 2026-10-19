# E5 — CI lint and pinned dependencies

| | |
|---|---|
| Branch | `chore/ci-lint-and-pins` |
| Depends on | — |
| Size | S |

## Goal

1. CI runs `ruff check .`, with the version pinned like pnp-knowledge
   (`ruff==0.16.6`).
2. Requirements are pinned for reproducible installs (`requests`,
   `python-dotenv`, `pytest`).
3. The VS Code task's Windows-only interpreter path is documented, or made
   portable.

## Steps

1. Add `ruff.toml` at the repo root, mirroring pnp-knowledge's
   (`../pnp-knowledge/ruff.toml`): same rule selection, `target-version =
   "py311"`, and exclude `fandom_env`, `proposals`, `wiki_cache`, `logs`,
   `reports`, `harvest`, `status`. Run `ruff check .` and fix what it finds.
   Use `--fix` only for safe autofixes, and review the diff. If a rule fires
   more than ~20 times on deliberate style, disable that rule in
   `ruff.toml` with a comment instead.
2. `requirements-dev.txt`: add `ruff==0.16.6`.
3. Pin: produce `constraints.txt` via
   `fandom_env/Scripts/python.exe -m pip freeze`, filtered to the packages
   in the two requirements files and their dependencies. CI installs with
   `-c constraints.txt`.
4. `.github/workflows/ci.yml`:
   - add a `lint` job (setup-python from `.python-version`,
     `pip install ruff==0.16.6`, `ruff check .`);
   - in the test job, use `pip install -r requirements.txt -r requirements-dev.txt -c constraints.txt`;
   - the workflow already runs on PRs; keep it as it is.
5. `.vscode/tasks.json` uses `fandom_env\\Scripts\\python.exe`. Add an
   `"osx"`/`"linux"` override per task with `fandom_env/bin/python`. VS Code
   tasks support per-OS `command` fields. Check the file's structure first.
6. Verify locally: `ruff check .` and `pytest -q`. Push only when the human
   approves; CI must go green on the PR.

Message: `chore(ci): lint with pinned ruff and install from constraints`
