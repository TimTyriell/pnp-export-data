"""Deterministic Markdown -> MediaWiki-Wikitext converter.

The KB's concept bodies are already synthesized, structured German markdown —
no LLM is needed (or wanted) to turn them into wiki pages: a deterministic
conversion cannot hallucinate, is free, and is trivially testable.

Scope is exactly the markdown the KB emits: ATX headings, bold/italic,
bullet lists, and markdown links between concepts. Anything unknown passes
through unchanged. Concept links are resolved against a ``concept -> wiki
page title`` map; links to concepts without a wiki page degrade to their
plain label text.

Inline source citations (``[P-08]``, ``[[S1-01-A]]`` — the KB is not
consistent about single vs. double brackets) are resolved the same way,
against an episode id -> wiki page title map: a known episode becomes a link
to that episode's own wiki page, an unknown one degrades to its bare label.
The KB's ``# Belege`` citation list itself is never emitted to the wiki (see
``pagemap.compose_body``) — these inline links are the wiki's only citation.
"""

from __future__ import annotations

import re

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# Episode citation markers: "[P-08]" or "[[P-08]]" (the KB emits both forms),
# and "[P-08, P-22]" where one statement rests on several sessions. Never
# overlaps _LINK_RE, which requires a trailing "(target)".
_CITE_ID = r"P-\d+|S\d+-\d+-[A-Za-z]+"
_CITE_MARKER_RE = re.compile(
    rf"\[{{1,2}}((?:{_CITE_ID})(?:\s*,\s*(?:{_CITE_ID}))*)\]{{1,2}}"
)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# Italic: single * pairs not at line start (line-start * is a bullet).
_ITALIC_RE = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")


def _normalize_target(target: str) -> str | None:
    """Reduce a markdown link target to a bundle concept id, if it is one.

    Handles ``/npcs/hexe.md`` (bundle-absolute), ``../npcs/hexe.md`` and
    ``hexe.md`` (relative — resolved by basename against the map's keys).
    External URLs return None.
    """

    if target.startswith(("http://", "https://", "mailto:")):
        return None
    target = target.split("#", 1)[0]
    if not target.endswith(".md"):
        return None
    return target[:-3].lstrip("./").lstrip("/")


class LinkResolver:
    """Resolve concept-link and episode-citation targets to wiki page titles."""

    def __init__(
        self,
        title_by_concept: dict[str, str],
        episode_titles: dict[str, str] | None = None,
    ):
        self.title_by_concept = title_by_concept
        self.episode_titles = episode_titles or {}
        # Basename fallback for relative links like (hexe.md) / (../npcs/hexe.md).
        self.by_basename: dict[str, str] = {}
        for concept, title in title_by_concept.items():
            base = concept.rsplit("/", 1)[-1]
            # First mapping wins; ambiguous basenames drop the fallback.
            if base in self.by_basename and self.by_basename[base] != title:
                self.by_basename[base] = ""
            else:
                self.by_basename.setdefault(base, title)

    def title_for(self, target: str) -> str | None:
        concept = _normalize_target(target)
        if concept is None:
            return None
        title = self.title_by_concept.get(concept)
        if title:
            return title
        return self.by_basename.get(concept.rsplit("/", 1)[-1]) or None

    def title_for_episode(self, marker: str) -> str | None:
        return self.episode_titles.get(marker)


def _convert_links(line: str, resolver: LinkResolver) -> str:
    def repl(match: re.Match) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://")):
            return f"[{target} {label}]"  # external wiki link syntax
        title = resolver.title_for(target)
        if title is None:
            return label  # concept without a wiki page -> plain text
        if title == label:
            return f"[[{title}]]"
        return f"[[{title}|{label}]]"

    return _LINK_RE.sub(repl, line)


def _convert_citations(line: str, resolver: LinkResolver) -> str:
    def one(marker: str) -> str:
        title = resolver.title_for_episode(marker)
        if title is None:
            return marker  # no (yet) wiki page for that episode -> plain text
        return f"[[{title}|{marker}]]"

    def repl(match: re.Match) -> str:
        return ", ".join(one(m.strip()) for m in match.group(1).split(","))

    return _CITE_MARKER_RE.sub(repl, line)


def markdown_to_wikitext(
    body_md: str,
    resolver: LinkResolver,
    category: str | None = None,
) -> str:
    out: list[str] = []
    for line in body_md.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            # Markdown h1 -> == on the wiki (page title is the h1 equivalent).
            level = min(len(heading.group(1)) + 1, 6)
            marks = "=" * level
            text = _convert_citations(
                _convert_links(heading.group(2).strip(), resolver), resolver
            )
            out.append(f"{marks} {text} {marks}")
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            indent, text = bullet.groups()
            depth = len(indent) // 2 + 1
            line = "*" * depth + " " + text
        line = _convert_links(line, resolver)
        line = _convert_citations(line, resolver)
        line = _BOLD_RE.sub(r"'''\1'''", line)
        line = _ITALIC_RE.sub(r"''\1''", line)
        out.append(line)
    text = "\n".join(out).strip() + "\n"
    if category:
        text += f"\n[[Kategorie:{category}]]\n"
    return text


# Transcription variants are pipeline bookkeeping, not encyclopaedic content:
# a reader does not care that the group's audio was once heard as "Breschka".
# The KB records them (they drive alias matching); the wiki should not repeat
# them. Aliases a character is genuinely *known* by are phrased differently
# ("auch X genannt") and deliberately survive.
_TRANSCRIPTION_NOTE_RE = re.compile(r"\s*\([^()]*transkribiert[^()]*\)")


# MediaWiki reserves these in page titles. "#" is the dangerous one: it starts
# a fragment, so the API accepts "Abisalis #6" and silently stores the page as
# "Abisalis" — no error, wrong title, and the next run no longer recognises its
# own page. A numbered part reads better spelled out anyway.
_TITLE_PART_RE = re.compile(r"#\s*(\d+)")
_TITLE_ILLEGAL_RE = re.compile(r"[#<>\[\]|{}]")


def wiki_safe_title(title: str) -> str:
    """``"Die Sanddorn Inseln #1"`` -> ``"Die Sanddorn Inseln Teil 1"``.

    Only the *page title* is sanitised. The name the KB and the episode list
    carry stays as written — it is what the overview table shows as the link
    label.
    """

    title = _TITLE_PART_RE.sub(r"Teil \1", title)
    title = _TITLE_ILLEGAL_RE.sub("", title)
    return re.sub(r"\s{2,}", " ", title).strip()


# Characters a Windows filename cannot hold. MediaWiki allows several of them
# in a title ("/" makes a subpage), so this is a *filename* transform only —
# the title itself must be recovered from the plan, never from the filename.
_FILENAME_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*]')


def proposal_filename(title: str) -> str:
    """The ``proposals/`` stem for a page title."""

    return _FILENAME_ILLEGAL_RE.sub("_", title)


def strip_transcription_variants(body_md: str) -> str:
    """Drop "(auch X, Y transkribiert)" asides from a KB body."""

    return _TRANSCRIPTION_NOTE_RE.sub("", body_md)
