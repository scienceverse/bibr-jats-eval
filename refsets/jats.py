"""JATS ``<mixed-citation>`` <-> bibr reference fields.

All three upstream sets end up as one JATS mixed-citation per reference (the
shape RenoBench ships), and ``fields_from_jats`` is the single path from that
markup to the bibr ``PaperReference`` field names the scorer compares. Using
one parser for every set keeps the field semantics identical across sets.

``authors`` and ``editors`` are the *printed span* covering every author
(editor) element, cut from the citation's own text, so they look like bibr's
``authors`` string ("Abbink, J., Brüne, S."). ``authors_list`` carries the
surnames when the markup has them.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from lxml import etree

_TITLE_TAGS = ("article-title", "chapter-title", "part-title")
_NAME_TAGS = ("name", "string-name")
_PAGE_RANGE_RE = re.compile(r"^\s*([^\s\-–—]+)\s*[-–—]+\s*([^\s\-–—]+)\s*$")


def _local(el: etree._Element) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def _text(el: etree._Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def parse_citation(xml: str) -> etree._Element:
    """Parse one citation; raises ``ValueError`` on malformed markup."""
    try:
        root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=False))
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"malformed citation XML: {exc}") from exc
    if _local(root) not in ("mixed-citation", "element-citation", "citation"):
        # RenoBench wraps some rows in <ref>; accept the first citation inside.
        for el in root.iter():
            if _local(el) in ("mixed-citation", "element-citation", "citation"):
                return el
    return root


def plaintext_of(root: etree._Element) -> str:
    return re.sub(r"\s+", " ", "".join(root.itertext())).strip()


def _offsets(root: etree._Element) -> dict[str, tuple[int, int]]:
    """Character span of every element inside ``"".join(root.itertext())``,
    keyed by the element's tree path (lxml proxies have no stable id())."""
    tree = root.getroottree()
    spans: dict[str, tuple[int, int]] = {}
    pos = 0

    def walk(el: etree._Element) -> None:
        nonlocal pos
        start = pos
        if el.text:
            pos += len(el.text)
        for child in el:
            walk(child)
            if child.tail:
                pos += len(child.tail)
        spans[tree.getpath(el)] = (start, pos)

    walk(root)
    return spans


def _span_text(raw: str, spans: list[tuple[int, int]]) -> str | None:
    if not spans:
        return None
    start = min(s for s, _ in spans)
    end = max(e for _, e in spans)
    value = re.sub(r"\s+", " ", raw[start:end]).strip()
    return value or None


def _people(root: etree._Element, role: str) -> list[etree._Element]:
    """Name elements for ``role`` ("author"/"editor"), group-scoped when grouped."""
    out: list[etree._Element] = []
    grouped = False
    for group in root.iter():
        if _local(group) != "person-group":
            continue
        kind = (group.get("person-group-type") or "author").strip().lower()
        grouped = True
        if kind != role:
            continue
        members = [el for el in group if _local(el) in _NAME_TAGS + ("collab",)]
        out.extend(members or [group])
    if not grouped and role == "author":
        out = [el for el in root.iter() if _local(el) in _NAME_TAGS + ("collab",)]
    return out


def _first(root: etree._Element, *names: str) -> str | None:
    for el in root.iter():
        if _local(el) in names:
            value = _text(el)
            if value:
                return value
    return None


def fields_from_jats(xml: str) -> dict[str, object]:
    """bibr ``PaperReference``-named fields for one JATS citation.

    Only fields the markup actually carries are returned; an absent key means
    "gold has no value", which the scorer excludes from that field's
    denominator.
    """
    root = parse_citation(xml)
    raw = "".join(root.itertext())
    spans = _offsets(root)
    path = root.getroottree().getpath
    out: dict[str, object] = {}

    authors = _people(root, "author")
    if authors:
        out["authors"] = _span_text(raw, [spans[path(el)] for el in authors])
        surnames = [
            _text(s) for el in authors for s in el.iter() if _local(s) == "surname" and _text(s)
        ]
        if surnames:
            out["authors_list"] = surnames
    editors = _people(root, "editor")
    if editors:
        out["editors"] = _span_text(raw, [spans[path(el)] for el in editors])

    pub_type = (root.get("publication-type") or "").strip().lower()
    title = _first(root, *_TITLE_TAGS)
    source = _first(root, "source")
    if title:
        out["title"] = title
        if source:
            out["container"] = source
    elif source:
        # A book/report cited whole prints its own title in <source>; a journal
        # or web page with no article title has only a container.
        if pub_type in ("journal", "webpage", "web"):
            out["container"] = source
        else:
            out["title"] = source

    year = _first(root, "year")
    if year:
        out["year"] = year
    for key, tag in (("volume", "volume"), ("issue", "issue"), ("publisher", "publisher-name")):
        value = _first(root, tag)
        if value:
            out[key] = value
    fpage = _first(root, "fpage")
    lpage = _first(root, "lpage")
    if fpage:
        out["first_page"] = fpage
    if lpage:
        out["last_page"] = lpage
    if not fpage:
        rng = _first(root, "page-range", "elocation-id")
        if rng:
            m = _PAGE_RANGE_RE.match(rng)
            out["first_page"] = m.group(1) if m else rng
            if m:
                out["last_page"] = m.group(2)
    for el in root.iter():
        if _local(el) == "pub-id" and (el.get("pub-id-type") or "").lower() == "doi":
            if _text(el):
                out["doi"] = _text(el)
                break
    url = _first(root, "uri", "ext-link")
    if url:
        out["url"] = url
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def wrap(tag: str, text: str, **attrs: str) -> str:
    """One escaped JATS element (attribute values are escaped too)."""
    attr = "".join(f' {k.replace("_", "-")}="{escape(v, {chr(34): "&quot;"})}"' for k, v in attrs.items())
    return f"<{tag}{attr}>{escape(text)}</{tag}>"
