#!/usr/bin/env python3
"""Build data/jobs.db from examples/jobs_seed.json so the UI has something to show."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import job_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    conn = job_store.connect()
    with open(os.path.join(ROOT, "examples", "jobs_seed.json"), encoding="utf-8") as fh:
        jobs = json.load(fh)
    new = sum(job_store.upsert(conn, j, run_date=j["first_seen"], run_tag="demo")[1] for j in jobs)
    conn.commit()
    print(f"seeded {new} demo jobs -> {job_store.DB_PATH}")
