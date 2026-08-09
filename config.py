"""Single source of truth for all tunables of the pnp-fandom-service.

Mirrors the pattern used by the sibling project pnp-crawl: scripts import
values from here directly instead of taking CLI flags for them. When asked to
change behaviour, edit this file — not the stage scripts — unless the change is
structural.

Secrets / instance-specific values come from a .env file (via python-dotenv,
optional) and fall back to shell environment variables. Never hardcode the bot
password into this file or commit it.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # optional dependency, same approach as pnp-crawl
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # fall back to plain environment variables
    pass


# --- Wiki / MediaWiki API -------------------------------------------------

# Base API endpoint of your Fandom wiki, e.g. https://meinwiki.fandom.com/api.php
WIKI_API_URL = os.environ.get("WIKI_API_URL", "https://DEINWIKI.fandom.com/api.php")

# Bot credentials. Create a bot password under Special:BotPasswords on the wiki.
# Keep these in .env, never in this file.
WIKI_USERNAME = os.environ.get("WIKI_USERNAME", "")
WIKI_BOT_PASSWORD = os.environ.get("WIKI_BOT_PASSWORD", "")

# Polite User-Agent is required by Fandom/Wikimedia API policy.
WIKI_USER_AGENT = os.environ.get(
    "WIKI_USER_AGENT", "pnp-fandom-service/0.1 (contact: noahstreppel@gmail.com)"
)

# Namespace to write generated pages into during review (0 = main/live,
# 2 = User:, "Draft" if your wiki has a Draft namespace). The review-gate
# workflow promotes from a draft/sandbox namespace to live only after approval.
DRAFT_NAMESPACE = os.environ.get("WIKI_DRAFT_NAMESPACE", "User")


# --- Knowledge-Base API (the "memory" repo, pnp-knowledge) -----------------

# Read-only KB API over the OKF bundle. Start it in the memory repo:
#   cd ../pnp-knowledge/services/kb && python -m pnp_okf.api
KB_URL = os.environ.get("PNP_KB_URL", "http://127.0.0.1:8070")

# Concept types exported as wiki pages. Sessions stay KB-internal by default.
EXPORT_TYPES = [
    "Character",
    "NPC",
    "Location",
    "Faction",
    "Item",
    "Event",
    "Deity",
    "Domain",
]

# Relevance gate (CHRONIST.md §5): a concept only earns a wiki page if it shows
# up across at least this many distinct sessions. The KB tracks *everything*;
# the wiki is a reference work, and 900 one-mention stubs nobody maintains are
# worse than 100 good pages. Counted from the "Session <date>" citations in the
# concept body (see 02_extract.py). Pages that already exist live are never
# filtered — a human created them, that decision beats the threshold. Set to 1
# to export every concept again.
MIN_SESSIONS = 2

# How similar a live section must be to what the KB renders today before the
# merge reclaims it into the KI region (see wikimerge.py). Pages synced before
# the region existed carry KB text inline; it has since drifted (the KB was
# regenerated, citation numbering was corrected), so byte-identity finds
# nothing. 0.8 catches those while leaving genuinely rewritten sections outside,
# where they stay untouched. Lower = reclaims more aggressively.
#
# **Migration-only.** It is consulted for a page whose KI region is `absent`.
# Once a page has been synced with markers its state is `clean` or `edited`
# forever after, and this value is never read for it again. Override per run
# for a stubborn page: PNP_RECLAIM_SIMILARITY=0.45 python 03_generate.py
RECLAIM_SIMILARITY = float(os.environ.get("PNP_RECLAIM_SIMILARITY", "0.8"))

# German category name per concept type, appended as [[Kategorie:...]].
CATEGORY_BY_TYPE = {
    "Character": "Charaktere",
    "NPC": "NPCs",
    "Location": "Orte",
    "Faction": "Fraktionen",
    "Item": "Gegenstände",
    "Event": "Ereignisse",
    "Deity": "Gottheiten",
    "Domain": "Domänen",
}


# --- LLM (local via Ollama) ----------------------------------------------

# ponytail: unused since stages 2/3 went deterministic (KB bodies are already
# synthesized German markdown). Kept for a later prose-polish pass, if ever.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

# Campaign content is German (see pnp-crawl). Generate Wikitext in German.
LANGUAGE = "de"


# --- Directories ----------------------------------------------------------

ROOT = Path(__file__).resolve().parent

# LLM-generated session reports, the input to this service. Produced upstream by
# pnp-crawl's (planned) stage-4 report generator. Drop the .md/.json files here.
REPORTS_DIR = ROOT / "reports"

# Cached snapshot of the wiki: page index, categories, extracted entities.
# Stage 1 (inventory) writes here; later stages read it. Gitignored.
WIKI_CACHE_DIR = ROOT / "wiki_cache"

# Generated Wikitext awaiting review (the dry-run output). Stage 3 writes a
# proposed/ diff here; nothing is uploaded until approved. Gitignored.
PROPOSALS_DIR = ROOT / "proposals"

# Human prose harvested from the KI region of a live wiki page (see
# wikimerge.py). This service stays a read-only client of the KB — it never
# writes into ../pnp-knowledge. Harvested text lands here for a human to move
# into knowledge/sources/ via the usual ingest branch + PR, after which the KB
# absorbs it and the region is regenerated including it. Gitignored.
HARVEST_DIR = ROOT / "harvest"

# One JSONL event log per run (see runlog.py). proposals/ is flat and mixes
# runs, so the log is the only record of which run wrote which file — and of
# the merge decisions behind it. Gitignored.
LOGS_DIR = ROOT / "logs"

# Machine-readable status snapshot for the pnp-dashboard service (see
# ../pnp-knowledge/docs/architecture/status-schema.md). Written by
# 05_report.py alongside the human-readable reports. Gitignored.
STATUS_DIR = ROOT / "status"


# --- Review gate ----------------------------------------------------------

# When True (default), stage 4 (upload) refuses to write to the wiki and only
# prints/serializes the diff. Set to False (or pass --apply) to actually upload.
DRY_RUN = os.environ.get("FANDOM_DRY_RUN", "1") not in ("0", "false", "False")

# Seconds to wait between consecutive edits. Fandom rate-limits bulk writes —
# a full sync without a gap trips "ratelimited" part way through and silently
# loses the rest of the batch. Uploads are idempotent, so a tripped run is
# recoverable by re-running, but pacing avoids the round trip.
EDIT_DELAY_S = float(os.environ.get("FANDOM_EDIT_DELAY_S", "3"))
