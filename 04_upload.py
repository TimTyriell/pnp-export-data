"""Stage 4 — Upload: push approved proposals to the wiki (gated).

Reads the reviewed .wikitext files from config.PROPOSALS_DIR and edits the
corresponding wiki pages via the MediaWiki API. This is the only stage that
writes to the wiki, and it refuses to do so unless the review gate is cleared:

  * config.DRY_RUN must be False (env FANDOM_DRY_RUN=0), or pass --apply.
  * Without that, it prints what *would* be uploaded and exits.

Two hard rules enforced here (see CLAUDE.md "The review gate"):

  * **The agent never creates pages.** Only proposals the stage-2 plan marked
    ``update`` (i.e. the page already exists on the wiki) are uploaded.
    ``create`` proposals are skipped — a human initializes those pages
    manually from proposals/NEW_PAGES.md, and the next sync fills them via
    the update path.
  * Uploads target the page title as-is (an existing page). The
    draft-namespace promotion flow (config.DRAFT_NAMESPACE) is a separate,
    not-yet-wired step; don't route creates through here to fake it.

Run:  python 04_upload.py            # dry-run, prints planned edits
      python 04_upload.py --apply    # actually uploads updates (needs bot login)
"""

from __future__ import annotations

import json
import sys
import time

import config
import runlog
from md2wiki import proposal_filename
from wiki_client import WikiClient

_STAGE = "04_upload"


def _load_plan() -> list[dict] | None:
    plan_path = config.WIKI_CACHE_DIR / "entities.json"
    if not plan_path.exists():
        return None
    return json.loads(plan_path.read_text(encoding="utf-8"))


def _titles_by_stem(plan: list[dict]) -> dict[str, str]:
    """``proposals/`` stem -> the real wiki title.

    A filename cannot hold every character a wiki title can ("/" makes a
    subpage on the wiki but is a path separator here), so the stem is a lossy
    form. Taking the title from it uploaded "Katze (Ajani / Günther)" as
    "Katze (Ajani _ Günther)", which the wiki then stored with a space. The
    plan is where the title actually lives.
    """

    return {proposal_filename(e["wiki_title"]): e["wiki_title"] for e in plan}


def _update_titles(plan: list[dict]) -> set[str]:
    """Wiki titles the plan marked ``update``."""

    titles = {e["wiki_title"] for e in plan if e.get("action") == "update"}
    # Not a concept, so never in the plan — but it is an existing page that
    # stage 3 merged, and it must go up the same way (see render_story_overview).
    if config.STORY_OVERVIEW_PAGE:
        titles.add(config.STORY_OVERVIEW_PAGE)
    return titles


def main(apply: bool, create: bool = False, only: str | None = None) -> None:
    """Upload reviewed proposals.

    *create* also writes proposals for pages that do not exist yet. Off by
    default and deliberately a separate flag from ``--apply``: creating a page
    is not reviewable as a diff (there is nothing to diff against), so it is
    a decision a human makes per batch. MediaWiki's ``action=edit`` creates a
    missing page with the same call, so there is no second code path.

    *only* restricts the run to titles containing that substring — how a big
    batch gets rolled out: one page live, look at it, then the rest.
    """

    runlog.log(
        _STAGE, "stage_start", apply=apply, create=create, dry_run=config.DRY_RUN
    )
    if not config.PROPOSALS_DIR.exists():
        runlog.log(
            _STAGE, "abort", level="warn", reason="no_proposals_dir",
            echo="No proposals/ directory — run stage 3 first.",
        )
        return

    proposals = sorted(config.PROPOSALS_DIR.glob("*.wikitext"))
    if only:
        proposals = [p for p in proposals if only.lower() in p.stem.lower()]
        runlog.log(_STAGE, "filter", only=only, matched=len(proposals),
                   echo=f"--only {only!r}: {len(proposals)} proposal(s)")
    if not proposals:
        runlog.log(
            _STAGE, "abort", level="warn", reason="no_proposals",
            echo="No reviewed proposals to upload.",
        )
        return

    plan = _load_plan()
    if plan is None:
        runlog.log(
            _STAGE, "abort", level="warn", reason="no_plan",
            echo="wiki_cache/entities.json missing — cannot tell updates from "
                 "new pages. Run 02_extract.py first (the agent never creates "
                 "pages).",
        )
        return
    updates = _update_titles(plan)
    title_by_stem = _titles_by_stem(plan)

    client = WikiClient()
    do_apply = apply and not config.DRY_RUN
    if do_apply:
        client.login()

    uploaded = skipped_new = unchanged = 0
    failures: list[tuple[str, str]] = []
    for path in proposals:
        # The stem is a lossy form of the title; the plan holds the real one.
        # Pages with no plan entry (the episode overview) keep the stem.
        title = title_by_stem.get(path.stem, path.stem)
        if title not in updates and not create:
            skipped_new += 1  # a proposed *new* page — humans create these
            runlog.log(_STAGE, "skip", title=title, reason="create")
            continue
        # An empty .diff means the merge produced the live page verbatim — the
        # edit would come back as "nochange" after a full round trip plus
        # EDIT_DELAY_S. Skip it. A *missing* .diff is not proof of anything
        # (older run, hand-dropped file), so that still uploads.
        diff_path = path.with_suffix(".diff")
        if diff_path.exists() and not diff_path.read_text(encoding="utf-8").strip():
            unchanged += 1
            runlog.log(_STAGE, "skip", title=title, reason="unchanged")
            continue
        text = path.read_text(encoding="utf-8")
        # sha8 + mtime tie this upload to the stage-3 `write` event that
        # produced the file — proposals/ keeps files from older runs.
        meta = {
            "title": title,
            "bytes": len(text),
            "sha8": runlog.sha8(text),
            "file_mtime": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(path.stat().st_mtime)
            ),
        }
        if do_apply:
            result = client.edit(title, text, summary="pnp-fandom-service update")
            # The API answers 200 with an {"error": ...} body for a refused
            # edit (rate limit, protection, bad token). Reporting that as an
            # upload loses edits silently, so inspect it.
            if "error" in result:
                err = result["error"]
                failures.append((title, err.get("info") or err.get("code", "?")))
                runlog.log(
                    _STAGE, "upload_failed", level="error", **meta,
                    code=err.get("code", "?"), info=err.get("info", ""),
                    echo=f"FAILED {title}: {err.get('code', '?')} — {err.get('info', '')}",
                )
            else:
                uploaded += 1
                runlog.log(
                    _STAGE, "upload", **meta, dry_run=False,
                    result=str(result.get("edit", result)),
                    echo=f"Uploaded {title}: {result.get('edit', result)}",
                )
            time.sleep(config.EDIT_DELAY_S)
        else:
            uploaded += 1
            runlog.log(
                _STAGE, "upload", **meta, dry_run=True,
                echo=f"[dry-run] would update {title} ({len(text)} chars)",
            )

    runlog.log(
        _STAGE, "stage_end", uploaded=uploaded, skipped_new=skipped_new,
        unchanged=unchanged, failed=len(failures), dry_run=not do_apply,
        echo=(
            f"\n{uploaded} update(s) {'uploaded' if do_apply else 'planned'}; "
            f"{unchanged} unchanged (empty diff, skipped); "
            + (
                f"{skipped_new} new-page proposal(s) skipped (see NEW_PAGES.md "
                "— create those manually, or re-run with --create)."
                if not create
                else "new pages included (--create)."
            )
        ),
    )
    if failures:
        print(f"\n{len(failures)} edit(s) FAILED and were NOT written:")
        for title, info in failures:
            print(f"  {title}: {info}")
        print(
            "Re-run to finish — edits are idempotent, pages already written "
            "come back as 'nochange'."
        )
    if not do_apply:
        print(
            "Review gate active. Re-run with --apply and FANDOM_DRY_RUN=0 to "
            "upload updates."
        )


if __name__ == "__main__":
    args = sys.argv[1:]
    only = args[args.index("--only") + 1] if "--only" in args else None
    main(apply="--apply" in args, create="--create" in args, only=only)
