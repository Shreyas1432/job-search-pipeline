#!/usr/bin/env python3
"""
jobspy_fetch.py
Multi-board Ireland job sourcing via JobSpy (github.com/speedyapply/JobSpy).

Why this exists: Indeed MCP gives one board, IrishJobs gives salaries, Apify gives
applicant counts. JobSpy adds Indeed + LinkedIn in ONE call with a real `hours_old`
recency filter and FULL job descriptions, with no login and no cookies.

Account safety: the LinkedIn path here uses LinkedIn's PUBLIC guest job endpoint.
It does NOT use anyone's session cookie, so it carries no account-restriction risk.
Do not "improve" this by adding a li_at cookie.

Known limits (verified 2026-08-25):
  - Glassdoor returns HTTP 400 "location not parsed" for Ireland. Excluded by default.
  - **LinkedIn's `hours_old` filter cannot be trusted.** Verified 2026-08-25: a 24-hour
    LinkedIn query returned 18 rows, ZERO with a real `date_posted`, spanning job IDs
    4420709478..4459005173 -- i.e. it happily returns weeks-old reposts and strips the
    date. Indeed's filter DOES work and returns real dates. So every row is tagged with
    a recency confidence: Indeed rows are VERIFIED, LinkedIn rows are graded by job ID.
    Calibration (98 dated rows): the max LinkedIn job ID rises monotonically with the
    posting date, so a HIGH id proves freshness, while a LOW id proves nothing (an old
    req that gets reposted keeps its old id). Treat LinkedIn recency as a hint, never
    as a fact, and confirm on the listing before calling anything "posted today".
  - Google Jobs does not serve Ireland at all (settled finding). Never add it.
  - ZipRecruiter is US/Canada only.
  - **`--job-type fulltime` is NOT reliable either.** Verified 2026-08-25: a fulltime-only
    sweep returned an Engage People role advertised as "EUR 550/day, rolling 6-month
    contract" and a recruiter role advertised as "Day Rate Contract EUR 500-600/day" in its
    first three data hits. The boards' own employment-type tags are wrong often enough
    that permanent-vs-contract MUST be confirmed from the JD text, not the filter.
  - LinkedIn rate-limits around page 10 (HTTP 429). Keep results_wanted modest.

Usage:
  python3 scripts/jobspy_fetch.py                      # 24h, default terms
  python3 scripts/jobspy_fetch.py --hours 6            # last 6 hours only
  python3 scripts/jobspy_fetch.py --terms "data engineer,analytics engineer"
  python3 scripts/jobspy_fetch.py --no-descriptions    # faster, no JD text
"""
import argparse
import os
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import job_store
from job_filters import (TARGET_TERMS as DEFAULT_TERMS, NOISE_TITLES as NOISE,
                         RELEVANT_TITLES as RELEVANT, is_northern_ireland)

# Titles that are out of scope for a 3-YOE profile. Fit is still scored by
# required-skills overlap, not title -- this only trims obvious noise.
# Calibrated 2026-08-25 against 98 LinkedIn rows carrying a real date_posted.
# Max observed id per date climbed 4451M (11 Aug) -> 4458M (24 Aug), ~3M ids/day.
# Bump this when the calibration goes stale (re-run with --calibrate).
LINKEDIN_FRESH_ID = 4_458_000_000

NOISE = ("director", "head of", "vp ", "vice president", "chief", "principal",
         "intern", "internship", "graduate programme", "apprentice")



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24, help="max posting age in hours")
    ap.add_argument("--terms", default=",".join(DEFAULT_TERMS))
    ap.add_argument("--location", default="Ireland")  # Ireland, not Dublin: the candidate is relocation-open
    ap.add_argument("--results", type=int, default=25, help="results wanted per site per term")
    ap.add_argument("--no-descriptions", action="store_true")
    # NB: board employment-type tags are unreliable -- see module docstring.
    ap.add_argument("--job-type", default=None,
                    choices=["fulltime", "parttime", "contract", "internship", "temporary"],
                    help="filter by employment type; 'fulltime' excludes contract/temp")
    ap.add_argument("--out", default=None)
    ap.add_argument("--include-contract", action="store_true",
                    help="include roles whose JD reads as contract/day-rate. OFF by default: "
                         "CSEP needs a 2-year offer and Irish contracts usually demand full "
                         "work authorisation from day one.")
    args = ap.parse_args()

    try:
        from jobspy import scrape_jobs
        import pandas as pd
    except ImportError:
        print("JobSpy not installed. Run: pip3 install python-jobspy", file=sys.stderr)
        return 1

    terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    frames = []
    for term in terms:
        try:
            df = scrape_jobs(
                site_name=["indeed", "linkedin"],
                search_term=term,
                location=args.location,
                results_wanted=args.results,
                hours_old=args.hours,
                country_indeed="Ireland",
                linkedin_fetch_description=not args.no_descriptions,
                job_type=args.job_type,
            )
        except Exception as exc:
            print(f"  ! '{term}' failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if len(df):
            df = df.copy()
            df["matched_term"] = term
            frames.append(df)
        print(f"  {term}: {len(df)}")

    if not frames:
        print("No results.")
        return 0

    all_df = pd.concat(frames, ignore_index=True)
    before = len(all_df)
    all_df = all_df.drop_duplicates(subset=["title", "company"], keep="first")
    # Recency confidence, because LinkedIn lies about dates (see module docstring).
    jid = all_df["job_url"].str.extract(r"/jobs/view/(\d+)")[0]
    all_df["jid"] = pd.to_numeric(jid, errors="coerce")

    def recency(r):
        if r["site"] == "indeed" and pd.notna(r.get("date_posted")):
            return f"VERIFIED {r['date_posted']}"
        if r["site"] == "linkedin":
            if pd.notna(r["jid"]) and r["jid"] >= LINKEDIN_FRESH_ID:
                return "LIKELY FRESH (high job id)"
            return "UNVERIFIED (LinkedIn stripped the date; may be a repost)"
        return "UNVERIFIED"

    all_df["recency"] = all_df.apply(recency, axis=1)

    # The board's fulltime/contract tag lies, so re-derive it from the JD wording.
    CONTRACT_RE = (r"day rate|per day|/day|\bdrc\b|month contract|fixed[- ]term"
                   r"|\bftc\b|contract role|daily rate")
    desc_l = all_df.get("description", pd.Series("", index=all_df.index)).fillna("").str.lower()
    title_l = all_df["title"].str.lower()
    all_df["contract_flag"] = (desc_l.str.contains(CONTRACT_RE, regex=True)
                               | title_l.str.contains(CONTRACT_RE, regex=True))
    # Most-trustworthy-and-freshest first.
    all_df["_rank"] = all_df["recency"].str.startswith("VERIFIED").map({True: 0, False: 1})
    all_df = all_df.sort_values(["_rank", "jid"], ascending=[True, False])

    # Northern Ireland is the UK - an Irish work permission does not cover it (job_filters.py).
    ni_mask = all_df["location"].astype(str).apply(is_northern_ireland)
    ni_rows = all_df[ni_mask]
    all_df = all_df[~ni_mask]

    lower = all_df["title"].str.lower()
    mask = (~lower.str.contains("|".join(NOISE), na=False)
            & lower.str.contains("|".join(RELEVANT), na=False))
    kept, dropped = all_df[mask], all_df[~mask]

    # Permanent full-time is the target, contract is a fallback.
    contract_rows = kept[kept["contract_flag"]] if "contract_flag" in kept else kept.iloc[0:0]
    if not args.include_contract and len(contract_rows):
        kept = kept[~kept["contract_flag"]]

    # Every sourced row goes into the deduplicating store, including rows this run
    # trims. A role trimmed as out-of-level today may be worth a second look, and
    # storing it again costs nothing because the store dedupes on URL.
    store_conn = job_store.connect()
    run_tag = os.path.basename(args.out).replace(".md", "") if args.out else "jobspy"
    n_new = 0
    for rows in (kept, contract_rows, dropped):
        for _, r in rows.iterrows():
            sal_v = None
            if r.get("min_amount") and str(r.get("min_amount")) != "nan":
                sal_v = (f"{r.get('currency') or ''}{r.get('min_amount')}-"
                         f"{r.get('max_amount')} {r.get('interval') or ''}")
            _, was_new = job_store.upsert(
                store_conn,
                {"title": r.get("title"), "company": r.get("company"),
                 "location": r.get("location"), "site": r.get("site"),
                 "url": r.get("job_url"), "salary": sal_v,
                 "is_contract": bool(r.get("contract_flag")),
                 "description": r.get("description") if isinstance(r.get("description"), str) else ""},
                run_tag=run_tag, recency=str(r.get("recency") or ""),
                term=str(r.get("matched_term") or ""))
            n_new += was_new
    store_conn.commit()

    out = args.out or os.path.join(BASE_DIR, "sourcing", f"jobspy_matches_{date.today()}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(f"# JobSpy Multi-Board Matches — {date.today()}\n\n")
        fh.write(f"**Sources**: Indeed + LinkedIn (public guest endpoint, no login)\n")
        fh.write(f"**Location**: {args.location} | **Max age**: {args.hours}h"
                 f"{' | **Type**: ' + args.job_type if args.job_type else ''}\n")
        fh.write(f"**Terms**: {', '.join(terms)}\n\n")
        fh.write(f"{before} raw, {len(all_df)} after dedupe, "
                 f"{len(kept)} in scope (permanent), {len(dropped)} trimmed as "
                 f"out-of-level or off-domain, {len(contract_rows)} set aside as contract.\n\n")
        fh.write("> **Recency caveat**: only rows marked VERIFIED carry a real posting "
                 "date (Indeed). LinkedIn strips dates and returns reposts, so its rows "
                 "are graded by job id and must be confirmed on the listing before being "
                 "called fresh.\n\n")
        fh.write(f"> **Full JD text is NOT inline.** It lives deduplicated in "
                 f"`data/jobs.db` ({n_new} new this run). Pull one with "
                 f"`python3 scripts/job_store.py --jd <id> --out jd.txt`; search with "
                 f"`--search <term>`. Inline JDs made these files 500KB+ each and "
                 f"re-stored the same role up to 10 times.\n\n")
        fh.write("> UNSCREENED. Score by required-skills overlap against "
                 "`data/master_experience_claims.json`, never by title. "
                 "Check for ghost/repost patterns before tailoring.\n\n---\n\n")

        for i, (_, r) in enumerate(kept.iterrows(), 1):
            sal = ""
            if r.get("min_amount") and str(r.get("min_amount")) != "nan":
                sal = f" | {r.get('currency') or ''}{r.get('min_amount')}-{r.get('max_amount')} {r.get('interval') or ''}"
            fh.write(f"### {i}. {r['title']} — {r['company']}\n")
            fh.write(f"- **Site**: {r['site']} | **Location**: {r.get('location')}{sal}\n")
            fh.write(f"- **Recency**: {r['recency']} (term: {r['matched_term']})\n")
            if r.get("contract_flag"):
                fh.write("- **⚠️ READS AS CONTRACT / DAY-RATE** despite the board's tag. "
                         "Confirm before treating as permanent.\n")
            fh.write(f"- **URL**: {r.get('job_url')}\n")
            desc = r.get("description")
            jid = job_store.make_job_id(r.get("job_url"), r.get("company"),
                                        r.get("title"), r.get("location"))
            if isinstance(desc, str) and desc.strip():
                first = " ".join(desc.split())[:260]
                fh.write(f"- **JD** ({len(desc)} chars, stored): "
                         f"`python3 scripts/job_store.py --jd {jid} --out jd.txt`\n")
                fh.write(f"- {first}...\n")
            else:
                fh.write(f"- **JD**: not captured. store id `{jid}`\n")
            fh.write("\n")

        if len(contract_rows):
            fh.write("---\n\n## Set aside: reads as CONTRACT / day-rate\n\n"
                     "Permanent is the priority: CSEP needs a 2-year offer, "
                     "and Irish contracts usually require full work authorisation from day one. "
                     "Re-run with `--include-contract` if speed-to-income is being prioritised.\n\n")
            for _, r in contract_rows.iterrows():
                fh.write(f"- {r['title']} — {r['company']} {r.get('job_url')}\n")
            fh.write("\n")

        if len(dropped):
            fh.write("---\n\n## Trimmed (out-of-level seniority, or not a data role)\n\n")
            for _, r in dropped.iterrows():
                fh.write(f"- {r['title']} — {r['company']}\n")

    print(f"\n{len(kept)} in-scope postings. Index: {out}")
    print(f"Store: {n_new} new unique jobs -> data/jobs.db "
          f"(python3 scripts/job_store.py --stats)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
