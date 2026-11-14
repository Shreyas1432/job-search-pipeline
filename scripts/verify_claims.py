#!/usr/bin/env python3
"""
verify_claims.py
Semantic claims verification gate script.
Checks tailored resume bullets against data/master_experience_claims.json
across 3 graduated proficiency tiers (Production, Working, Actively Building).
Outputs flagged bullets for mandatory 30-second human read before compilation.

Two checks run:
  1. Anchor coverage: does each work/project bullet share vocabulary with at
     least one anchor anywhere in the claims file? (soft warning)
  2. Tier misattribution: does a bullet inside a WORK EXPERIENCE section claim
     a tool that is only backed by an `actively_building` anchor (i.e. a
     personal/portfolio-only skill), not a `production_experience` or
     `working_proficiency` one? This is a hard fail — actively_building tools
     must only appear under Projects, never under an employer's bullets.
"""

import sys
import os
import re
import json
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAIMS_FILE = os.path.join(BASE_DIR, "data", "master_experience_claims.json")

import sys  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from candidate import PROFILE  # noqa: E402

# Generic vocabulary used for the soft "does this bullet relate to anything
# in the claims file" check. Not used for tier misattribution (that check
# is derived dynamically from the claims file itself, below).
GENERIC_KEYWORDS = [
    "sql", "oracle", "fbdi", "postgresql", "60%", "genai", "gpt",
    "500k", "500,000", "dbt", "snowflake", "pandas", "numpy", "pytorch",
    "bert", "etl", "elt", "star-schema", "f1-score", "99.8%"
]

# Tool/tech nouns to track for tier misattribution. Extend as needed.
TRACKED_TOOLS = [
    "snowflake", "dbt", "postgresql", "oracle ebs", "oracle fbdi", "fbdi",
    "pytorch", "bert", "gpt-3.5", "gpt-4", "openai",
    "excel", "power bi", "tableau", "databricks",
    "peoplesoft", "jd edwards", "oracle fusion", "oracle bi",
]

WORK_SECTION_MARKERS = ("work experience", "professional experience", "experience")
PROJECT_SECTION_MARKERS = ("project", "projects")


def extract_tool_tiers(claims_data):
    """Return {tool: set(tiers)} where tiers is a subset of
    {"production", "working", "building"}, derived by substring match of
    TRACKED_TOOLS against each anchor string."""
    tier_map = {
        "production": claims_data.get("production_experience", []),
        "working": claims_data.get("working_proficiency", []),
        "building": claims_data.get("actively_building", []),
    }
    tool_tiers = {tool: set() for tool in TRACKED_TOOLS}
    for tier, anchors in tier_map.items():
        blob = " ".join(anchors).lower()
        for tool in TRACKED_TOOLS:
            if tool in blob:
                tool_tiers[tool].add(tier)
    return tool_tiers


def split_into_sections(content):
    """Split the resume into (heading, body_lines) chunks on markdown
    headings (##/###) or bold section-like lines. Returns a list of dicts:
    {"heading": str, "lines": [str, ...]}."""
    sections = []
    current = {"heading": "", "lines": []}
    heading_re = re.compile(r"^#{1,4}\s+(.*)")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        m = heading_re.match(line)
        if m:
            if current["lines"] or current["heading"]:
                sections.append(current)
            current = {"heading": m.group(1), "lines": []}
        else:
            current["lines"].append(line)
    if current["lines"] or current["heading"]:
        sections.append(current)
    return sections


def is_work_section(heading, lines):
    """A section counts as 'work experience' if its heading says so, OR if
    an early line names a known employer context (company name followed by
    a date range is the common pattern in these templates)."""
    h = heading.lower()
    if any(marker in h for marker in WORK_SECTION_MARKERS):
        return True
    if any(marker in h for marker in PROJECT_SECTION_MARKERS):
        return False
    # Fallback: look for a role/company header pattern in the heading itself
    # (e.g. "Analytics Engineer | Northwind Consulting") or in the first few body
    # lines (e.g. an italicized company name line right after the heading).
    # Employers come from data/profile.json.
    employers = [e.lower() for e in PROFILE["employers"]]
    if any(e in h for e in employers):
        return True
    head_text = " ".join(lines[:4]).lower()
    return any(e in head_text for e in employers)


def verify_resume(md_path):
    if not os.path.exists(md_path):
        print(f"❌ Error: Resume file not found at {md_path}")
        return False

    if not os.path.exists(CLAIMS_FILE):
        print(f"⚠️ Warning: Master claims file missing at {CLAIMS_FILE}")
        return True

    with open(CLAIMS_FILE, 'r', encoding='utf-8') as f:
        claims_data = json.load(f)

    all_anchors = (
        claims_data.get("production_experience", []) +
        claims_data.get("working_proficiency", []) +
        claims_data.get("actively_building", [])
    )
    tool_tiers = extract_tool_tiers(claims_data)
    building_only_tools = {t for t, tiers in tool_tiers.items() if tiers == {"building"}}

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"\n🔍 CLAIMS VERIFICATION GATE: {os.path.basename(md_path)}")
    print("=" * 60)
    print(f"📦 Total Master Anchors Loaded: {len(all_anchors)} across 3 Tiers (Production / Working / Building)")
    if building_only_tools:
        print(f"🧭 Portfolio-only tools (must not appear under Work Experience): {', '.join(sorted(building_only_tools))}")

    # --- Check 1: soft anchor-coverage warning (unchanged behavior) ---
    all_bullets = [
        line.strip() for line in content.splitlines()
        if line.strip().startswith(('-', '*', '•'))
    ]
    uncovered = []
    for bullet in all_bullets:
        clean = bullet.lstrip("-*• ").strip()
        if not any(kw in clean.lower() for kw in GENERIC_KEYWORDS):
            uncovered.append(clean)

    # --- Check 2: hard fail on tier misattribution ---
    sections = split_into_sections(content)
    misattributed = []
    for section in sections:
        if not is_work_section(section["heading"], section["lines"]):
            continue
        for line in section["lines"]:
            if not line.startswith(('-', '*', '•')):
                continue
            clean = line.lstrip("-*• ").strip()
            low = clean.lower()
            for tool in building_only_tools:
                if tool in low:
                    misattributed.append((section["heading"] or "(work experience)", tool, clean))

    if misattributed:
        print(f"\n🛑 CLAIMS GATE FAILED — {len(misattributed)} misattribution(s) found:")
        for heading, tool, bullet in misattributed:
            print(f'  [{heading}] claims "{tool}" as work experience, but it is only backed by a portfolio/practice anchor (actively_building tier).')
            print(f'      Bullet: "{bullet}"')
        print("\n👉 Action: HALT compilation. Rewrite these bullets to use a verified production/working-tier anchor instead, or move the claim into a clearly-labeled Projects section.")
        print("=" * 60)
        return False

    if uncovered:
        print(f"\n⚠️ ATTENTION: {len(uncovered)} bullet(s) flagged for 30-Second Human Verification Read:")
        for idx, b in enumerate(uncovered, 1):
            print(f"  [{idx}] {b}")
        print("\n👉 Action: Confirm bullet accuracy against master project history before compiling.")
    else:
        print("\n🟢 CLAIMS GATE PASSED: No tier misattribution found; all bullets share vocabulary with a master anchor.")

    print("=" * 60)
    return True


def main():
    parser = argparse.ArgumentParser(description="Resume Claims Verification Gate")
    parser.add_argument("--resume", type=str, required=True, help="Path to resume markdown file")
    args = parser.parse_args()
    passed = verify_resume(args.resume)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
