"""Company -> ATS board catalog, stored as a table in an sqlite db (data/jobs.db).

Rows: (company, platform, board_token, careers_url, market, last_harvested).
PRIMARY KEY (platform, board_token) so a board is catalogued once.
"""
import csv
import sqlite3
from typing import Optional

from . import discovery

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ats_catalog (
    company TEXT,
    platform TEXT,
    board_token TEXT,
    careers_url TEXT,
    market TEXT,
    last_harvested TEXT,
    PRIMARY KEY (platform, board_token)
)
"""


def _conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def ensure_schema(db_path: str):
    with _conn(db_path) as c:
        c.execute(_SCHEMA)


def add(db_path, company, platform, board_token, careers_url=None, market=None):
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO ats_catalog(company,platform,board_token,careers_url,market,last_harvested)"
            " VALUES(?,?,?,?,?,NULL)"
            " ON CONFLICT(platform,board_token) DO UPDATE SET"
            " company=excluded.company, careers_url=excluded.careers_url, market=excluded.market",
            (company, platform, board_token, careers_url, market))


def list(db_path, market=None, platform=None):
    q, args = "SELECT * FROM ats_catalog", []
    where = []
    if market:
        where.append("market=?"); args.append(market)
    if platform:
        where.append("platform=?"); args.append(platform)
    if where:
        q += " WHERE " + " AND ".join(where)
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def mark_harvested(db_path, platform, board_token, when_iso):
    with _conn(db_path) as c:
        c.execute("UPDATE ats_catalog SET last_harvested=? WHERE platform=? AND board_token=?",
                  (when_iso, platform, board_token))


def seed_from_file(db_path, path):
    """File rows: company,domain_or_careers_url[,market]. Runs discovery.detect per
    row; adds detected boards. Returns (added, skipped)."""
    added = skipped = 0
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            company = row[0].strip()
            url = row[1].strip() if len(row) > 1 else ""
            market = row[2].strip() if len(row) > 2 else None
            platform, token = discovery.detect(url, fetch=True)
            if platform and token:
                add(db_path, company, platform, token, careers_url=url, market=market)
                added += 1
            else:
                skipped += 1
    return added, skipped
