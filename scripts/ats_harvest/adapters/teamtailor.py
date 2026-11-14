"""Teamtailor: host-keyed. The /jobs listing has no JSON-LD; each job PAGE carries
schema.org JobPosting JSON-LD with datePosted. So: list job links, then fetch each
page and parse its JSON-LD (true date). board_token is the careers HOST.
"""
import json
import re
from ..base import Adapter, http_text, parse_date, concurrent_map
from ..record import JobPosting

_HOST = re.compile(r"([a-z0-9_.-]+\.teamtailor\.com)", re.I)
_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_JOBLINK = re.compile(r"/jobs/(\d+[a-z0-9-]*)", re.I)
_MAX = 80  # cap requests per board


def _jobpostings_from_html(html):
    out = []
    for block in _LD.findall(html):
        try:
            obj = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in (obj if isinstance(obj, list) else [obj]):
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                out.append(node)
    return out


class Teamtailor(Adapter):
    PLATFORM = "teamtailor"

    def fetch(self, board_token: str) -> list:
        host = board_token if board_token.startswith("http") else f"https://{board_token}"
        listing = http_text(f"{host}/jobs")
        nodes = _jobpostings_from_html(listing)                 # backward-compat: JSON-LD on listing
        links = list(dict.fromkeys(_JOBLINK.findall(listing)))[:_MAX]

        def _page(jid):
            try:
                return _jobpostings_from_html(http_text(f"{host}/jobs/{jid}"))
            except Exception:
                return []
        for page_nodes in concurrent_map(_page, links):
            nodes.extend(page_nodes)
        out, seen = [], set()
        for node in nodes:
            url = node.get("url", "")
            key = url or node.get("title")
            if key in seen:
                continue
            seen.add(key)
            jl = node.get("jobLocation")
            if isinstance(jl, list):
                jl = jl[0] if jl else {}
            loc = (jl.get("address") or {}) if isinstance(jl, dict) else {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            out.append(JobPosting(
                source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                job_id=str((node.get("identifier") or {}).get("value") or url),
                title=node.get("title", ""),
                location=loc.get("addressLocality"), country=loc.get("addressCountry"),
                remote=None,
                posted_date=parse_date(node.get("datePosted")),
                updated_date=parse_date(node.get("dateModified")),
                apply_url=url, jd_text=node.get("description"), raw=node))
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _HOST.search(hay or "")
            if m:
                return m.group(1)
        return None
