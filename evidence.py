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
TAG_WEB = "web_mention"  # a restaurant/hotel website names Guinness, but not clearly as something on the menu

TAG_TEXT = {
    TAG_OSM: "OpenStreetMap lists Guinness as a beer or brewery here. Those tags are edited by volunteers and not checked by this app.",
    TAG_NAME: "The name suggests an Irish pub. Nothing was checked, so this is a guess.",
    TAG_WEB: "Its website mentions Guinness, but not clearly as something they serve (it could be a recipe or an event).",
    TAG_STARTER: "Part of this app's starter list of Irish pubs and Guinness venues. It has not been checked.",
}

# Words in a venue name that suggest an Irish pub. A hint only (it also matches "Kelly's Pizza").
IRISH_NAME_RE = re.compile(
    r"\b(irish|guinness|shamrock|pickwick|paddy|mulligan|flanagan|kelly|celtic|dublin|o'|pub)\b", re.I
)

# Website wording that says how Guinness is served (English, German, French, Italian).
DRAUGHT_RE = re.compile(r"draught|draft|on tap|\btap\b|vom fass|\bfass\b|ausschank|pression|alla spina|\bpint\b|zapf", re.I)
CAN_RE = re.compile(r"\bcans?\b|bottles?|flasche|dose|bouteille|bottiglia", re.I)

# A price as printed on Swiss menus: "CHF 9.50", "Fr. 9.-", "9,50 CHF", "SFr 9".
_PRICE_RE = re.compile(
    r"(?:CHF|SFr\.?|Fr\.?)\s*(\d{1,2}(?:[.,]\d{1,2})?)(?:\.-)?|(\d{1,2}(?:[.,]\d{1,2})?)(?:\.-)?\s*(?:CHF|SFr\.?|Fr\.?)",
    re.I,
)
PRICE_WINDOW = 70  # characters after the word "Guinness" in which its price is looked for

SYNTHETIC_AUTHORS = frozenset({"Swiss Nationwide Crawler", "Switzerland OSM Directory", "OpenStreetMap Tags"})


def price_near_guinness(snippets):
    """The first price printed right after the word "Guinness" in the page text, as "CHF 8.50", or None.

    Taking the first price anywhere in the snippets (as the crawler did) picks up the neighbouring beer's price.
    This is the price listed after the Guinness entry, which may be a small glass: it is not a pint-price check.
    """
    for snippet in snippets or []:
        for m in re.finditer(r"guinness", snippet or "", re.I):
            hit = _PRICE_RE.search(snippet[m.end() : m.end() + PRICE_WINDOW])
            if hit:
                amount = float((hit.group(1) or hit.group(2)).replace(",", "."))
                if 2 <= amount <= 40:
                    return f"CHF {amount:.2f}"
    return None


# "Beef & Guinness pie", "Guinness cake", "Guinness World Record": the word is there, the beer is not (necessarily).
FOOD_WORDS = r"pies?|stews?|beef|cakes?|brownies?|bread|sauce|gravy|chocolate|burgers?|braised|glazed|marinated|ice\s*cream|mousse|cheddar|chilli|records?"
_FOOD_BEFORE = re.compile(rf"\b(?:{FOOD_WORDS})\W+(?:\w+\W+){{0,3}}guinness\b", re.I)
_FOOD_AFTER = re.compile(rf"\bguinness\W+(?:\w+\W+){{0,2}}(?:{FOOD_WORDS})\b", re.I)
# Addresses and file names are not text a visitor reads: guinness-pour.jpg, /images/guinness/, "fileName":"guinness.png"
_URL_OR_FILE = re.compile(r"https?:\\?/\\?/\S+|\S*\.(?:jpe?g|png|gif|svg|webp|avif|pdf|mp4)\b\S*|[\w./\\-]*(?:/|\\)[\w.\\/-]*guinness[\w.\\/-]*", re.I)


def strip_urls_and_files(text):
    return _URL_OR_FILE.sub(" ", text or "")


def is_food_mention(snippet):
    """True when a snippet names Guinness only as an ingredient or a record, with nothing saying it is poured."""
    text = snippet or ""
    if not re.search(r"guinness", text, re.I):
        return False
    if DRAUGHT_RE.search(text):  # "on tap", "vom Fass", "pint"...: it is poured (a price alone could be a dish's)
        return False
    return bool(_FOOD_BEFORE.search(text) or _FOOD_AFTER.search(text))


def website_mention_kind(category, snippets):
    """Does a venue's own website name Guinness as something it serves ("menu"), or only mention it ("mention")?

    A pub or bar that names Guinness on its website almost certainly pours it. A restaurant or hotel might only have a
    recipe ("braised in Guinness"), an event or a blog post, so there the text has to say how it is served or what it
    costs. Text that only came from page metadata (keywords) never counts as a menu.
    """
    snippets = [x for x in (snippets or []) if not is_food_mention(x)] if snippets else []
    text = " ".join(snippets)
    if not text.strip() or re.search(r"<meta|content=|name=\"keywords", text, re.I):
        return "mention"
    if (category or "") in ("pub", "bar"):
        return "menu"
    if DRAUGHT_RE.search(text) or CAN_RE.search(text) or price_near_guinness(snippets) or re.search(r"0[.,]0|alkoholfrei|sans alcool", text, re.I):
        return "menu"
    return "mention"


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

    v["editorialSummary"] = None  # hand-written or generated blurbs said nothing the evidence does not (the label and its reason do)
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
        elif menu.get("foundOnMenu") and website_mention_kind(v.get("category"), menu.get("snippets")) == "mention":
            # a restaurant/hotel site that names Guinness without saying it is served: a hint, not a confirmation
            tag = tag_check(TAG_WEB)
            v["menuCheck"] = {**menu, "foundOnMenu": False, "typesFound": [], "extractedPrice": None}
        else:
            snippets = menu.get("snippets") or []
            v["menuCheck"] = {
                **menu,
                "typesFound": serving_types(snippets) if menu.get("foundOnMenu") else [],
                # the crawler took the first price in the snippets, often another beer's: re-read it from the text
                "extractedPrice": price_near_guinness(snippets) if menu.get("foundOnMenu") else None,
            }
    else:  # starter list: written by hand, never checked
        # A hand-typed deep link (".../birre", ".../drinks") was a guess at the site's structure that nothing ever opened:
        # drop it. The UI falls back to the venue's website, and apply_site_check() puts back the page a crawl really read.
        v.pop("menuUrl", None)
        tag = tag_check(TAG_STARTER)
        hint = menu.get("extractedPrice") or (venue.get("crowdCheck") or {}).get("reportedPrice")
        if hint:  # kept, but shown as "unchecked": nothing in this app read it from the venue
            v["priceHint"] = {"price": hint, "text": "Price from the starter list, not checked."}
        v["menuCheck"] = not_checked()

    if tag:
        v["tagCheck"] = tag
    else:
        v.pop("tagCheck", None)
    return v


def apply_site_check(venue, check):
    """A copy of a sanitised starter-list venue with what the crawler really read on its own website.

    ``check`` is the crawler's record for that venue (``starterChecks`` in the crawl results): ``reachable``, ``foundOnMenu``,
    ``typesFound``, ``snippets``, ``extractedPrice``, ``checkedUrl``, ``checkedAt``. A site that could not be read changes
    nothing (that is "unknown", never "no"). A site that was read but does not mention Guinness is recorded as read, but the
    starter-list hint stays: a pub's website not naming its beer is not evidence that it does not pour it. A site that names
    Guinness as something served becomes a real menu check; one that only mentions it (a recipe, an event) becomes a weaker hint.
    """
    if not isinstance(venue, dict) or not isinstance(check, dict) or not check.get("reachable"):
        return venue
    v = copy.deepcopy(venue)
    read_at = check.get("checkedAt")
    page = check.get("checkedUrl")
    if page and not v.get("menuUrl"):
        v["menuUrl"] = page  # a page this app really opened
    snippets = check.get("snippets") or []
    if check.get("foundOnMenu"):
        if website_mention_kind(v.get("category"), snippets) == "menu":
            v["menuCheck"] = {
                "checked": True,
                "lastChecked": read_at,
                "foundOnMenu": True,
                "typesFound": serving_types(snippets),
                "extractedPrice": price_near_guinness(snippets),
                "snippets": snippets,
            }
            v.pop("tagCheck", None)  # real evidence replaces the guess
            v.pop("priceHint", None)
        else:
            v["tagCheck"] = tag_check(TAG_WEB)
            v["menuCheck"] = {**not_checked("The website mentions Guinness without saying it is served."), "checked": True, "lastChecked": read_at}
    else:
        v["menuCheck"] = {**not_checked("The website was read: no Guinness text found."), "checked": True, "lastChecked": read_at}
    return v
