#!/usr/bin/env python3
"""
fit_decision.py - a typed, auditable APPLY / STRETCH / SKIP decision for a JD.

WHY: hosted decision models are valuable for their SHAPE, not their hosting:
every decision is one of three typed primitives, and you branch on the value
instead of parsing prose. That shape is reproduced here, run locally, so no JD
or claim text leaves the machine.

  noul   - a yes/no gate with a confidence 0.0-1.0
  score  - an ordered 0-3 band
  choice - one label from a fixed set (the final verdict)

The gates below are not invented. Each one encodes a real miss seen in practice:
  * salary hidden in prose      -> "non-negotiable start at the minimum of the scale"
  * domain hidden behind title  -> a "Data Analyst" title that is really a SOC role
  * "Stamp 4 or EU citizen"     -> unwinnable on a graduate work permission
  * "right to work AT TIME OF
     APPLICATION"               -> excludes anyone whose permission starts later
  * years bar                   -> 5+ / 7-8+ against a 3-year profile
  * seniority in the title      -> Architect / Lead / Director are out of level
  * Northern Ireland            -> an Irish (Republic) permission does not cover the UK

Usage:
  python3 scripts/fit_decision.py --jd data/jds/x.txt
  python3 scripts/fit_decision.py --jd x.txt --overlap 3 --domain 2 --json
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from candidate import PROFILE  # noqa: E402

YOE = PROFILE["years_experience"]
SALARY_FLOOR = PROFILE["salary_floor"]
PERMISSION = PROFILE["work_permission"]
PERMIT_SALARY_ROUTE = 68911

NI_CITIES = ["belfast", "derry", "londonderry", "lisburn", "omagh", "ballymena",
             "dundonald", "newry", "craigavon", "antrim", "bangor, co"]

VISA_HARD = re.compile(
    r"(stamp\s*4|eu\s+citizen|indefinitel|without\s+any\s+restriction|"
    r"unrestricted\s+right|permanent\s+resident|no\s+sponsorship\s+(is\s+)?(available|offered)|"
    r"right\s+to\s+work.{0,60}at\s+the\s+time\s+of\s+application)", re.I)
VISA_SOFT = re.compile(r"(right to work|work authoris|work authoriz|eligible to work|sponsor)", re.I)

SENIOR_TITLE = re.compile(
    r"\b(architect|director|head of|principal|vice president|\bvp\b|chief|"
    r"senior manager|lead\b|team lead|manager)\b", re.I)
JUNIOR_TITLE = re.compile(r"\b(intern|graduate|placement|co-?op|trainee|apprentice)\b", re.I)

YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?year", re.I)
# "EUR 53,072 to 76,227" / "€60,185 - €70,718" / "45 - 50k"
SAL = re.compile(r"(?:eur|€)\s?([\d][\d,\.]{2,})\s*(?:-|to|–)\s*(?:eur|€)?\s?([\d][\d,\.]{2,})", re.I)
SAL_MIN_TRAP = re.compile(r"(non[- ]negotiable|start at the minimum|minimum of the scale|"
                          r"first point of the scale)", re.I)
CONTRACT = re.compile(r"(day rate|daily rate|fixed[- ]term|\bftc\b|contract\b|month contract|"
                      r"\d+\s*month[s]?\s*(contract|ftc))", re.I)


def num(s):
    try: return float(str(s).replace(",", "").replace(".", "") if str(s).count(".") == 1 and len(str(s).split(".")[-1]) == 3 else str(s).replace(",", ""))
    except ValueError: return None


def noul(name, value, conf, why):
    return {"type": "noul", "q": name, "noul": bool(value), "confidence": round(conf, 2), "why": why}


def score(name, v, levels, why):
    return {"type": "score", "q": name, "score": v, "of": levels, "why": why}


def evaluate(text, title="", overlap=None, domain=None):
    t = text or ""
    low = t.lower()
    out, blockers, warnings = [], [], []

    # --- noul: location is in the Republic -------------------------------
    ni = [c for c in NI_CITIES if c in low]
    ok = not ni
    out.append(noul("location_in_republic", ok, 0.99 if ok else 0.97,
                    "Republic of Ireland" if ok else f"Northern Ireland ({ni[0]}): {PERMISSION} does not cover the UK"))
    if not ok: blockers.append(f"Northern Ireland - {PERMISSION} does not permit working there")

    # --- noul: visa wording is survivable --------------------------------
    hard = VISA_HARD.findall(t)
    if hard:
        phrase = " ".join(x for x in (hard[0] if isinstance(hard[0], tuple) else (hard[0],)) if x)
        out.append(noul("visa_compatible", False, 0.93, f"hard requirement found: '{phrase.strip()}'"))
        blockers.append(f"visa wording is a knockout: '{phrase.strip()}'")
    else:
        soft = bool(VISA_SOFT.search(t))
        out.append(noul("visa_compatible", True, 0.72 if soft else 0.9,
                        "authorisation mentioned but not exclusionary - confirm" if soft
                        else "no authorisation language in the JD"))
        if soft: warnings.append(f"JD mentions work authorisation without excluding {PERMISSION} - ask before assuming")

    # --- noul: years bar is met ------------------------------------------
    yrs = sorted({int(m) for m in YEARS.findall(t) if 1 <= int(m) <= 20})
    bar = min(yrs) if yrs else None
    if bar is None:
        out.append(noul("years_met", True, 0.6, "no years figure stated, which helps"))
    else:
        ok = bar <= YOE
        out.append(noul("years_met", ok, 0.9,
                        f"JD asks {bar}+ years, candidate has {YOE}" + ("" if ok else " - short by %d" % (bar - YOE))))
        if not ok and bar - YOE >= 3: blockers.append(f"asks {bar}+ years vs {YOE} - a {bar-YOE} year gap")
        elif not ok: warnings.append(f"asks {bar}+ years vs {YOE}")

    # --- noul: in level ---------------------------------------------------
    st, jt = SENIOR_TITLE.search(title or ""), JUNIOR_TITLE.search(title or "")
    if st:
        out.append(noul("in_level", False, 0.88, f"title carries '{st.group(0)}' - above a 3-YOE band"))
        blockers.append(f"out of level: title says '{st.group(0)}'")
    elif jt:
        out.append(noul("in_level", False, 0.85, f"title carries '{jt.group(0)}' - below level"))
        warnings.append(f"below level: '{jt.group(0)}'")
    else:
        out.append(noul("in_level", True, 0.8, "title reads mid-level"))

    # --- noul: clears the salary floor -----------------------------------
    m = SAL.search(t)
    if m:
        lo, hi = num(m.group(1)), num(m.group(2))
        # DAY RATES ARE NOT ANNUAL SALARIES. A contract quoted at "EUR 550 - EUR 650
        # per day" was once read as EUR 550/year and failed the floor by a mile.
        # Annualise at 220 billable days before comparing to the floor.
        DAY_RATE = re.compile(r"(per day|/\s*day|\bp\.?d\.?\b|day rate|daily rate)", re.I)
        daily = bool(DAY_RATE.search(t)) and lo and lo < 2000
        if daily:
            lo, hi = lo * 220, (hi * 220 if hi else None)
        trap = bool(SAL_MIN_TRAP.search(t))
        effective = lo if trap else lo
        ok = effective and effective >= SALARY_FLOOR
        why = f"band {lo:,.0f}-{hi:,.0f}" + (" (day rate annualised at 220 days)" if daily else "")
        if trap: why += "; JD says starting point is NON-NEGOTIABLE at the minimum, so the real offer is the floor of the band"
        out.append(noul("clears_salary_floor", bool(ok), 0.9, why))
        if not ok: blockers.append(f"starting salary {effective:,.0f} is below the {SALARY_FLOOR:,} floor")
        elif hi and hi >= PERMIT_SALARY_ROUTE:
            warnings.append(f"top of band {hi:,.0f} clears the {PERMIT_SALARY_ROUTE:,} non-CSOL permit route")
    else:
        out.append(noul("clears_salary_floor", True, 0.35, "no salary published - UNVERIFIED, ask before investing"))
        warnings.append("no salary published - confirm it clears the floor before tailoring")

    # --- choice: employment type -----------------------------------------
    ctype = "contract" if CONTRACT.search(t) else "permanent"
    out.append({"type": "choice", "q": "employment_type", "choice": ctype, "of": ["permanent", "contract"],
                "why": "permanent ranks first; contract is in scope since 2026-09-18"})

    # --- scores: the judgment half, supplied by the reader ---------------
    if overlap is not None:
        out.append(score("claims_overlap", overlap, 3,
                         "how much of the JD's REQUIRED skills trace to master_experience_claims.json"))
    if domain is not None:
        out.append(score("domain_match", domain, 3,
                         "does the candidate know the business domain, not just the mechanics"))

    # --- choice: the verdict ---------------------------------------------
    if blockers:
        verdict, conf = "SKIP", 0.9
    elif overlap is None or domain is None:
        verdict, conf = "NEEDS_JUDGEMENT", 0.5
    elif overlap >= 3 and domain >= 2 and not warnings:
        verdict, conf = "APPLY_TIER1", 0.85
    elif overlap >= 2:
        verdict, conf = ("APPLY_TIER2", 0.7) if domain >= 1 else ("STRETCH", 0.55)
    else:
        verdict, conf = "SKIP", 0.75
    out.append({"type": "choice", "q": "verdict", "choice": verdict, "confidence": conf,
                "of": ["APPLY_TIER1", "APPLY_TIER2", "STRETCH", "SKIP", "NEEDS_JUDGEMENT"]})
    return {"title": title, "decisions": out, "blockers": blockers, "warnings": warnings,
            "verdict": verdict, "confidence": conf}


def render(r):
    print("\n" + "=" * 70)
    print(f" FIT DECISION  —  {r['title'][:56] or '(untitled)'}")
    print("=" * 70)
    for d in r["decisions"]:
        if d["type"] == "noul":
            mark = "PASS" if d["noul"] else "FAIL"
            print(f"  noul   {d['q']:24s} {mark:4s} · {d['confidence']:.2f}   {d['why']}")
        elif d["type"] == "score":
            print(f"  score  {d['q']:24s} {d['score']}/{d['of']}        {d['why']}")
        else:
            c = f" · {d['confidence']:.2f}" if "confidence" in d else ""
            print(f"  choice {d['q']:24s} {d['choice']}{c}")
            if d.get("why"): print(f"         {' '*24} {d['why']}")
    if r["blockers"]:
        print("\n  BLOCKERS:")
        for b in r["blockers"]: print(f"    x {b}")
    if r["warnings"]:
        print("\n  WARNINGS:")
        for w in r["warnings"]: print(f"    ! {w}")
    print(f"\n  >>> {r['verdict']}  (confidence {r['confidence']:.2f})")
    if r["verdict"] == "NEEDS_JUDGEMENT":
        print("      Pass --overlap 0-3 and --domain 0-3 after reading the JD to resolve.")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--overlap", type=int, choices=range(4))
    ap.add_argument("--domain", type=int, choices=range(4))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    text = open(a.jd, encoding="utf-8", errors="replace").read()
    title = a.title or next((l.strip() for l in text.splitlines() if l.strip()), "")
    r = evaluate(text, title, a.overlap, a.domain)
    print(json.dumps(r, indent=2)) if a.json else render(r)
    return 0 if r["verdict"] != "SKIP" else 2


if __name__ == "__main__":
    sys.exit(main())
