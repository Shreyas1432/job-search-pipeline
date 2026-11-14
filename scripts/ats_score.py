#!/usr/bin/env python3
"""
ats_score.py (v2, 2026-08-06)
Keyword-coverage ATS score: checks a tailored resume against required vs.
nice-to-have keywords, either hand-curated (--config) or auto-extracted from
a pasted JD (--jd-file / --jd-text). Scores against the compiled PDF's
extracted text when one exists (what a real ATS actually parses), falling
back to the markdown source otherwise, and flags any mismatch between the two.

v2 changes from v1:
- Whole-word/phrase regex matching instead of raw substring (v1 falsely
  matched "sql" inside "mysql", and falsely MISSED "Power BI" against
  "PowerBI" because normalize() collapsed both to different strings with no
  common substring - spacing/punctuation variants simply didn't match).
- Synonym-aware matching via skills_dictionary.SYNONYM_GROUPS (SQL <->
  Structured Query Language, ETL <-> Extract Transform Load, etc.).
- Optional auto keyword extraction from a raw JD via skills_dictionary.SKILL_VOCAB,
  so keyword lists aren't 100% hand-picked by the same agent being scored.
- Scores the compiled PDF's extracted text (pdfplumber) when available, not
  just the markdown source - closer to what a real ATS parser sees.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from skills_dictionary import SYNONYM_GROUPS, SKILL_VOCAB


def normalize(text):
    text = text.lower()
    text = re.sub(r"[‐-―]", "-", text)  # normalize unicode dashes
    return text


def build_pattern(term):
    """Word-boundary regex for a term, tolerant of internal space/hyphen variation
    (so 'power bi' also matches 'power-bi' or 'power  bi'). Built from tokens
    directly rather than post-processing an escaped string, to avoid a
    replace-collision where a later substitution matches text a prior
    substitution just inserted."""
    # Split on, and rejoin with, light punctuation as well as whitespace/hyphen.
    # WHY (2026-09-22): JDs write skills as comma lists ("performance, productivity,
    # capacity, cost and efficiency"). The keyword extractor lifts multi-word phrases
    # straight out of those lists, so requiring the phrase to be comma-free meant the
    # JD's OWN TEXT could not match its own extracted keyword - manufacturing
    # unreachable "missed must-haves" and depressing every composite score.
    tokens = re.split(r"[\s\-,/]+", term.lower().strip())
    escaped_tokens = [re.escape(t) for t in tokens if t]
    # Comma/slash tolerated as list separators; "and"/"or" deliberately NOT bridged,
    # which kept over-matching down while still fixing the comma-list case.
    body = r"[\s\-,/]+".join(escaped_tokens)
    # Trailing optional plural (s/es) so "visualization" matches "visualizations",
    # "pipeline"->"pipelines", "dashboard"->"dashboards", "model"->"models", etc.
    # This lifts recall on both coverage and the claims-honesty gate, where the
    # claims file often stores the plural surface form.
    return re.compile(r"(?<![a-z0-9])" + body + r"(?:es|s)?(?![a-z0-9])")


def synonym_expand(term):
    """Return the full set of surface forms for a term, including itself."""
    t = term.lower().strip()
    for group in SYNONYM_GROUPS:
        if t in group:
            return group
    return {t}


def hit(term, haystack_norm):
    for form in synonym_expand(term):
        if build_pattern(form).search(haystack_norm):
            return True
    return False


def extract_pdf_text(pdf_path):
    try:
        import pdfplumber
    except ImportError:
        return None
    if not os.path.exists(pdf_path):
        return None
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def auto_extract_keywords(jd_text):
    """Split a raw JD into required vs nice-to-have by locating common section
    headers, then intersect each section's text against SKILL_VOCAB."""
    jd_lower = jd_text.lower()

    req_markers = [
        "essential", "required", "requirements", "must have", "must-have",
        "you'll need", "what you need", "what you'll bring", "key requirements",
    ]
    nice_markers = [
        "desirable", "nice to have", "nice-to-have", "preferred", "bonus",
        "advantageous", "would be a plus", "a plus",
    ]

    def marker_index(markers):
        best_idx = None
        for m in markers:
            idx = jd_lower.find(m)
            if idx != -1 and (best_idx is None or idx < best_idx):
                best_idx = idx
        return best_idx

    req_idx = marker_index(req_markers)
    nice_idx = marker_index(nice_markers)

    def bounded_section(start_idx, other_idx):
        if start_idx is None:
            return None
        end_idx = start_idx + 1200
        if other_idx is not None and other_idx > start_idx:
            end_idx = min(end_idx, other_idx)
        return jd_lower[start_idx:end_idx]

    req_section = bounded_section(req_idx, nice_idx)
    nice_section = bounded_section(nice_idx, req_idx)

    def vocab_hits(section_text):
        if not section_text:
            return []
        return [term for term in SKILL_VOCAB if hit(term, normalize(section_text))]

    if req_section or nice_section:
        required = vocab_hits(req_section) if req_section else []
        nice = vocab_hits(nice_section) if nice_section else []
        # anything in the whole JD but not already bucketed goes to required
        # (safer default - undercounting required hurts more than overcounting)
        whole = vocab_hits(jd_text)
        required = list(dict.fromkeys(required + [t for t in whole if t not in nice]))
    else:
        # no section headers found - treat everything detected as required
        required = vocab_hits(jd_text)
        nice = []

    return required[:20], nice[:10]


def score(resume_text_sources, required, nice_to_have, label):
    results = {}
    for source_name, text in resume_text_sources.items():
        if text is None:
            continue
        norm = normalize(text)
        req_hits = [kw for kw in required if hit(kw, norm)]
        req_misses = [kw for kw in required if kw not in req_hits]
        nice_hits = [kw for kw in nice_to_have if hit(kw, norm)]
        nice_misses = [kw for kw in nice_to_have if kw not in nice_hits]

        req_pct = 100 * len(req_hits) / len(required) if required else 100
        nice_pct = 100 * len(nice_hits) / len(nice_to_have) if nice_to_have else 100
        overall = 0.75 * req_pct + 0.25 * nice_pct

        results[source_name] = {
            "overall": overall, "req_pct": req_pct, "nice_pct": nice_pct,
            "req_hits": req_hits, "req_misses": req_misses,
            "nice_hits": nice_hits, "nice_misses": nice_misses,
        }

    print(f"\n{'='*64}\nATS KEYWORD COVERAGE: {label}\n{'='*64}")
    for source_name, r in results.items():
        print(f"\n--- scored against: {source_name} ---")
        print(f"Required: {len(r['req_hits'])}/{len(required)} ({r['req_pct']:.0f}%)")
        if r["req_misses"]:
            print(f"  Missing required: {', '.join(r['req_misses'])}")
        print(f"Nice-to-have: {len(r['nice_hits'])}/{len(nice_to_have)} ({r['nice_pct']:.0f}%)")
        if r["nice_misses"]:
            print(f"  Missing nice-to-have: {', '.join(r['nice_misses'])}")
        print(f"OVERALL: {r['overall']:.0f}/100")

    if "compiled_pdf" in results and "markdown_source" in results:
        diff = abs(results["compiled_pdf"]["overall"] - results["markdown_source"]["overall"])
        if diff >= 3:
            print(f"\n[!] WARNING: PDF score differs from markdown-source score by {diff:.0f} points.")
            print("    The compiled PDF is what a real ATS actually parses - trust that number,")
            print("    and check for a compile-step formatting issue if the gap is large.")
    print(f"{'='*64}")

    authoritative = results.get("compiled_pdf", results.get("markdown_source"))
    return authoritative


def resolve_pdf_path(resume_md_path):
    """Locate the compiled PDF for a resume .md. compile_docs writes it into the SAME
    folder: <base>.pdf outside applications/, or the send file
    <First>_<Last>_<Role>[_Tag].pdf inside an applications/ folder.
    Returns the first match, else the <base>.pdf guess so the caller can report it."""
    import glob
    from candidate import file_prefix
    md_dir = os.path.dirname(os.path.abspath(resume_md_path))
    base = os.path.splitext(os.path.basename(resume_md_path))[0]
    direct = os.path.join(md_dir, f"{base}.pdf")
    if os.path.exists(direct):
        return direct
    is_cover = "cover_letter" in base.lower()
    sends = sorted((f for f in glob.glob(os.path.join(md_dir, file_prefix() + "*.pdf"))
                    if ("_Cover_Letter" in f) == is_cover), key=os.path.getmtime)
    return sends[-1] if sends else direct


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", required=True, help="Path to the resume .md source")
    parser.add_argument("--config", help="JSON file with hand-curated 'required'/'nice_to_have' lists")
    parser.add_argument("--jd-file", help="Path to a text file containing the raw JD, for auto keyword extraction")
    parser.add_argument("--pdf", help="Explicit path to the compiled PDF (auto-detected from --resume path if omitted)")
    args = parser.parse_args()

    with open(args.resume, "r", encoding="utf-8") as f:
        md_text = f.read()

    pdf_path = args.pdf or resolve_pdf_path(args.resume)
    pdf_text = extract_pdf_text(pdf_path)

    sources = {"markdown_source": md_text}
    if pdf_text:
        sources["compiled_pdf"] = pdf_text
    elif not extract_pdf_text.__module__:
        pass

    if args.config:
        with open(args.config) as f:
            cfg = json.load(f)
        required, nice = cfg["required"], cfg["nice_to_have"]
    elif args.jd_file:
        with open(args.jd_file, "r", encoding="utf-8") as f:
            jd_text = f.read()
        required, nice = auto_extract_keywords(jd_text)
        print(f"[auto-extracted from JD] required: {required}")
        print(f"[auto-extracted from JD] nice-to-have: {nice}")
    else:
        print("Provide either --config (hand-curated) or --jd-file (auto-extract).", file=sys.stderr)
        sys.exit(1)

    score(sources, required, nice, args.resume)
