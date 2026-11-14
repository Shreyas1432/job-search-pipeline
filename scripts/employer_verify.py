#!/usr/bin/env python3
"""
employer_verify.py - is this role listed on the EMPLOYER'S OWN job board right now?

WHY (2026-11-13): LinkedIn's public guest page showed a Data Analyst role as
"not closed" while a logged-in view said "No longer accepting applications".
A LinkedIn or Indeed listing is a LEAD. The only proof a vacancy is real and open is the
employer's own ATS returning the req. This finds the employer's board (catalog first,
then probes the public APIs of the common ATS platforms by company slug), looks for the
title, and adds every board it finds to the catalog so `make source` harvests it too.

Verdicts:
  LIVE_EMPLOYER  - title found on the employer's board (apply URL + true date returned)
  NOT_ON_BOARD   - the board exists but does not list this title: closed, filled, or a
                   ghost/agency repost. Do NOT build.
  NO_BOARD       - no board found on the probed platforms. Stays UNVERIFIED; check by hand.

  python3 scripts/employer_verify.py --company "TVH" --title "Data Analyst"
  python3 scripts/employer_verify.py --selftest
"""
import argparse, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ats_harvest import catalog, registry                      # noqa: E402
from ats_harvest.base import http_json, concurrent_map, parse_workday_date  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jobs.db")
NOISE = r"\b(private|pvt|limited|ltd|inc|llc|plc|corp(oration)?|company|co|group|holdings|" \
        r"india|ireland|technologies|technology|solutions|services|software|systems|global|international)\b"
SINGLE_CALL = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "personio")
WD_HOSTS = ("wd1", "wd3", "wd5", "wd103", "wd12")
WD_SITES = ("External", "Careers", "{S}", "{S}Careers", "{S}_Careers", "External_Careers", "careers", "jobs")


def slugs(company):
    base = re.sub(r"\(.*?\)", " ", company.lower())
    base = re.sub(NOISE, " ", base)
    words = re.findall(r"[a-z0-9]+", base)
    out = []
    for s in ("".join(words), "-".join(words), words[0] if words else ""):
        if s and s not in out:
            out.append(s)
    return out


def norm(t):
    return set(re.findall(r"[a-z0-9]+", re.sub(r"\b(sr|senior|jr|junior|i|ii|iii)\b", " ", t.lower())))


def title_match(want, got):
    a, b = norm(want), norm(got)
    if not a or not b:
        return False
    # a subset counts only when the other side adds <= 2 words (a city, a level, a team).
    extra = 1 if min(len(a), len(b)) <= 2 else 2   # short titles: "Financial Analyst" != "Financial Risk Quant Analyst"
    return len(a & b) / len(a | b) >= 0.6 or (a <= b and len(b - a) <= extra) or (b <= a and len(a - b) <= extra)


def _probe_single(args):
    platform, slug = args
    try:
        posts = registry.get(platform)().fetch(slug)
        return (platform, slug, posts)
    except Exception:
        return None


def _probe_workday(args):
    host, site, title = args
    tenant = host.split(".")[0]
    for attempt in (1, 2):   # one retry: under load a slow tenant must not read as "no board"
        try:
            d = http_json(f"https://{host}/wday/cxs/{tenant}/{site}/jobs", method="POST",
                          json_body={"limit": 20, "offset": 0, "searchText": title, "appliedFacets": {}},
                          timeout=20 if attempt == 2 else 10)
            return ("workday", f"{host}/{site}", d.get("jobPostings", []))
        except Exception as e:
            if "404" in str(e) or "400" in str(e) or "422" in str(e):
                return None   # a real "no such site", not a timeout
    return None


def find(company, title, market=None, add=True, location=None):
    """Return (verdict, detail dict)."""
    catalog.ensure_schema(DB)
    key = re.sub(NOISE, " ", company.lower()).strip()
    kw = set(re.findall(r"[a-z0-9]+", key))

    def same(name):   # whole words only: "isa" must not match "visa"
        w = set(re.findall(r"[a-z0-9]+", re.sub(NOISE, " ", name.lower())))
        return bool(kw) and bool(w) and (kw <= w or w <= kw)
    boards = [r for r in catalog.list(DB) if same(r["company"])]
    hits = []
    for r in boards:
        if r["platform"] == "workday":
            res = _probe_workday((r["board_token"].split("/")[0], r["board_token"].split("/")[1], title))
            if res:
                hits.append(res)
        else:
            res = _probe_single((r["platform"], r["board_token"]))
            if res:
                hits.append(res)
    if not hits:
        jobs = [(p, s) for s in slugs(company) for p in SINGLE_CALL]
        hits = [h for h in concurrent_map(_probe_single, jobs, workers=8) if h and h[2]]
    if not hits:
        wd = [(f"{s}.{w}.myworkdayjobs.com", site.replace("{S}", s.capitalize()), title)
              for s in slugs(company)[:1] for w in WD_HOSTS for site in WD_SITES]
        hits = [h for h in concurrent_map(_probe_workday, wd, workers=8) if h is not None]
        hits = hits[:1]   # first board that answered is the tenant
    if not hits:
        return "NO_BOARD", {"tried": slugs(company)}

    platform, token, posts = hits[0]
    probed = not boards   # found by slug guessing: may be a different company of the same name
    matches = []
    for p in posts:
        if isinstance(p, dict):   # raw Workday search row
            host = token.split("/")[0]
            m = {"title": p.get("title", ""), "posted": p.get("postedOn"), "location": p.get("locationsText") or p.get("externalPath", ""),
                 "url": f"https://{host}{p.get('externalPath', '')}"}
        else:
            m = {"title": p.title, "posted": p.posted_date, "location": p.location or "", "url": p.apply_url}
        if title_match(title, m["title"]):
            matches.append(m)
    if matches:
        loc = (location or "").lower()
        want = set()
        if loc:
            codes = {"mh": "maharashtra mumbai pune", "ka": "karnataka bengaluru bangalore", "tn": "tamil chennai",
                     "ts": "telangana hyderabad", "tg": "telangana hyderabad", "hr": "haryana gurugram gurgaon",
                     "up": "uttar noida", "dl": "delhi", "d": "dublin", "c": "cork", "g": "galway", "l": "limerick"}
            toks = re.findall(r"[a-z]+", loc)
            toks = toks + [w for t in toks if t in codes for w in codes[t].split()]
            want = {t for t in toks if len(t) >= 3} - {"county", "district", "division", "area", "greater", "metropolitan",
                                                       "region", "verify", "careers", "care", "india", "ireland", "remote"}
        if loc and want:
            def where(m):
                return set(re.findall(r"[a-z]+", (m["location"] + " " + m["url"]).lower()))
            here = [m for m in matches if want & where(m)]
            ie = {"dublin", "cork", "galway", "limerick", "waterford", "kildare", "meath", "wicklow", "louth", "dundalk",
                  "athlone", "sligo", "kilkenny", "letterkenny", "shannon", "swords", "tralee", "monaghan", "carlow", "ennis"}
            ind = {"hyderabad", "bengaluru", "bangalore", "chennai", "pune", "mumbai", "gurugram", "gurgaon", "noida",
                   "delhi", "kolkata", "ahmedabad", "maharashtra", "karnataka", "telangana", "tamil", "haryana"}
            country = ({"ireland", "india"} & set(toks)) | ({"ireland"} if ie & set(toks) else set()) | ({"india"} if ind & set(toks) else set())
            if not here and country:   # city did not match: accept the same country (e.g. "Ireland-Remote")
                here = [m for m in matches if country & where(m)]
            multi = [m for m in matches if re.search(r"\d+ locations", m["location"].lower())]
            if not here and multi:   # "3 Locations": the one we want may or may not be among them
                return "NO_BOARD", {"note": f"multi-location req on {token}, check by hand: {multi[0]['url']}"}
            if not here:
                if probed:
                    return "NO_BOARD", {"note": f"guessed board {token} lists the title only elsewhere"}
                return "NOT_ON_BOARD", {"platform": platform, "board": token, "note": f"title listed only elsewhere: {[m['location'] for m in matches][:4]}"}
            matches = here
        if add and probed:
            catalog.add(DB, company, platform, token, market=market)
        # several reqs with the same title: the newest is the one the listing points at
        matches.sort(key=lambda m: str(parse_workday_date(m["posted"]) if str(m["posted"]).startswith("Posted") else m["posted"] or ""), reverse=True)
        return "LIVE_EMPLOYER", {"platform": platform, "board": token, **matches[0], "also": len(matches) - 1}
    if probed:   # a guessed board can confirm a role, never condemn it
        return "NO_BOARD", {"note": f"guessed board {token} does not list it (may be another company)"}
    return "NOT_ON_BOARD", {"platform": platform, "board": token, "board_size": len(posts)}


def selftest():
    assert slugs("TVH India Private Limited")[0] == "tvh"
    assert slugs("Gartner")[0] == "gartner"
    assert title_match("Data Analyst", "Data Analyst - Pune")
    assert title_match("Senior Data Analyst", "Data Analyst")
    assert not title_match("Data Analyst", "Software Engineer, Payments")
    assert not title_match("Data Analyst", "Knowledge Analyst - Data Curation & Classification")
    assert title_match("FinOps & Product Analytics Engineer", "FinOps & Product Analytics Engineer")
    assert not title_match("Financial Analyst", "Financial Risk Quantitative Analyst")
    assert title_match("Data Analyst", "Data Analyst - Pune")
    kw = {"isa"}; w = {"visa"}
    assert not (kw <= w or w <= kw), "ISA must not match Visa"
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--company")
    ap.add_argument("--title")
    ap.add_argument("--market")
    ap.add_argument("--location", help="city/country hint; a title listed only elsewhere is NOT_ON_BOARD")
    ap.add_argument("--no-add", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); sys.exit(0)
    if not (a.company and a.title):
        ap.error("pass --company and --title")
    v, d = find(a.company, a.title, a.market, add=not a.no_add, location=a.location)
    print(v, d)
