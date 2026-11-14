#!/usr/bin/env python3
"""
job_store.py - one SQLite store for every job sourced, deduplicated across runs.

WHY THIS EXISTS: sourcing runs used to write the full JD text inline into a dated
markdown file. By 2026-09-18 that was 10MB across 19 files holding 2,219 job entries
of which only 1,055 were unique - the same role re-stored up to 10 times because it
was reposted across runs. Markdown is a report format, not a datastore.

The store keeps one row per unique job (hashed on url, else company+title+location),
records every run that saw it, and lets a JD be pulled back out when tailoring.
The dated .md file becomes a thin index that points here.

  python3 scripts/job_store.py --stats
  python3 scripts/job_store.py --search "fabric"
  python3 scripts/job_store.py --jd <job_id>            # print one JD
  python3 scripts/job_store.py --jd <job_id> --out jd.txt
  python3 scripts/job_store.py --ingest-md jobspy_2026-09-15.md
  python3 scripts/job_store.py --prune-days 120         # drop stale unseen jobs
"""
import argparse
import hashlib
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT,
    site        TEXT,
    url         TEXT,
    salary      TEXT,
    is_contract INTEGER DEFAULT 0,
    description TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    times_seen  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_jobs_company  ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_lastseen ON jobs(last_seen);

CREATE TABLE IF NOT EXISTS sightings (
    job_id   TEXT NOT NULL,
    run_date TEXT NOT NULL,
    run_tag  TEXT,
    recency  TEXT,
    term     TEXT,
    PRIMARY KEY (job_id, run_date, run_tag)
);
"""


def connect(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


# Query parameters that are tracking noise and must be stripped before hashing,
# or the same job hashes differently on every run. Everything NOT on this list is
# kept, because for some boards the identity lives IN the query string.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "source", "src", "trk", "trackingid", "refid", "ref", "referer", "referrer",
    "position", "pagenum", "origin", "originalsubdomain", "savedsearchid",
    "eaddoc", "from", "hl", "gclid", "fbclid", "vjk", "tk", "advn", "sjdu",
    "xkcb", "xpse", "xfps", "alid", "vs", "campaignid", "jobsearchid",
}


def make_job_id(url, company, title, location):
    """Stable identity. Prefer the URL; fall back to company+title+location.

    CRITICAL: do NOT blanket-strip the query string. An Indeed job URL is
    `https://ie.indeed.com/viewjob?jk=<id>` - the identity IS the query string.
    Stripping it collapsed every Indeed job in the store into a single row
    (found 2026-09-22 after one row had absorbed 894 different postings, so
    `--jd <id>` handed back the wrong JD entirely). LinkedIn is the opposite:
    its id is in the path, and its query string is pure tracking.

    So: keep the path, keep identifying params, drop only known tracking params.
    """
    if url:
        base, _, query = url.partition("?")
        base = base.rstrip("/").lower()
        keep = []
        for part in query.split("&"):
            if not part:
                continue
            name = part.split("=", 1)[0].strip().lower()
            if name and name not in _TRACKING_PARAMS:
                keep.append(part.lower())
        key = base + ("?" + "&".join(sorted(keep)) if keep else "")
    else:
        key = f"{(company or '').lower()}|{(title or '').lower()}|{(location or '').lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _txt(v, default=""):
    """Coerce a value to a safe string for SQLite.

    pandas hands us float('nan') for a missing field, and NaN is TRUTHY, so the
    usual `v or ""` idiom passes it straight through - and Python's sqlite3 binds
    NaN as NULL, which trips the NOT NULL constraint and aborts the whole run.
    (Hit 2026-09-22: one posting with no company name killed a 700-row sweep.)
    """
    if v is None:
        return default
    if isinstance(v, float) and v != v:      # NaN
        return default
    v = str(v).strip()
    return v if v and v.lower() != "nan" else default


def upsert(conn, job, run_date=None, run_tag="", recency="", term=""):
    """Insert a job or update it in place. Returns (job_id, was_new)."""
    run_date = run_date or str(date.today())
    jid = make_job_id(job.get("url"), job.get("company"), job.get("title"), job.get("location"))
    cur = conn.execute("SELECT description, times_seen FROM jobs WHERE job_id=?", (jid,))
    row = cur.fetchone()
    desc = (job.get("description") or "").strip()

    if row is None:
        conn.execute(
            "INSERT INTO jobs (job_id,title,company,location,site,url,salary,is_contract,"
            "description,first_seen,last_seen,times_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            (jid, _txt(job.get("title")), _txt(job.get("company"), "Unknown"),
             _txt(job.get("location")), _txt(job.get("site")), _txt(job.get("url")),
             _txt(job.get("salary"), None),
             1 if job.get("is_contract") else 0, desc, run_date, run_date),
        )
        was_new = True
    else:
        # Never overwrite a stored JD with an empty one - a later run with
        # --no-descriptions must not blank out text we already captured.
        keep = desc if len(desc) > len(row[0] or "") else row[0]
        conn.execute(
            "UPDATE jobs SET last_seen=?, times_seen=times_seen+1, description=?,"
            " salary=COALESCE(?,salary), is_contract=? WHERE job_id=?",
            (run_date, keep, _txt(job.get("salary"), None), 1 if job.get("is_contract") else 0, jid),
        )
        was_new = False

    conn.execute(
        "INSERT OR REPLACE INTO sightings (job_id,run_date,run_tag,recency,term) VALUES (?,?,?,?,?)",
        (jid, run_date, run_tag, recency, term),
    )
    return jid, was_new


def get_jd(conn, job_id):
    cur = conn.execute(
        "SELECT title,company,location,site,url,salary,description,first_seen,last_seen,times_seen"
        " FROM jobs WHERE job_id=?", (job_id,))
    return cur.fetchone()


def search(conn, q, limit=40, contract=None):
    sql = ("SELECT job_id,title,company,location,url,is_contract,last_seen,times_seen FROM jobs"
           " WHERE (title LIKE ? OR company LIKE ? OR description LIKE ?)")
    params = [f"%{q}%"] * 3
    if contract is not None:
        sql += " AND is_contract=?"
        params.append(1 if contract else 0)
    sql += " ORDER BY last_seen DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def stats(conn):
    j = conn.execute("SELECT COUNT(*), SUM(times_seen), SUM(LENGTH(COALESCE(description,'')))"
                     " FROM jobs").fetchone()
    runs = conn.execute("SELECT COUNT(DISTINCT run_date) FROM sightings").fetchone()[0]
    contract = conn.execute("SELECT COUNT(*) FROM jobs WHERE is_contract=1").fetchone()[0]
    return {"unique_jobs": j[0] or 0, "total_sightings": j[1] or 0,
            "jd_bytes": j[2] or 0, "runs": runs, "contract_jobs": contract}


def prune(conn, days):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    n = conn.execute("SELECT COUNT(*) FROM jobs WHERE last_seen < ?", (cutoff,)).fetchone()[0]
    conn.execute("DELETE FROM sightings WHERE job_id IN (SELECT job_id FROM jobs WHERE last_seen < ?)",
                 (cutoff,))
    conn.execute("DELETE FROM jobs WHERE last_seen < ?", (cutoff,))
    conn.commit()
    conn.execute("VACUUM")
    return n


# --- migration: read the historical inline-JD markdown dumps ----------------
ENTRY_RE = re.compile(r"^### \d+\.\s+(.*?)\s+—\s+(.*?)\s*$", re.M)


def ingest_md(conn, path):
    """Parse one legacy jobspy_*.md and pull its JDs into the store."""
    text = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"# JobSpy Multi-Board Matches\s+—\s+(\d{4}-\d{2}-\d{2})", text)
    run_date = m.group(1) if m else str(date.fromtimestamp(os.path.getmtime(path)))
    run_tag = os.path.basename(path).replace(".md", "")

    marks = list(ENTRY_RE.finditer(text))
    new = seen = 0
    for i, mk in enumerate(marks):
        block = text[mk.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        url = re.search(r"- \*\*URL\*\*:\s*(\S+)", block)
        site = re.search(r"- \*\*Site\*\*:\s*(\w+)", block)
        loc = re.search(r"\| \*\*Location\*\*:\s*([^|\n]+)", block)
        sal = re.search(r"\| \*\*Salary\*\*:\s*([^|\n]+)", block)
        rec = re.search(r"- \*\*Recency\*\*:\s*([^(\n]+)", block)
        term = re.search(r"\(term:\s*([^)]+)\)", block)
        jd = re.search(r"```text\n(.*?)\n```", block, re.S)
        job = {
            "title": mk.group(1).strip(), "company": mk.group(2).strip(),
            "location": loc.group(1).strip() if loc else None,
            "site": site.group(1) if site else None,
            "url": url.group(1) if url else None,
            "salary": sal.group(1).strip() if sal else None,
            "is_contract": "READS AS CONTRACT" in block,
            "description": jd.group(1) if jd else "",
        }
        _, was_new = upsert(conn, job, run_date=run_date, run_tag=run_tag,
                            recency=rec.group(1).strip() if rec else "",
                            term=term.group(1).strip() if term else "")
        new += was_new
        seen += 1
    conn.commit()
    return seen, new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--search")
    ap.add_argument("--contract-only", action="store_true")
    ap.add_argument("--permanent-only", action="store_true")
    ap.add_argument("--jd", help="job_id to print")
    ap.add_argument("--out", help="write the JD to this file instead of stdout")
    ap.add_argument("--ingest-md", nargs="+")
    ap.add_argument("--prune-days", type=int)
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    conn = connect(a.db)

    if a.ingest_md:
        tot_seen = tot_new = 0
        for p in a.ingest_md:
            if not os.path.exists(p):
                print(f"  skip (missing): {p}")
                continue
            s, n = ingest_md(conn, p)
            tot_seen += s
            tot_new += n
            print(f"  {os.path.basename(p):45s} {s:5d} entries, {n:5d} new")
        print(f"\nIngested {tot_seen} entries, {tot_new} unique new jobs.")

    if a.prune_days:
        print(f"Pruned {prune(conn, a.prune_days)} jobs unseen for {a.prune_days}+ days.")

    if a.jd:
        row = get_jd(conn, a.jd)
        if not row:
            print(f"No job {a.jd}", file=sys.stderr)
            return 1
        hdr = (f"{row[0]} — {row[1]}\nLocation: {row[2]}\nSite: {row[3]}\nURL: {row[4]}\n"
               f"Salary: {row[5]}\nSeen: {row[7]} to {row[8]} ({row[9]}x)\n{'-'*60}\n")
        body = hdr + (row[6] or "(no JD text stored)")
        if a.out:
            open(a.out, "w").write(body)
            print(f"Wrote {a.out} ({len(body)} chars)")
        else:
            print(body)

    if a.search:
        contract = True if a.contract_only else (False if a.permanent_only else None)
        rows = search(conn, a.search, a.limit, contract)
        print(f"{len(rows)} match(es) for '{a.search}':\n")
        for r in rows:
            tag = " [CONTRACT]" if r[5] else ""
            print(f"  {r[0]}  {r[1][:52]:52s} {r[2][:26]:26s} {r[6]}{tag}\n"
                  f"      {r[4]}")

    if a.stats or not any([a.search, a.jd, a.ingest_md, a.prune_days]):
        s = stats(conn)
        size = os.path.getsize(a.db) if os.path.exists(a.db) else 0
        print("\nJOB STORE")
        print(f"  unique jobs      : {s['unique_jobs']:,}")
        print(f"  total sightings  : {s['total_sightings']:,}  "
              f"(dedupe saved {s['total_sightings'] - s['unique_jobs']:,} duplicate stores)")
        print(f"  contract-flagged : {s['contract_jobs']:,}")
        print(f"  sourcing runs    : {s['runs']:,}")
        print(f"  JD text          : {s['jd_bytes']/1e6:.1f} MB")
        print(f"  db file          : {size/1e6:.1f} MB\n")
    conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
