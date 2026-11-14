"""Ashby: the public posting-api REST endpoint returns 401 unless the employer
enabled it, so use the keyless job-board GraphQL to LIST postings, then read each
job page's schema.org JSON-LD for the true datePosted (same 2-phase as Teamtailor).
board_token is the org slug (jobs.ashbyhq.com/<org>).
"""
import json
import re
from ..base import Adapter, http_json, http_text, parse_date, concurrent_map
from ..record import JobPosting

_RE = re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_-]+)", re.I)
_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_GQL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
_QUERY = ("query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!)"
          "{jobBoard:jobBoardWithTeams(organizationHostedJobsPageName:$organizationHostedJobsPageName)"
          "{jobPostings{id title locationName}}}")
_MAX = 80


def _ld_jobposting(html):
    for block in _LD.findall(html):
        try:
            obj = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in (obj if isinstance(obj, list) else [obj]):
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return None


class Ashby(Adapter):
    PLATFORM = "ashby"

    def fetch(self, board_token: str) -> list:
        data = http_json(_GQL, method="POST", json_body={
            "operationName": "ApiJobBoardWithTeams",
            "variables": {"organizationHostedJobsPageName": board_token},
            "query": _QUERY})
        listings = (((data.get("data") or {}).get("jobBoard") or {}).get("jobPostings") or [])[:_MAX]

        def _one(j):
            jid = j.get("id")
            url = f"https://jobs.ashbyhq.com/{board_token}/{jid}"
            posted, loc = None, j.get("locationName")
            try:
                node = _ld_jobposting(http_text(url))
                if node:
                    posted = parse_date(node.get("datePosted"))
                    a = ((node.get("jobLocation") or {}).get("address") or {}) if isinstance(node.get("jobLocation"), dict) else {}
                    loc = a.get("addressLocality") or loc
            except Exception:
                pass
            return JobPosting(
                source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                job_id=str(jid), title=j.get("title", ""),
                location=loc, country=None, remote=("remote" in (j.get("locationName") or "").lower()) or None,
                posted_date=posted, updated_date=None,
                apply_url=url, jd_text=None, raw=j)
        return concurrent_map(_one, listings)

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return m.group(1)
        return None
