"""Harvest orchestrator: catalog -> adapters -> filter -> dedupe -> jobs.db + index.

Stores every in-scope (market + title) posting into jobs.db (harvest wide), and
returns / indexes the FRESH subset (true date <= hours). A board that errors is
skipped with a warning; the run continues.
"""
import os
import sys
from datetime import datetime, timezone

from . import registry, catalog, filters
from .base import concurrent_map

# make scripts/job_store.py importable whether run via CLI or test
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import job_store  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _write_index(index_dir, fresh):
    os.makedirs(index_dir, exist_ok=True)
    day = datetime.now().date().isoformat()
    path = os.path.join(index_dir, f"ats_{day}.md")
    lines = [f"# ATS Harvest — {day}",
             f"Direct from employer ATSes. {len(fresh)} fresh (true date) in-scope roles.",
             "> Dates are the EMPLOYER's own posting date, not an aggregator label.", ""]
    for i, p in enumerate(sorted(fresh, key=lambda x: x.posted_date or "", reverse=True), 1):
        lines.append(f"{i}. **{p.title}** — {p.company} [{p.source_platform}]")
        lines.append(f"   {p.location or '?'} | posted {p.posted_date} | {p.apply_url}")
    open(path, "w").write("\n".join(lines) + "\n")
    return path


def _fetch_board(row):
    """Network only (runs in a worker thread): return (row, posts, error-or-None)."""
    try:
        posts = registry.get(row["platform"])().fetch(row["board_token"])
        return (row, posts, None)
    except Exception as e:
        return (row, [], e)


def run(db_path, hours=48, markets=("IE", "IN"), platform=None, index_dir=None, workers=6):
    index_dir = index_dir or os.path.join(BASE_DIR, "sourcing")
    rows = catalog.list(db_path, platform=platform)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Fetch every board concurrently (network). DB writes stay on this thread.
    results = concurrent_map(_fetch_board, rows, workers=workers)

    seen = {}
    harvested = []
    conn = job_store.connect(db_path)
    try:
        for row, posts, err in results:
            if err is not None:
                sys.stderr.write(f"[ats] skip {row['platform']}/{row['board_token']}: {err}\n")
                continue
            harvested.append((row["platform"], row["board_token"]))
            for p in posts:
                if not (filters.in_market(p, markets) and filters.title_match(p.title)):
                    continue
                jid = job_store.make_job_id(p.apply_url, p.company, p.title, p.location)
                if jid in seen:
                    continue
                seen[jid] = p
                job_store.upsert(conn, {
                    "url": p.apply_url, "company": p.company, "title": p.title,
                    "location": p.location, "site": f"ats:{p.source_platform}",
                    "salary": None, "is_contract": False,
                    "description": p.jd_text or ""},
                    run_tag="ats", recency=(p.posted_date or ""))
        conn.commit()
    finally:
        conn.close()
    for plat, tok in harvested:
        catalog.mark_harvested(db_path, plat, tok, now_iso)
    fresh = [p for p in seen.values() if filters.is_fresh(p, hours)]
    _write_index(index_dir, fresh)
    return fresh
