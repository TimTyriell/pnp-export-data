"""Thin MediaWiki Action API client shared across all stages.

Wraps login (bot password), reading pages/categories/the page index, and
editing pages. All write paths honour config.DRY_RUN: when set, edit() does not
POST to the wiki and returns the would-be payload instead, so the review-gate
stages can produce a diff without touching live content.

Docs: https://www.mediawiki.org/wiki/API:Main_page
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

import config


@dataclass
class Page:
    title: str
    wikitext: str


class WikiClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.WIKI_USER_AGENT
        self.url = config.WIKI_API_URL
        self._logged_in = False

    # --- auth -------------------------------------------------------------

    def login(self) -> None:
        """Log in with the bot account (two-step token + login dance)."""
        token = self._get(action="query", meta="tokens", type="login")[
            "query"
        ]["tokens"]["logintoken"]
        resp = self._post(
            action="login",
            lgname=config.WIKI_USERNAME,
            lgpassword=config.WIKI_BOT_PASSWORD,
            lgtoken=token,
        )
        if resp.get("login", {}).get("result") != "Success":
            raise RuntimeError(f"Wiki login failed: {resp.get('login')}")
        self._logged_in = True

    def _csrf_token(self) -> str:
        return self._get(action="query", meta="tokens")["query"]["tokens"][
            "csrftoken"
        ]

    # --- read -------------------------------------------------------------

    def all_pages(self, namespace: int = 0) -> list[str]:
        """Return every page title in a namespace (paginated via apcontinue)."""
        titles: list[str] = []
        cont: dict[str, str] = {}
        while True:
            data = self._get(
                action="query",
                list="allpages",
                aplimit="max",
                apnamespace=namespace,
                **cont,
            )
            titles += [p["title"] for p in data["query"]["allpages"]]
            if "continue" not in data:
                break
            cont = data["continue"]
        return titles

    def user_contributions(self, user: str, limit: str = "max") -> list[dict]:
        """Every edit ``user`` made: ``{title, timestamp, comment}`` (paginated).

        The wiki already tracks who touched what and when — reporting reads it
        from here instead of reconstructing it from local run logs, which only
        know about runs that happened on this machine.
        """

        edits: list[dict] = []
        cont: dict[str, str] = {}
        while True:
            data = self._get(
                action="query",
                list="usercontribs",
                ucuser=user,
                ucprop="title|timestamp|comment",
                uclimit=limit,
                **cont,
            )
            edits += data.get("query", {}).get("usercontribs", [])
            if "continue" not in data:
                break
            cont = data["continue"]
        return edits

    def last_revisions(self, titles: list[str]) -> dict[str, dict]:
        """``title -> {timestamp, user, comment}`` of the newest revision."""

        out: dict[str, dict] = {}
        for i in range(0, len(titles), 50):  # API caps titles= at 50
            data = self._get(
                action="query",
                prop="revisions",
                rvprop="timestamp|user|comment",
                titles="|".join(titles[i : i + 50]),
            )
            for page in data.get("query", {}).get("pages", {}).values():
                if "missing" in page or not page.get("revisions"):
                    continue
                out[page["title"]] = page["revisions"][0]
        return out

    def read(self, title: str) -> Page | None:
        """Fetch raw Wikitext of a page, or None if it does not exist."""
        data = self._get(
            action="query",
            prop="revisions",
            rvprop="content",
            rvslots="main",
            titles=title,
        )
        page = next(iter(data["query"]["pages"].values()))
        if "missing" in page:
            return None
        content = page["revisions"][0]["slots"]["main"]["*"]
        return Page(title=title, wikitext=content)

    def read_many(self, titles: list[str]) -> dict[str, str]:
        """``title -> wikitext`` for the pages that exist, in batches of 50.

        Same batching the API allows for ``last_revisions`` — one page per
        request is ~40 round trips per sync for no reason. Missing pages are
        absent from the result; an existing but *empty* page maps to ``""``,
        which callers must distinguish (membership, not truthiness).
        """

        return {t: text for t, (text, _ts) in self.read_many_with_revs(titles).items()}

    def read_many_with_revs(self, titles: list[str]) -> dict[str, tuple[str, str]]:
        """``title -> (wikitext, revision timestamp)`` for pages that exist (batches of 50)."""

        out: dict[str, tuple[str, str]] = {}
        for i in range(0, len(titles), 50):  # API caps titles= at 50
            data = self._get(
                action="query",
                prop="revisions",
                rvprop="content|timestamp",
                rvslots="main",
                titles="|".join(titles[i : i + 50]),
            )
            for page in data.get("query", {}).get("pages", {}).values():
                if "missing" in page:
                    continue
                revs = page.get("revisions")
                if revs:
                    text = revs[0]["slots"]["main"].get("*", "")
                    out[page["title"]] = (text, revs[0]["timestamp"])
                else:
                    out[page["title"]] = ("", "")
        return out

    # --- write ------------------------------------------------------------

    def edit(self, title: str, text: str, summary: str, *,
             basetimestamp: str | None = None, nocreate: bool = True,
             createonly: bool = False) -> dict:
        """Create or replace a page. No-op (returns payload) when DRY_RUN.

        ``basetimestamp`` makes MediaWiki refuse the edit if the page changed
        since that revision (editconflict); ``starttimestamp`` makes it refuse
        if the page was deleted meanwhile. ``nocreate`` refuses to recreate a
        missing page; ``createonly`` refuses to overwrite an existing one. The
        two are never sent together.
        """
        payload = {
            "action": "edit",
            "title": title,
            "text": text,
            "summary": summary,
            "bot": True,
            "format": "json",
        }
        if createonly:
            payload["createonly"] = 1
        elif nocreate:
            payload["nocreate"] = 1
        if basetimestamp:
            payload["basetimestamp"] = basetimestamp
            payload["starttimestamp"] = basetimestamp
        if config.DRY_RUN:
            return {"dry_run": True, **payload}
        if not self._logged_in:
            raise RuntimeError("Call login() before editing with DRY_RUN off.")
        payload["token"] = self._csrf_token()
        return self._post(**payload)

    # --- transport --------------------------------------------------------

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
