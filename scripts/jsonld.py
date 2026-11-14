#!/usr/bin/env python3
"""Extract schema.org JobPosting data from a page's JSON-LD.

Most job boards and employer ATS pages embed a <script type="application/ld+json">
JobPosting block (title, hiringOrganization, jobLocation, datePosted, salary,
description). Reading THAT is far more robust than regex-scraping rendered HTML:
it is the structured data the employer publishes for Google Jobs.

This is NOT a WAF bypass. If a page is served (not 403), this pulls its own
declared data. Pages behind an anti-bot wall (IrishJobs/Akamai) stay unreadable
here by design — use the human-present Chrome path for those.

Usage:
  python3 scripts/jsonld.py <url>          # fetch (browser UA) + print JobPosting JSON
  python3 scripts/jsonld.py --file p.html  # parse a saved page
"""
import argparse
import html as _html
import json
import re
import sys

_LDJSON = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_TAG = re.compile(r"<[^>]+>")


def _walk(obj):
    """Yield every dict in a JSON-LD doc (handles top-level arrays and @graph)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.get("@graph", []) or []:
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _is_job(node):
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return "JobPosting" in [str(x) for x in types]


def _text(v):
    """Strip HTML tags + unescape entities from a JSON-LD description string."""
    if not v:
        return None
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", str(v)))).strip() or None


def _org(node):
    o = node.get("hiringOrganization")
    if isinstance(o, dict):
        return o.get("name")
    return o if isinstance(o, str) else None


def _location(node):
    locs = node.get("jobLocation")
    if isinstance(locs, dict):
        locs = [locs]
    parts = []
    for loc in locs or []:
        addr = loc.get("address") if isinstance(loc, dict) else None
        if isinstance(addr, dict):
            parts.append(", ".join(
                str(addr[k]) for k in ("addressLocality", "addressRegion", "addressCountry")
                if addr.get(k) and not isinstance(addr[k], dict)))
        elif isinstance(addr, str):
            parts.append(addr)
    return "; ".join(p for p in parts if p) or None


def extract_job_postings(page_html):
    """Return a list of normalized JobPosting dicts found in the page's JSON-LD."""
    out = []
    for m in _LDJSON.finditer(page_html or ""):
        raw = m.group(1).strip()
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _walk(doc):
            if not isinstance(node, dict) or not _is_job(node):
                continue
            out.append({
                "title": node.get("title"),
                "company": _org(node),
                "location": _location(node),
                "date_posted": node.get("datePosted"),
                "valid_through": node.get("validThrough"),
                "employment_type": node.get("employmentType"),
                "apply_url": node.get("url") or node.get("directApply"),
                "description": _text(node.get("description")),
            })
    return out


def _fetch(url):
    import urllib.request
    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("url", nargs="?")
    g.add_argument("--file")
    a = ap.parse_args(argv)
    page = open(a.file, encoding="utf-8").read() if a.file else _fetch(a.url)
    jobs = extract_job_postings(page)
    if not jobs:
        sys.stderr.write("no JobPosting JSON-LD found (page may be JS-rendered or WAF-walled)\n")
        return 1
    print(json.dumps(jobs, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
