#!/usr/bin/env python3
"""
job_filters.py — SINGLE SOURCE OF TRUTH for sourcing filters.

WHY THIS FILE EXISTS (2026-08-26): the search-term list was duplicated across
scripts/jobspy_fetch.py and scripts/scrape_jobs.py and silently DRIFTED. Each
copy was missing different target titles, so for a week neither IrishJobs nor
LinkedIn was searched for the full target list, and "Applied AI Engineer" and
"Machine Learning Engineer" were never searched at all. Every sourcing script
must import from here rather than keeping its own copy.
"""

# Target role families, in priority order.
TARGET_TERMS = [
    # Lane 1 - analytics and BI engineering (strongest lane)
    "analytics engineer", "business intelligence developer", "bi developer",
    "power bi developer", "bi analyst", "business intelligence analyst",
    # Lane 2 - data engineering
    "data engineer", "data warehouse engineer", "snowflake developer", "dbt developer",
    # Lane 3 - analyst / insights / reporting
    "data analyst", "senior data analyst", "reporting analyst",
    "insights analyst", "insight analyst", "analytics consultant",
    "business analyst", "data quality analyst", "data governance",
    # Lane 4 - applied AI / ML
    "applied ai engineer", "machine learning engineer", "ai engineer",
]

# ---------------------------------------------------------------------------
# NORTHERN IRELAND IS NOT IRELAND.
# Belfast, Derry, Lisburn etc. are the United Kingdom. A Republic of Ireland work
# permission does NOT cover Northern Ireland, but board searches for "Ireland"
# happily return NI roles - one career-site run surfaced 6 of them. Filter on
# every channel.
# ---------------------------------------------------------------------------
NI_CITIES = {
    "belfast", "derry", "londonderry", "derry/londonderry", "lisburn", "omagh",
    "ballymena", "newry", "armagh", "bangor", "craigavon", "coleraine",
    "enniskillen", "dundonald", "antrim", "larne", "newtownabbey",
    "carrickfergus", "strabane", "downpatrick", "banbridge", "portadown",
    "derry and strabane district", "county antrim", "county down",
    "county armagh", "county tyrone", "county fermanagh", "county londonderry",
    "northern ireland",
}


def is_northern_ireland(text) -> bool:
    """True if a location string or list of cities is in Northern Ireland."""
    if not text:
        return False
    if isinstance(text, (list, tuple, set)):
        return any(is_northern_ireland(t) for t in text)
    low = str(text).lower()
    return any(c in low for c in NI_CITIES)


# Board employment-type tags are unreliable (verified 2026-08-25: two of three
# "full-time" hits were day-rate contracts), so re-derive from the JD wording.
# Permanent is the target, contract a fallback.
CONTRACT_RE = (r"day rate|per day|/day|\bdrc\b|month contract|fixed[- ]term"
               r"|\bftc\b|contract role|daily rate|rolling contract")

# Out-of-level titles for a 3-YOE profile.
NOISE_TITLES = ("director", "head of", "vp ", "vice president", "chief",
                "principal", "staff ", "intern", "internship",
                "graduate programme", "apprentice")

# A title must look data-shaped, or "data engineer" drags in mechanical,
# civil, welding and support engineers (~half the raw hits, verified 2026-08-25).
RELEVANT_TITLES = ("data", "analytics", "analyst", "business intelligence",
                   " bi ", "reporting", "insight", "warehouse", "etl", "sql",
                   "power bi", "steward", "governance", "master data",
                   "dashboard", "machine learning", "ai engineer")
