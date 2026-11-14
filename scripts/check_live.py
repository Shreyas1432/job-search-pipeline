#!/usr/bin/env python3
"""
check_live.py - is this role STILL ACCEPTING APPLICATIONS? A hard gate before tailoring.

WHY: on 2026-09-21 a resume was built for a role that had CLOSED. The check used at the
time only confirmed the posting PAGE still rendered and carried a title and a date. That
is not the same question. LinkedIn keeps closed postings up and serves them with HTTP 200.

The marker was in the HTML the whole time: "No longer accepting applications".

This ports the gate from an earlier sibling pipeline and
adds the closed-marker test. Its rules:
  LIVE        - a source that can actually prove it (LinkedIn guest endpoint without the
                closed marker, an ATS API returning an active req)
  CLOSED      - a proven dead/closed marker
  UNVERIFIED  - an aggregator or a JS shell. HTTP 200 from Indeed/Workday/Adzuna proves
                NOTHING (seen in practice: a req died between two checks while the
                URL still returned 200). Never upgrade UNVERIFIED to LIVE on a 200.

  python3 scripts/check_live.py --url <url>
  python3 scripts/check_live.py --tracker          # every 'Prepared' row
  python3 scripts/check_live.py --store-fresh 3    # store rows seen in last N days
"""
import argparse, csv, os, re, subprocess, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CLOSED = re.compile(r"no longer accepting applications|no-longer-accepting|"
                    r"closed to applications|this job is no longer available|"
                    r"position (has been|is) filled|vacancy (has )?closed", re.I)
# Hosts whose HTTP 200 means nothing.
AGGREGATOR = ("indeed.", "adzuna.", "glassdoor.", "jooble.", "careerjet.",
              "ziprecruiter.", "jobleads.", "irishjobs.ie", "eures.")
JS_SHELL = ("myworkdayjobs.com", "icims.com", "taleo.net", "corehr.com")
# Newest LinkedIn job ids seen 2026-11-13 are ~4,490,5xx,xxx. Ids >15M below that are weeks
# old, so a "posted 1 hour ago" on one is a repost. Bump this when sweeps show higher ids.
NEWEST_LI_ID = 4_490_590_000


def curl(url, timeout=20):
    r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), url, "-H", f"User-Agent: {UA}"],
                       capture_output=True, text=True)
    return r.stdout or ""


def linkedin_id(url):
    m = re.search(r"/jobs/view/(?:[^/]*-)?(\d{8,})", url) or re.search(r"currentJobId=(\d{8,})", url)
    return m.group(1) if m else None


def check(url):
    host = urllib.parse.urlparse(url).netloc.lower()

    jid = linkedin_id(url)
    if jid:
        html = curl(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}")
        if len(html) < 500:
            return "CLOSED", "LinkedIn guest endpoint returned nothing - posting removed"
        if CLOSED.search(html):
            return "CLOSED", "LinkedIn says: no longer accepting applications"
        # 2026-11-13 (a real case): a closed role can drop its Apply button WITHOUT
        # the closed text on the guest page, while the logged-in view says closed.
        if "apply-button" not in html and "top-card-layout__cta--primary" not in html:
            return "CLOSED", "LinkedIn shows no Apply button (closed or pulled)"
        t = re.search(r"posted-time-ago__text[^>]*>(.*?)</span>", html, re.S)
        age = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t.group(1))).strip() if t else "age unknown"
        n = re.search(r"([\d,]+)\s+applicants", html)
        apps = f"{n.group(1)} applicants" if n else ("200+ applicants" if "Over 200 applicants" in html else "applicant count hidden")
        # A fresh age with 200+ applicants, or a job id far below the newest ids, is a REPOST.
        repost = ("Over 200 applicants" in html and re.search(r"minute|hour", age)) or int(jid) < NEWEST_LI_ID - 15_000_000
        flag = " REPOST (age is not real)" if repost else ""
        org = re.search(r"topcard__org-name-link[^>]*>(.*?)<", html, re.S)
        ttl = re.search(r"top-card-layout__title[^>]*>(.*?)<", html, re.S)
        if org and ttl:
            import html as _h, employer_verify
            loc = re.search(r"topcard__flavor topcard__flavor--bullet[^>]*>(.*?)<", html, re.S)
            v, d = employer_verify.find(_h.unescape(org.group(1).strip()), _h.unescape(ttl.group(1).strip()),
                                        location=_h.unescape(loc.group(1).strip()) if loc else None)
            if v == "LIVE_EMPLOYER":
                return "LIVE", f"on employer board ({d['platform']}), {d.get('posted')}, {d['url']}{flag}"
            if v == "NOT_ON_BOARD":
                return "CLOSED", f"employer board {d['board']} does not list it (closed/ghost){flag}"
        age += flag
        # 2026-11-09: LinkedIn "not closed" is NOT "real vacancy". Easy Apply postings are
        # the classic ghost/low-response kind, so they are demoted; external-apply ones
        # still need the employer's own board before anything is built or recommended.
        if "apply-link-onsite" in html:
            return "EASY_APPLY", f"LinkedIn Easy Apply (low response, ghost risk), {age}, {apps}. Skip unless the employer board lists it."
        return "UNVERIFIED", (f"open on LinkedIn (not-closed only), external apply, {age}, {apps}. "
                              "Find it on the employer's own board before recommending.")

    if any(h in host for h in JS_SHELL):
        return "UNVERIFIED", (f"{host} serves a JS shell; HTTP 200 proves nothing. "
                              "Search the employer's own board BY REQ NUMBER.")
    if any(h in host for h in AGGREGATOR):
        return "UNVERIFIED", f"{host} is an aggregator; confirm on the employer's own site"

    html = curl(url)
    if not html:
        return "CLOSED", "no response"
    if CLOSED.search(html):
        return "CLOSED", "dead/closed marker found on the page"
    return "LIVE", f"page served content ({len(html):,} bytes), no closed marker"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--tracker", action="store_true")
    ap.add_argument("--store-fresh", type=int, metavar="DAYS")
    a = ap.parse_args()

    targets = []
    if a.url:
        targets = [("(supplied)", a.url)]
    elif a.tracker:
        for r in csv.DictReader(open("data/application_tracker.csv")):
            if r["status"].strip().lower().startswith("prepared") and r.get("application_url"):
                targets.append((f"{r['company'][:22]} / {r['job_title'][:26]}", r["application_url"]))
    elif a.store_fresh:
        sys.path.insert(0, "scripts")
        import job_store
        from datetime import date, timedelta
        cut = str(date.today() - timedelta(days=a.store_fresh))
        c = job_store.connect()
        for r in c.execute("SELECT title,company,url FROM jobs WHERE last_seen>=? AND url IS NOT NULL",
                           (cut,)).fetchall():
            targets.append((f"{r[1][:22]} / {r[0][:26]}", r[2]))
    else:
        ap.error("pass --url, --tracker or --store-fresh N")

    counts = {"LIVE": 0, "CLOSED": 0, "UNVERIFIED": 0, "EASY_APPLY": 0}
    print(f"\nChecking {len(targets)} role(s)\n" + "=" * 72)
    for label, url in targets:
        state, why = check(url)
        counts[state] += 1
        mark = {"LIVE": "OK  ", "CLOSED": "DEAD", "UNVERIFIED": "??  ", "EASY_APPLY": "EASY"}[state]
        print(f"  [{mark}] {label[:48]:48s} {state}")
        print(f"         {why}")
    print("=" * 72)
    print(f"  LIVE {counts['LIVE']}   CLOSED {counts['CLOSED']}   UNVERIFIED {counts['UNVERIFIED']}   EASY_APPLY {counts['EASY_APPLY']}")
    print("  RULE: never build a resume for anything not LIVE. UNVERIFIED means go and"
          "\n        check the employer's own board before spending tailoring budget.\n")
    return 1 if counts["CLOSED"] else 0


if __name__ == "__main__":
    sys.exit(main())
