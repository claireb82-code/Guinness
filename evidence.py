"""
Honest evidence: what we know about a venue, and where we know it from.

The app used to fill in review counts, crowd "confirmations", pint ratings, Google ratings and even review
quotes with fixed numbers whenever a venue merely *looked* Irish (its name, an OpenStreetMap tag, a bundled
starter list). Those numbers then fed the "Confirmed" / "Mentioned in Reviews" labels, so a guess looked like
a fact. The rule now is: a field holds real evidence or it is empty.

* ``menuCheck``   - we really fetched the venue's website and read it (``checked``) and what it said.
* ``reviewCheck`` - Google review/summary text that really mentions Guinness.
* ``crowdCheck``  - reports submitted by visitors of this app, nothing else.
* ``tagCheck``    - a *weaker* signal that is not a check: ``{"kind": ..., "text": ...}`` where kind is
  ``osm_tag`` (a volunteer-edited OpenStreetMap tag names Guinness), ``irish_name`` (the venue's name
  suggests an Irish pub) or ``starter_list`` (listed in this app's bundled starter list, never checked).
  It can make a venue "likely", never "confirmed".

Pure standard library; no I/O.
"""

import copy
import re

TAG_OSM = "osm_tag"
TAG_NAME = "irish_name"
TAG_STARTER = "starter_list"

TAG_TEXT = {
    TAG_OSM: "OpenStreetMap lists Guinness as a beer or brewery here. Those tags are edited by volunteers and not checked by this app.",
    TAG_NAME: "The name suggests an Irish pub. Nothing was checked, so this is a guess.",
    TAG_STARTER: "Part of this app's starter list of Irish pubs and Guinness venues. It has not been checked.",
}

# Words in a venue name that suggest an Irish pub. A hint only (it also matches "Kelly's Pizza").
IRISH_NAME_RE = re.compile(
    r"\b(irish|guinness|shamrock|pickwick|paddy|mulligan|flanagan|kelly|celtic|dublin|o'|pub)\b", re.I
)

# Website wording that says how Guinness is served (English, German, French, Italian).
DRAUGHT_RE = re.compile(r"draught|draft|on tap|\btap\b|vom fass|\bfass\b|pression|alla spina|\bpint\b|zapfen", re.I)
CAN_RE = re.compile(r"\bcans?\b|bottles?|flasche|dose|bouteille|bottiglia", re.I)

SYNTHETIC_AUTHORS = frozenset({"Swiss Nationwide Crawler", "Switzerland OSM Directory", "OpenStreetMap Tags"})


def is_irish_name(name):
    return bool(IRISH_NAME_RE.search(name or ""))


def tag_check(kind, text=None):
    return {"kind": kind, "text": text or TAG_TEXT[kind]}


def no_reviews():
    return {"mentionCount": 0, "sentiment": "none", "excerpts": []}


def no_crowd():
    return {
        "confirmedCount": 0,
        "deniedCount": 0,
        "servingFormat": "unknown",
        "avgPintRating": None,
        "reportedPrice": None,
        "hasZero": False,
        "recentReports": [],
    }


def not_checked(note=None):
    return {
        "checked": False,
        "lastChecked": None,
        "foundOnMenu": False,
        "typesFound": [],
        "extractedPrice": None,
        "snippets": [note] if note else [],
    }


def serving_types(snippets):
    """What the website wording says about how Guinness is served (never assumed from the word alone)."""
    text = " ".join(snippets or [])
    types = []
    if DRAUGHT_RE.search(text):
        types.append("Guinness Draught (On Tap)")
    if CAN_RE.search(text):
        types.append("Guinness (Cans / Bottles)")
    return types or ["Guinness (mentioned on website)"]


def _kind_of_crawl_menu(menu):
    """How the bundled crawl file got ``foundOnMenu``: a real website match, an OSM tag, or a name guess."""
    snippets = " ".join(menu.get("snippets") or [])
    types = " ".join(menu.get("typesFound") or [])
    if "OSM Brewery" in types or snippets.startswith("OpenStreetMap Switzerland tag"):
        return TAG_OSM
    if snippets.startswith("Verified Irish pub"):
        return TAG_NAME
    return None


def sanitise_static_venue(venue):
    """A copy of a venue from the bundled data files with every invented number removed.

    ``swiss_crawl_results.json`` and the starter list were generated with fixed ratings, review counts, crowd
    confirmations and review quotes. What is real is kept: the venue's name, place, website, a website that
    the crawler really read (and what it found or did not find there). What was a guess becomes a ``tagCheck``.
    """
    if not isinstance(venue, dict):
        return venue
    v = copy.deepcopy(venue)
    if "tagCheck" in v:  # already clean (e.g. written by the fixed crawler): leave it alone
        return v
    is_crawl = str(v.get("id", "")).startswith("ch-")
    menu = v.get("menuCheck") or {}

    v["googleRating"] = None
    v["googleReviewCount"] = 0
    v["priceLevel"] = None
    v["reviewCheck"] = no_reviews()
    v["crowdCheck"] = no_crowd()

    tag = None
    if is_crawl:
        kind = _kind_of_crawl_menu(menu) if menu.get("foundOnMenu") or menu.get("typesFound") else None
        if kind == TAG_OSM:
            tag = tag_check(TAG_OSM)
            v["menuCheck"] = not_checked()
        elif kind == TAG_NAME:
            tag = tag_check(TAG_NAME)
            scanned = "Website scanned" in " ".join(menu.get("snippets") or [])
            v["menuCheck"] = (
                {**not_checked("The website was read: no Guinness text found."), "checked": True, "lastChecked": menu.get("lastChecked")}
                if scanned
                else not_checked()
            )
        else:
            snippets = menu.get("snippets") or []
            v["menuCheck"] = {**menu, "typesFound": serving_types(snippets) if menu.get("foundOnMenu") else []}
        if tag:
            v["editorialSummary"] = f"{(v.get('category') or 'venue').title()} found through OpenStreetMap."
        elif menu.get("foundOnMenu"):
            v["editorialSummary"] = f"{(v.get('category') or 'venue').title()}; Guinness is mentioned on its website."
        else:
            v["editorialSummary"] = f"{(v.get('category') or 'venue').title()}; no Guinness found on its website."
    else:  # starter list: written by hand, never checked
        tag = tag_check(TAG_STARTER)
        v["menuCheck"] = not_checked()
        v["editorialSummary"] = f"{(v.get('category') or 'venue').title()} in the app's starter list. Not yet checked."

    if tag:
        v["tagCheck"] = tag
    else:
        v.pop("tagCheck", None)
    return v
