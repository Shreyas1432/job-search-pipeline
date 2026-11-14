#!/usr/bin/env python3
"""
pipeline_review.py - "are we doing this correctly?" answered from our own outcome data.

WHY THIS EXISTS: the question was whether a hosted decision model (Jev /
TypeSafe AI) could tell us how well we are doing. The honest finding was that the
blocker is not a missing model, it is that the tracker cannot be measured:
  - the status column held ~30 distinct free-text values for ~6 real states
    ("Applied", "Submitted / Applied", "APPLIED 2026-08-31", ...)
  - ATS scores live inside prose notes, not a field
  - there is no applied-date vs responded-date, so time-to-response is unknowable

A calibrated model on top of unmeasurable data produces confident numbers with no
grounding. So: normalise first, measure second, and only then consider a model.

  python3 scripts/pipeline_review.py
  python3 scripts/pipeline_review.py --by-score
"""
import argparse, csv, re, sys
from collections import Counter, defaultdict
from datetime import date, datetime

TRACKER = "data/application_tracker.csv"

# One real state per bucket. Order matters: first match wins.
STATES = [
    ("OFFER",     re.compile(r"\boffer\b", re.I)),
    ("INTERVIEW", re.compile(r"interview|phone screen|loop|onsite", re.I)),
    ("REJECTED",  re.compile(r"reject|unsuccessful|declined by", re.I)),
    ("CLOSED",    re.compile(r"closed|no longer accept|do not (apply|prioritise)|demoted", re.I)),
    ("APPLIED",   re.compile(r"applied|submitted", re.I)),
    ("OUTREACH",  re.compile(r"messaged|awaiting response|warm channel", re.I)),
    ("BUILT",     re.compile(r"prepared|draft ready", re.I)),
    ("SOURCED",   re.compile(r"sourced|research", re.I)),
]
ATS_RE = re.compile(r"ATS (\d{2,3})\s*/\s*100", re.I)
TIER_RE = re.compile(r"tier\s*-?\s*([12])", re.I)


def norm_state(raw):
    for name, pat in STATES:
        if pat.search(raw or ""):
            return name
    return "UNKNOWN"


def load(path=TRACKER):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        r["_state"] = norm_state(r.get("status", ""))
        m = ATS_RE.search(r.get("notes", "") or "")
        r["_ats"] = int(m.group(1)) if m else None
        t = TIER_RE.search(r.get("fit_level", "") or "")
        r["_tier"] = f"Tier {t.group(1)}" if t else "unset"
    return rows


def pct(n, d):
    return f"{100*n/d:.0f}%" if d else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", default=TRACKER)
    ap.add_argument("--by-score", action="store_true",
                    help="does a higher ATS score actually correlate with a response?")
    a = ap.parse_args()
    rows = load(a.tracker)

    print("\n" + "=" * 68)
    print(" PIPELINE REVIEW  —  measured from data/application_tracker.csv")
    print("=" * 68)

    st = Counter(r["_state"] for r in rows)
    print(f"\n[Funnel]  {len(rows)} tracked roles")
    for k in ["SOURCED", "BUILT", "OUTREACH", "APPLIED", "INTERVIEW", "OFFER", "REJECTED", "CLOSED", "UNKNOWN"]:
        if st.get(k):
            print(f"   {st[k]:3d}  {k}")

    # An application has 'landed' once it reached a human decision either way.
    applied = [r for r in rows if r["_state"] in ("APPLIED", "INTERVIEW", "OFFER", "REJECTED")]
    decided = [r for r in applied if r["_state"] in ("INTERVIEW", "OFFER", "REJECTED")]
    interviews = [r for r in applied if r["_state"] in ("INTERVIEW", "OFFER")]
    silent = [r for r in applied if r["_state"] == "APPLIED"]

    print(f"\n[Conversion]")
    print(f"   Applied or beyond        : {len(applied)}")
    print(f"   Heard back (any outcome) : {len(decided)}  ({pct(len(decided), len(applied))} of applied)")
    print(f"   Reached interview        : {len(interviews)}  ({pct(len(interviews), len(applied))} of applied)")
    print(f"   Still silent             : {len(silent)}")
    if decided:
        print(f"   Interview rate among decided: {pct(len(interviews), len(decided))}")

    # The honest caveat, printed every time so nobody over-reads the numbers.
    if len(applied) < 30:
        print(f"\n   ⚠️  {len(applied)} applications is a SMALL SAMPLE. Treat every rate above as")
        print(f"      directional, not statistical. One outcome moves it several points.")

    scored = [r for r in applied if r["_ats"] is not None]
    print(f"\n[Data quality]")
    print(f"   Applications with a recorded ATS score : {len(scored)}/{len(applied)}")
    missing_date = sum(1 for r in applied if not (r.get("date_added") or "").strip())
    print(f"   Applications missing a date            : {missing_date}")
    print(f"   Distinct raw status strings            : {len(set(r.get('status','') for r in rows))}"
          f"  (normalised to {len(set(r['_state'] for r in rows))} real states)")
    print("   NOTE: there is no responded-date column, so time-to-response is UNKNOWABLE.")
    print("         Add one before trusting any speed claim.")

    if a.by_score:
        print(f"\n[Does a higher ATS score actually get a response?]")
        if len(scored) < 8:
            print(f"   Only {len(scored)} scored applications. Not enough to say anything honest.")
        else:
            bands = defaultdict(lambda: {"n": 0, "heard": 0})
            for r in scored:
                b = "90+" if r["_ats"] >= 90 else "80-89" if r["_ats"] >= 80 else "<80"
                bands[b]["n"] += 1
                if r["_state"] in ("INTERVIEW", "OFFER", "REJECTED"):
                    bands[b]["heard"] += 1
            for b in ["90+", "80-89", "<80"]:
                d = bands.get(b)
                if d and d["n"]:
                    print(f"   ATS {b:6s}: {d['n']:2d} applied, {d['heard']:2d} heard back  ({pct(d['heard'], d['n'])})")
            print("   Reading it: a high score means the DOCUMENT parses and matches. It cannot")
            print("   buy experience the JD requires. Check rejections for the real reason.")

    print(f"\n[By tier]")
    for tier, grp in sorted(defaultdict(list, {k: [r for r in applied if r["_tier"] == k]
                                               for k in set(r["_tier"] for r in applied)}).items()):
        if grp:
            iv = sum(1 for r in grp if r["_state"] in ("INTERVIEW", "OFFER"))
            print(f"   {tier:8s}: {len(grp):2d} applied, {iv} reached interview")

    print("\n" + "=" * 68)
    print(" What this can and cannot tell you")
    print("=" * 68)
    print(" CAN : how many applications convert, which tiers convert, whether the")
    print("       document gates (ATS/claims) are being passed before sending.")
    print(" CANNOT: why a rejection happened. Nine of the recorded rejections carry no")
    print("       stated reason. Until reasons are captured, no model - hosted or")
    print("       local - can tell you what to change. Capture the reason when it")
    print("       arrives; that single habit is worth more than any scoring model.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
