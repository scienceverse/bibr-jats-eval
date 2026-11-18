"""Shared normalisation for the links and citations extension (gold/jats_eval_v1_ext, ext_metrics_version 1).

Used by the gold projector (project_ext_from_jats.py), the prediction adapters (ext_view.py) and the scorer
(score_ext.py), so gold and predictions are normalised by the same code.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹣－"), "-")
_WRAP = "<>[]{}\"'“”‘’«»"

# A URL or DOI in running text. Deliberately narrow: scheme or www., a DOI, or a bare research-repository host.
URL_RE = re.compile(
    r"(?:https?://|ftp://|www\d?\.)[^\s<>\"“”]+"
    r"|\bdoi:\s?10\.\d{4,9}/[^\s<>\"“”]+"
    r"|\b10\.\d{4,9}/[^\s<>\"“”]+"
    r"|\b(?:osf\.io|github\.com|gitlab\.com|zenodo\.org|figshare\.com|aspredicted\.org|bitbucket\.org"
    r"|researchbox\.org|dataverse\.[a-z.]+|openneuro\.org|psyarxiv\.com)/[^\s<>\"“”]*",
    re.I,
)

REPO_CLASSES = ("osf", "github", "zenodo", "aspredicted", "doi")

# Printed links that are page furniture rather than content: neither credited nor penalised (see README).
FURNITURE_HOSTS = (
    "orcid.org", "creativecommons.org", "crossmark.crossref.org", "crossref.org",
    "frontiersin.org", "loop.frontiersin.org", "journals.plos.org", "plos.org", "elifesciences.org",
    "nature.com", "springer.com", "link.springer.com", "springernature.com", "wiley.com", "onlinelibrary.wiley.com",
    "cambridge.org", "royalsocietypublishing.org", "peerj.com", "mdpi.com", "biomedcentral.com", "tandfonline.com",
    "sagepub.com", "journals.sagepub.com", "elsevier.com", "sciencedirect.com", "cell.com", "bmj.com", "apa.org",
    "psycnet.apa.org", "oup.com", "academic.oup.com", "hindawi.com", "jneurosci.org", "pnas.org", "science.org",
    "biorxiv.org/content/10.1101", "ncbi.nlm.nih.gov/pmc", "europepmc.org", "pubmed.ncbi.nlm.nih.gov",
    "copyright.com", "authorservices.wiley.com", "editorialmanager.com", "jstor.org", "s3-eu-west-1.amazonaws.com",
)


def url_like(s: str | None) -> bool:
    s = (s or "").strip()
    return bool(s) and not re.search(r"\s", s) and bool(URL_RE.search(s) or re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+/", s, re.I))


def _strip(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = s.strip(_WRAP).rstrip(".,;:!?")
        for a, b in ("()", "[]", "<>"):
            if s.startswith(a) and s.endswith(b):
                s = s[1:-1]
        if s.endswith(")") and s.count(")") > s.count("("):
            s = s[:-1]
        if s.startswith("(") and s.count("(") > s.count(")"):
            s = s[1:]
    return s


def norm_doi(d: str) -> str:
    d = unquote(d).strip()
    d = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return _strip(d)


def norm_url(s: str | None) -> str:
    """Comparable form of a printed URL/DOI. '' if nothing usable is left."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).translate(_DASHES)
    s = re.sub(r"[\s­​‌‍⁠﻿]+", "", s).casefold()
    s = _strip(s)
    if re.match(r"^(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:)", s) or re.match(r"^10\.\d{4,9}/", s):
        d = norm_doi(s)
        if m := re.match(r"^10\.17605/osf\.io/([a-z0-9]+)", d):
            return "osf.io/" + m.group(1)
        if m := re.match(r"^10\.5281/zenodo\.(\d+)", d):
            return "zenodo.org/records/" + m.group(1)
        return "doi:" + d if d else ""
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    s = re.sub(r"^www\d?\.", "", s)
    s = s.split("#", 1)[0].replace("/?", "?").rstrip("/")
    s = re.sub(r"^zenodo\.org/record/(\d+)", r"zenodo.org/records/\1", s)
    return _strip(s)


def host(u: str) -> str:
    if u.startswith("doi:"):
        return "doi"
    return u.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]


def repo_key(u: str) -> str | None:
    """Identity of a research-repository link, insensitive to sub-pages and view-only tokens. None otherwise."""
    if not u:
        return None
    if u.startswith("doi:"):
        return u
    h, _, path = u.partition("/")
    path = path.split("?", 1)[0] if h != "aspredicted.org" else path
    segs = [p for p in path.split("/") if p]
    if h == "osf.io" and segs:
        if segs[0] == "preprints" and len(segs) >= 3:
            return f"osf:{segs[2]}"
        return f"osf:{segs[0]}"
    if h == "github.com" and len(segs) >= 2:
        return f"github:{segs[0]}/{re.sub(r'[.]git$', '', segs[1])}"
    if h == "zenodo.org" and len(segs) >= 2 and segs[0] in ("records", "record", "deposit"):
        return f"zenodo:{segs[1]}"
    if h == "aspredicted.org" and path:
        return f"aspredicted:{path}"
    return None


def host_class(u: str) -> str:
    k = repo_key(u)
    return k.split(":", 1)[0] if k else "other"


# publisher-hosted supplement downloads of the article itself (JMIR "Multimedia Appendix" links)
FURNITURE_RES = [re.compile(r"(^|\.)jmir\.org/api/download")]


def is_furniture(u: str, own_doi: str = "") -> bool:
    """Article's own DOI (and DOIs that extend it: .t003, .s1 ...), licence, ORCID, publisher and index pages."""
    if not u or u.startswith("mailto:"):  # e-mail addresses are not links for this metric; gold has none
        return True
    if own_doi and u.startswith("doi:") and (u == own_doi or u[len(own_doi):len(own_doi) + 1] in (".", "/", "#")
                                             and u.startswith(own_doi)):
        return True
    if any(r.search(u) for r in FURNITURE_RES):
        return True
    h = host(u)
    for f in FURNITURE_HOSTS:
        if "/" in f:
            if u.startswith(f):
                return True
        elif h == f or h.endswith("." + f):
            return True
    return False


def norm_text(s: str) -> str:
    """Alignment form: NFKC, accents stripped, lowercase, alphanumerics only, digits removed."""
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower().replace("ß", "ss"))


def shingles(s: str, k: int = 8) -> list[str]:
    return [s[i:i + k] for i in range(len(s) - k + 1)]
