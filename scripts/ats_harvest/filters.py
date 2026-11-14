"""Market / title / recency filters. Recency uses the TRUE date only: a posting
with no date is NEVER counted fresh (the AIG rule)."""
from datetime import datetime, timezone
from typing import Optional

from .record import JobPosting

# Full words only — 2-letter ISO codes ("ie"/"in") are omitted on purpose because
# they false-match as substrings ("berlin" contains "in", "field" contains "ie").
_IE = ("ireland", "dublin", "cork", "limerick", "galway", "waterford")
_IN = ("india", "hyderabad", "bengaluru", "bangalore", "chennai", "pune",
       "mumbai", "delhi", "gurgaon", "gurugram", "noida")
_MARKET_KW = {"IE": _IE, "IN": _IN}

# data-role title allowlist (mirrors the sourcing term list)
DATA_TERMS = ("data analyst", "data engineer", "analytics engineer", "bi developer",
              "business intelligence", "bi analyst", "data scientist", "data modeler",
              "data modeller", "reporting analyst", "insights analyst", "insight analyst",
              "data quality", "data governance", "analytics", "data science", "machine learning",
              "ml engineer", "ai engineer", "data warehouse")


def _text_has(text: Optional[str], keywords) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in keywords)


def in_market(p: JobPosting, markets) -> bool:
    hay = f"{p.location or ''} {p.country or ''}"
    for m in markets:
        if _text_has(hay, _MARKET_KW.get(m, ())):
            return True
    if p.remote and _text_has(hay, ("eu", "europe", "india", "ireland", "remote")):
        return True
    return False


def title_match(title: str) -> bool:
    return _text_has(title, DATA_TERMS)


def is_fresh(p: JobPosting, hours: int) -> bool:
    if not p.posted_date:
        return False
    try:
        d = datetime.fromisoformat(p.posted_date.replace("Z", "+00:00"))
    except ValueError:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - d).total_seconds() / 3600.0
    return 0 <= age_h <= hours or age_h < 0  # future-dated treated as fresh
