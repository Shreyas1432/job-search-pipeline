#!/usr/bin/env python3
"""ATS harvester CLI — source jobs directly from employers' own ATSes (true dates).

Subcommands:
  platforms                      list all declared platforms (real + stub)
  discover --company <domain>    detect a company's ATS + board token (and add to catalog)
  seed --file <csv>              bulk add from company,domain[,market] rows
  catalog [--market] [--platform]   show catalogued boards
  harvest [--hours 48] [--market IE,IN] [--platform]   harvest -> jobs.db + index
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make ats_harvest importable
from ats_harvest import registry, discovery, catalog, harvest  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jobs.db")


def main(argv=None):
    ap = argparse.ArgumentParser(description="ATS harvester")
    ap.add_argument("--db", default=DB)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("platforms")

    d = sub.add_parser("discover")
    d.add_argument("--company", required=True, help="domain or careers URL")
    d.add_argument("--market", default=None)
    d.add_argument("--no-add", action="store_true")

    s = sub.add_parser("seed")
    s.add_argument("--file", required=True)

    c = sub.add_parser("catalog")
    c.add_argument("--market", default=None)
    c.add_argument("--platform", default=None)

    h = sub.add_parser("harvest")
    h.add_argument("--hours", type=int, default=48)
    h.add_argument("--market", default="IE,IN")
    h.add_argument("--platform", default=None)
    h.add_argument("--workers", type=int, default=6)

    a = ap.parse_args(argv)

    if a.cmd == "platforms":
        real = set(registry.real_platforms())
        for p in registry.platforms():
            print(f"{p}\t{'built' if p in real else 'stub'}")
        return 0

    if a.cmd == "discover":
        plat, tok = discovery.detect(a.company, fetch=True)
        if not plat:
            print(f"no ATS detected for {a.company}")
            return 1
        print(f"{a.company} -> {plat} / {tok}")
        if not a.no_add:
            catalog.ensure_schema(a.db)
            catalog.add(a.db, a.company, plat, tok, careers_url=a.company, market=a.market)
            print("added to catalog")
        return 0

    if a.cmd == "seed":
        catalog.ensure_schema(a.db)
        added, skipped = catalog.seed_from_file(a.db, a.file)
        print(f"seeded: {added} added, {skipped} skipped (no ATS detected)")
        return 0

    if a.cmd == "catalog":
        catalog.ensure_schema(a.db)
        rows = catalog.list(a.db, market=a.market, platform=a.platform)
        for r in rows:
            print(f"{r['platform']:16} {r['board_token']:40} {r['market'] or '':4} {r['company']}")
        print(f"\n{len(rows)} boards")
        return 0

    if a.cmd == "harvest":
        catalog.ensure_schema(a.db)
        markets = tuple(m.strip() for m in a.market.split(",") if m.strip())
        fresh = harvest.run(a.db, hours=a.hours, markets=markets, platform=a.platform, workers=a.workers)
        print(f"harvested {len(fresh)} fresh in-scope role(s); index in sourcing/ats_<date>.md")
        for p in fresh[:30]:
            print(f"  [{p.source_platform}] {p.title} — {p.company} | {p.location} | {p.posted_date}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
