"""Self-check for guard.ps1: every rule blocks, every override and neighbour passes.

    python .claude/hooks/test_guard.py

Copies the guard into a throwaway git repo (on main) so the checks never touch
this checkout. Needs powershell (Windows) or pwsh. Not in CI.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The human's own overrides must not leak into the expectations.
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("PNP_ALLOW_")}
SHELL = shutil.which("powershell") or shutil.which("pwsh")


def run(repo: Path, tool: str, tool_input: dict, **env: str) -> int:
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(repo)})
    return subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(repo / ".claude/hooks/guard.ps1")],
        input=payload, capture_output=True, text=True, env={**CLEAN_ENV, **env},
    ).returncode


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / ".claude/hooks").mkdir(parents=True)
        shutil.copy(HERE / "guard.ps1", repo / ".claude/hooks/guard.ps1")
        git = ["git", "-C", str(repo)]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)

        edit = lambda path: {"file_path": str(repo / path), "old_string": "y", "new_string": "x"}  # noqa: E731
        write = lambda path: {"file_path": str(repo / path), "content": "{}"}  # noqa: E731
        bash = lambda cmd: {"command": cmd}  # noqa: E731
        cases = [
            # (expected exit, tool, input, env)
            (2, "Write", write(".claude/guards.env"), {}),
            (2, "Bash", bash("echo PNP_ALLOW_MAIN_COMMIT=1 >> .claude/guards.env"), {}),
            (2, "PowerShell", bash("Set-Content .claude/guards.env 'PNP_ALLOW_MAIN_COMMIT=1'"), {}),
            (0, "Bash", bash("cat .claude/guards.env"), {}),
            (2, "Bash", bash("python3.11 04_upload.py --apply"), {}),
            (2, "Bash", bash("py 04_upload.py --apply"), {}),
            (2, "Bash", bash('nohup bash -c "python 04_upload.py --apply"'), {}),
            (0, "Bash", bash("grep -n -- --apply 04_upload.py"), {}),
            (2, "Edit", edit(".claude/hooks/guard.ps1"), {}),
            (2, "Write", write(".claude/settings.json"), {}),
            (0, "Write", write(".claude/settings.json"), {"PNP_ALLOW_GUARD_EDIT": "1"}),
            (0, "Edit", edit(".claude/agents/verifier.md"), {}),
            (2, "Bash", bash("python 04_upload.py --apply"), {}),
            (2, "Bash", bash("FANDOM_DRY_RUN=0 fandom_env/Scripts/python.exe 04_upload.py --apply --only X"), {}),
            (2, "PowerShell", bash(r"$env:FANDOM_DRY_RUN='0'; python .\04_upload.py --apply"), {}),
            (0, "Bash", bash("python 04_upload.py"), {}),
            (0, "Bash", bash("python 04_upload.py --apply"), {"PNP_ALLOW_WIKI_WRITE": "1"}),
            (0, "Bash", bash("python 03_generate.py --apply-merge"), {}),
            (0, "Bash", bash('git commit -m "04_upload.py --apply is gated"'), {"PNP_ALLOW_MAIN_COMMIT": "1"}),
            (2, "Bash", bash('git commit -m "x"'), {}),
            (0, "Bash", bash('git commit -m "x"'), {"PNP_ALLOW_MAIN_COMMIT": "1"}),
            (0, "Bash", bash("git status"), {}),
            (0, "Bash", bash(""), {}),
        ]
        failures = [
            f"expected {want}, got {got}: {tool} {inp} {env}"
            for want, tool, inp, env in cases
            if (got := run(repo, tool, inp, **env)) != want
        ]
        (repo / ".claude/guards.env").write_text("PNP_ALLOW_MAIN_COMMIT=1\nPNP_ALLOW_GUARD_EDIT=0\n")
        if run(repo, "Bash", bash('git commit -m "x"')) != 0:
            failures.append("PNP_ALLOW_MAIN_COMMIT=1 in guards.env did not allow the commit")
        if run(repo, "Write", write(".claude/guards.env")) != 2:
            failures.append("guards.env with GUARD_EDIT=0 did not protect itself")
        (repo / ".claude/guards.env").unlink()
        subprocess.run([*git, "switch", "-q", "-c", "feat/x"], check=True)
        if run(repo, "Bash", bash('git commit -m "x"')) != 0:
            failures.append("commit on a branch was blocked")
        assert not failures, "\n".join(failures)
        print(f"guard.ps1: {len(cases) + 3} checks passed")


if __name__ == "__main__":
    main()
