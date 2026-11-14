#!/usr/bin/env python3
"""
ats_analyzer.py (2026-08-10)
The "proper" ATS system — a layer ON TOP of the existing ats_score.py, not a
rewrite. It REUSES ats_score's matching helpers and skills_dictionary's
vocab/synonyms, and adds the four things keyword-coverage alone misses:

  1. JD-driven keyword extraction BEYOND the fixed vocab (frequency-weighted
     uni/bi/tri-grams from the JD itself) — so a JD-specific term that isn't in
     SKILL_VOCAB is no longer invisible.
  2. Weighted coverage — required keywords weighted by how often the JD repeats
     them (an ATS ranks harder on the terms the JD stresses).
  3. Title match — resume headline vs the JD's job title (ATS weights title heavily).
  4. Parse-safety lint — checks the COMPILED PDF for the things that silently
     break ATS parsing (multi-column scramble, tables, content in header/footer
     margins, missing/garbled contact info, image-only/empty text).

Plus an honesty-preserving keyword-gap report: a missing JD keyword is labelled
EARNABLE (backed by master_experience_claims.json -> add it) vs NOT-TRUE
(not backed -> never keyword-stuff it; upskill or skip the role).

Usage:
  python3 scripts/ats_analyzer.py --resume resumes/md/resume_x.md --jd-file jd.txt
  python3 scripts/ats_analyzer.py --resume resumes/md/resume_x.md --config data/ats_configs/x.json
  (PDF auto-detected from the resume path; pass --pdf to override.)
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# --- REUSE existing code (build on it, don't restart) ---
from ats_score import (
    normalize, build_pattern, synonym_expand, hit,
    extract_pdf_text, auto_extract_keywords, resolve_pdf_path,
)
from skills_dictionary import SKILL_VOCAB, SYNONYM_GROUPS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAIMS_FILE = os.path.join(BASE_DIR, "data", "master_experience_claims.json")

# Boilerplate/stopwords to strip from JD keyword extraction. Kept lean;
# SKILL_VOCAB hits are added back regardless so real skills survive.
STOPWORDS = set("""
a an the and or of to in on for with at by from as is are be been being this that these those
you your our we they it its will can may should must have has had do does role job position team
work working experience years year strong good excellent ability able across within including
etc using use used help support build building develop developing deliver delivering delivered ideal
candidate looking seeking join company business data new all any per via into out up down more
most least both each other such who what which their them there here about over under between
requirements responsibilities skills essential desirable preferred plus bonus advantageous
opportunity opportunities environment environments fast paced paced great every day days week weeks month
please apply email cv resume contact benefits salary hybrid remote onsite dublin ireland office
demonstrated demonstrable proven solid strong knowledge technologies technology complex large
scale datasets dataset hands driven drive closely non technical field provider facing teams timely
various level levels standard related modern tools tool solutions solution operational actionable
senior junior principal analyst engineer engineering scientist developer specialist manager lead
big high degree understanding proficiency track record delivering results multiple priorities
collaborate collaboratively stakeholders stakeholder communicate communication interpersonal
proactively anticipate customer needs approaches methodologies gaps process improvement automation
""".split())


# ---------------------------------------------------------------------------
# 1 + 2. JD keyword extraction (weighted, beyond the fixed vocab)
# ---------------------------------------------------------------------------
def _tokens(text):
    return re.findall(r"[a-z0-9][a-z0-9+.#/-]*", text.lower())


def extract_jd_keywords_weighted(jd_text, top_n=25):
    """Return [(term, weight)] combining (a) SKILL_VOCAB terms actually present
    in the JD and (b) the JD's own frequent uni/bi/tri-grams not in the
    stoplist. Weight = JD frequency (multi-word phrases get a small boost, since
    a named tool/skill phrase matters more than a lone common word)."""
    norm = normalize(jd_text)
    toks = _tokens(jd_text)

    # (a) canonical skills from our vocab that appear in the JD
    vocab_hits = {term: len(build_pattern(term).findall(norm)) or 1
                  for term in SKILL_VOCAB if hit(term, norm)}

    # (b) frequency n-grams from the JD itself (captures novel terms)
    grams = Counter()
    content = [t for t in toks if t not in STOPWORDS and len(t) > 2]
    for t in content:
        grams[t] += 1
    for n, boost in ((2, 1.4), (3, 1.7)):
        for i in range(len(toks) - n + 1):
            window = toks[i:i + n]
            if any(w in STOPWORDS for w in window):
                continue
            if all(len(w) > 1 and not w.endswith(".") for w in window):
                grams[" ".join(window)] += boost

    # merge: vocab hits are trusted skill names; scale them up so they rank well
    weights = {}
    for term, c in vocab_hits.items():
        weights[term] = c * 3.0
    for term, c in grams.items():
        # don't double-count a gram that is just a vocab term surface form
        if any(term in synonym_expand(v) for v in vocab_hits):
            continue
        weights[term] = weights.get(term, 0) + c

    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    # drop pure-number grams and 1-char noise
    ranked = [(t, w) for t, w in ranked if not re.fullmatch(r"[\d.]+", t)]
    return ranked[:top_n]


# ---------------------------------------------------------------------------
# 3. Title match
# ---------------------------------------------------------------------------
def extract_jd_title(jd_text):
    lines = [l.strip() for l in jd_text.splitlines() if l.strip()]
    for l in lines[:6]:
        m = re.search(r"(?:job title|role|position|title)\s*[:\-]\s*(.+)", l, re.I)
        if m:
            return m.group(1).strip()
    for l in lines[:3]:
        if 2 <= len(l.split()) <= 8 and not l.endswith((".", ":")):
            return l
    m = re.search(r"hiring (?:a|an)\s+([A-Za-z /&-]{4,40})", jd_text, re.I)
    return m.group(1).strip() if m else (lines[0] if lines else "")


TITLE_WORDS = {"data", "analyst", "analytics", "engineer", "engineering", "business",
               "intelligence", "bi", "reporting", "insights", "scientist", "science",
               "developer", "quality", "governance", "senior", "junior", "lead", "warehouse"}


def title_match(resume_text, jd_text):
    jd_title = extract_jd_title(jd_text)
    jd_core = {w for w in _tokens(jd_title) if w in TITLE_WORDS}
    # resume "title" = headline / first heading / summary role line
    head = "\n".join(resume_text.splitlines()[:12]).lower()
    res_core = {w for w in _tokens(head) if w in TITLE_WORDS}
    if not jd_core:
        return 1.0, jd_title, sorted(res_core)  # can't determine -> don't penalise
    overlap = jd_core & res_core
    return len(overlap) / len(jd_core), jd_title, sorted(jd_core - res_core)


# ---------------------------------------------------------------------------
# 4. Parse-safety lint (on the compiled PDF)
# ---------------------------------------------------------------------------
def parse_safety_lint(pdf_path):
    findings = []
    try:
        import pdfplumber
    except ImportError:
        return ["pdfplumber not installed — cannot run parse-safety lint."], None
    if not pdf_path or not os.path.exists(pdf_path):
        return ["No compiled PDF found — compile first, then re-lint (ATS parses the PDF, not the .md)."], None

    text = extract_pdf_text(pdf_path) or ""
    if len(text.strip()) < 200:
        findings.append("PDF text extraction is nearly empty — resume may be image-based/scanned. An ATS will read NOTHING. Fix the compile.")

    if not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        findings.append("No email address found in the extracted text — contact info may be in an unparseable region (header/graphic).")
    if not re.search(r"(\+?\d[\d ()-]{7,}\d)", text):
        findings.append("No phone number found in extracted text (ok if intentional; otherwise it may be in an unparseable region).")

    with pdfplumber.open(pdf_path) as pdf:
        for pageno, page in enumerate(pdf.pages, 1):
            h = page.height
            words = page.extract_words() or []
            if words:
                # header/footer content: only the extreme ~28pt edge zone (~0.4in),
                # where running headers/footers/page-numbers live — NOT normal tight
                # body margins (which start ~0.5-0.75in in and shouldn't trigger).
                edge = 28
                hf = [w for w in words if w["top"] < edge or w["bottom"] > h - edge]
                if len(hf) > 3:
                    sample = " ".join(w["text"] for w in hf[:8])
                    findings.append(f"p{pageno}: {len(hf)} words in the extreme header/footer margin (e.g. \"{sample}\") — many ATS parsers drop these. Keep real content out of the top/bottom ~0.4in.")
                # crude multi-column detection: words clustered in left AND right thirds, sparse middle
                W = page.width
                centers = [(w["x0"] + w["x1"]) / 2 for w in words]
                left = sum(1 for c in centers if c < W / 3)
                right = sum(1 for c in centers if c > 2 * W / 3)
                mid = sum(1 for c in centers if W / 3 <= c <= 2 * W / 3)
                if left > 0.25 * len(centers) and right > 0.25 * len(centers) and mid < 0.2 * len(centers):
                    findings.append(f"p{pageno}: possible MULTI-COLUMN layout — parsers read across columns and scramble order. Prefer a single column. (Heuristic; verify visually.)")
            try:
                tables = page.find_tables()
                if tables:
                    findings.append(f"p{pageno}: {len(tables)} table(s) detected — content inside tables is often mis-parsed. Put skills/dates in plain text.")
            except Exception:
                pass

    if not findings:
        findings.append("No parse-safety issues detected (single-column, no tables, contact info parseable, real text). ✅")
    return findings, text


# ---------------------------------------------------------------------------
# Human-voice / Irish-CV pre-send lint (embeds the 2026-08-19 strict-review
# blockers so they are caught mechanically on every ATS run, not from memory).
# These rules came out of a line-by-line review of sent resumes.
# ---------------------------------------------------------------------------
AI_TELLS = [
    "leverage", "spearhead", "passionate", "results-driven", "synergy",
    "cutting-edge", "seamless", "game-chang", "best-in-class", "world-class",
    "in today's", "tapestry", "realm of", "deep dive", "move the needle",
    "hit the ground running", "unlock", "elevate", "delve",
]


def human_voice_lint(md_text, pdf_path):
    """Return (blockers, warnings). Blockers must be clean before a resume is sent."""
    blockers, warnings = [], []
    pdf_text = extract_pdf_text(pdf_path) if pdf_path else ""
    haystack = (pdf_text or "") + "\n" + md_text
    em = haystack.count("—")
    if em:
        blockers.append(f"{em} em-dash(es) present (Hard Rule #8 / #1 AI-tell). Replace with comma, full stop, or ' | ' and recompile.")
    if not re.search(r"(\+?\d[\d ()\-]{7,}\d)", md_text):
        blockers.append("No phone number in the contact line (Irish CVs expect a mobile). Add one; never invent it.")
    low = md_text.lower()
    hits = sorted({w for w in AI_TELLS if w in low})
    if hits:
        warnings.append("AI-buzzword(s): " + ", ".join(hits) + " — rewrite in plain language.")
    if "what sets me apart" in low:
        warnings.append("'What Sets Me Apart' self-praise section present — cut it from any SENT resume (evidence over adjectives).")
    return blockers, warnings


# ---------------------------------------------------------------------------
# Real-ATS behaviours (2026-08-20): must-have weighting + knockout coverage,
# and a resume field-parse (structure) check. Commercial ATS (Workday,
# Greenhouse, Taleo, iCIMS) weight "essential/required" terms far above
# "desirable" ones and parse the resume into standard fields — mirror that.
# ---------------------------------------------------------------------------
REQ_MARKERS = ["essential", "required", "requirements", "must have", "must-have",
               "what you'll bring", "what you need", "you'll need", "key requirements",
               "qualifications", "basic qualifications", "what you'll do", "responsibilities"]
NICE_MARKERS = ["desirable", "nice to have", "nice-to-have", "preferred", "bonus",
                "advantageous", "would be a plus", "a plus", "beneficial"]


def required_section(jd_text):
    """Best-effort slice of the JD's essential/required text (before any desirable section)."""
    low = jd_text.lower()
    starts = [low.find(m) for m in REQ_MARKERS if low.find(m) != -1]
    if not starts:
        return ""
    start = min(starts)
    ends = [low.find(m) for m in NICE_MARKERS if low.find(m) > start]
    end = min(ends) if ends else start + 1600
    return jd_text[start:end]


def structure_lint(md_text):
    """What a resume-parsing ATS looks for as distinct fields. Returns missing field names."""
    low = md_text.lower()
    checks = {
        "contact email": bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", md_text)),
        "contact phone": bool(re.search(r"\+?\d[\d ()\-]{7,}\d", md_text)),
        "summary/profile": any(h in low for h in ["summary", "profile", "professional summary"]),
        "experience": any(h in low for h in ["experience", "employment", "work history"]),
        "skills": "skill" in low,
        "education": "education" in low,
        "dated roles (mm/yyyy)": bool(re.search(r"(19|20)\d{2}", md_text)),
    }
    return [k for k, v in checks.items() if not v]


# ---------------------------------------------------------------------------
# Coverage + honesty-preserving keyword gap
# ---------------------------------------------------------------------------
def load_claims_blob():
    if not os.path.exists(CLAIMS_FILE):
        return ""
    with open(CLAIMS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    anchors = (data.get("production_experience", []) + data.get("working_proficiency", [])
               + data.get("actively_building", []))
    return normalize(" ".join(anchors))


def weighted_coverage(resume_norm, weighted_keywords):
    total_w = sum(w for _, w in weighted_keywords) or 1
    hit_w = sum(w for term, w in weighted_keywords if hit(term, resume_norm))
    hits = [t for t, _ in weighted_keywords if hit(t, resume_norm)]
    misses = [t for t, _ in weighted_keywords if not hit(t, resume_norm)]
    return 100 * hit_w / total_w, hits, misses


def gap_report(misses, claims_blob):
    earnable, not_true = [], []
    for term in misses:
        (earnable if (claims_blob and hit(term, claims_blob)) else not_true).append(term)
    return earnable, not_true


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def analyze(resume_md, jd_text, pdf_path, config=None):
    with open(resume_md, encoding="utf-8") as f:
        md_text = f.read()

    pdf_text = extract_pdf_text(pdf_path) if pdf_path else None
    scored_text = pdf_text or md_text
    resume_norm = normalize(scored_text)
    source_label = "compiled PDF" if pdf_text else "markdown source (no PDF found — compile for a true ATS read)"

    # keywords: hand-curated config, else weighted JD extraction
    if config:
        weighted = [(k, 3.0) for k in config.get("required", [])] + \
                   [(k, 1.0) for k in config.get("nice_to_have", [])]
        extracted_note = "using hand-curated config keywords"
    else:
        weighted = extract_jd_keywords_weighted(jd_text)
        extracted_note = "auto-extracted + frequency-weighted from the JD"

    # Requirement-tier awareness: real ATS weight essential/required terms far above
    # desirables and effectively knock out on missed must-haves. Boost + track them.
    if config:
        required_terms = set(config.get("required", []))
    else:
        req_norm = normalize(required_section(jd_text)) if jd_text else ""
        required_terms = {t for t, _ in weighted if req_norm and hit(t, req_norm)}
    if required_terms:
        weighted = [(t, w * 1.8 if t in required_terms else w) for (t, w) in weighted]

    cov_pct, hits, misses = weighted_coverage(resume_norm, weighted)
    must = [(t, w) for (t, w) in weighted if t in required_terms]
    mh_pct, mh_hits, mh_miss = weighted_coverage(resume_norm, must) if must else (None, [], [])
    claims_blob = load_claims_blob()
    earnable, not_true = gap_report(misses, claims_blob)

    tmatch, jd_title, missing_title_words = (title_match(scored_text, jd_text) if jd_text else (1.0, "(n/a)", []))
    lint, _ = parse_safety_lint(pdf_path)
    parse_ok = all("✅" in f or "phone number" in f for f in lint)  # phone-only note isn't a real failure

    composite = 0.6 * cov_pct + 0.2 * (tmatch * 100) + 0.2 * (100 if parse_ok else 40)

    # ---- report ----
    print("=" * 70)
    print(f" ATS ANALYZER  —  {os.path.basename(resume_md)}")
    print(f" scored against: {source_label}")
    print("=" * 70)
    print(f"\n[Keywords] {extracted_note}")
    print(f"  Weighted coverage: {cov_pct:.0f}%   ({len(hits)}/{len(weighted)} terms present)")
    if must:
        print(f"  Must-have coverage: {mh_pct:.0f}%   ({len(mh_hits)}/{len(must)} essential terms present)")
        if mh_miss:
            print(f"  ⚠️ Missed MUST-HAVES (real-ATS knockout risk): {', '.join(mh_miss[:12])}")
    if earnable:
        print(f"  🟠 MISSING but you HAVE it (add to resume): {', '.join(earnable[:15])}")
    if not_true:
        print(f"  🔴 MISSING and NOT in your claims (do NOT keyword-stuff; upskill or skip): {', '.join(not_true[:15])}")

    print(f"\n[Title match] JD title: \"{jd_title}\"")
    print(f"  Score: {tmatch*100:.0f}%" + (f"   missing title words in resume headline: {', '.join(missing_title_words)}" if missing_title_words else "  ✅"))

    print("\n[Parse-safety lint] (what an ATS actually parses)")
    for f_ in lint:
        print(f"  - {f_}")

    blockers, voice_warn = human_voice_lint(md_text, pdf_path)
    print("\n[Human-voice / Irish-CV lint] (audit gate — must be clean before sending)")
    if blockers:
        for b in blockers:
            print(f"  🔴 BLOCKER: {b}")
    if voice_warn:
        for w in voice_warn:
            print(f"  🟠 {w}")
    if not blockers and not voice_warn:
        print("  ✅ No em-dashes, phone present, no buzzwords or self-praise.")

    struct_missing = structure_lint(md_text)
    print("\n[Structure / ATS field parse] (fields a resume-parsing ATS expects)")
    if struct_missing:
        print("  🟠 not clearly detected: " + ", ".join(struct_missing))
    else:
        print("  ✅ all standard fields present (contact email + phone, summary, experience, skills, education, dated roles)")

    print("\n" + "-" * 70)
    print(f" COMPOSITE ATS SCORE: {composite:.0f}/100")
    print("   (60% weighted keyword coverage · 20% title match · 20% parse-safety)")
    if blockers:
        print(f" ⛔ PRE-SEND: NOT READY — {len(blockers)} blocker(s) above must be fixed before this is sent.")
    else:
        print(" ✅ PRE-SEND: human-voice/Irish-CV gate clean.")
    print("=" * 70)
    return {"composite": composite, "coverage": cov_pct, "title": tmatch,
            "earnable": earnable, "not_true": not_true, "lint": lint,
            "blockers": blockers, "voice_warnings": voice_warn}


def main():
    ap = argparse.ArgumentParser(description="Proper ATS analyzer (coverage + JD extraction + title + parse-safety)")
    ap.add_argument("--resume", required=True, help="Path to resume .md")
    ap.add_argument("--jd-file", help="Raw JD text file (enables weighted extraction + title match)")
    ap.add_argument("--config", help="Hand-curated JSON {required, nice_to_have} (alternative to --jd-file)")
    ap.add_argument("--pdf", help="Compiled PDF (auto-detected from --resume if omitted)")
    args = ap.parse_args()

    pdf_path = args.pdf or resolve_pdf_path(args.resume)
    jd_text = ""
    config = None
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
    if args.jd_file:
        with open(args.jd_file, encoding="utf-8") as f:
            jd_text = f.read()
    if not config and not jd_text:
        print("Provide --jd-file (recommended) or --config.", file=sys.stderr)
        sys.exit(1)

    analyze(args.resume, jd_text, pdf_path, config=config)


if __name__ == "__main__":
    main()
