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

import config
from wiki_client import WikiClient


def _update_titles() -> set[str] | None:
    """Wiki titles the plan marked ``update``; None if the plan is missing."""

    plan_path = config.WIKI_CACHE_DIR / "entities.json"
    if not plan_path.exists():
        return None
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    return {e["wiki_title"] for e in plan if e.get("action") == "update"}


def main(apply: bool) -> None:
    if not config.PROPOSALS_DIR.exists():
        print("No proposals/ directory — run stage 3 first.")
        return

    proposals = sorted(config.PROPOSALS_DIR.glob("*.wikitext"))
    if not proposals:
        print("No reviewed proposals to upload.")
        return

    updates = _update_titles()
    if updates is None:
        print(
            "wiki_cache/entities.json missing — cannot tell updates from new "
            "pages. Run 02_extract.py first (the agent never creates pages)."
        )
        return

    client = WikiClient()
    do_apply = apply and not config.DRY_RUN
    if do_apply:
        client.login()

    uploaded = skipped_new = 0
    for path in proposals:
        title = path.stem
        if title not in updates:
            skipped_new += 1  # a proposed *new* page — humans create these
            continue
        text = path.read_text(encoding="utf-8")
        if do_apply:
            result = client.edit(title, text, summary="pnp-fandom-service update")
            print(f"Uploaded {title}: {result.get('edit', result)}")
        else:
            print(f"[dry-run] would update {title} ({len(text)} chars)")
        uploaded += 1

    print(
        f"\n{uploaded} update(s) {'uploaded' if do_apply else 'planned'}; "
        f"{skipped_new} new-page proposal(s) skipped (see NEW_PAGES.md — "
        "create those manually)."
    )
    if not do_apply:
        print(
            "Review gate active. Re-run with --apply and FANDOM_DRY_RUN=0 to "
            "upload updates."
        )


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
