"""Workday: POST {host}/wday/cxs/{tenant}/{site}/jobs (paginated).

board_token is 'host/site', e.g. 'aig.wd1.myworkdayjobs.com/External'. Workday
returns a RELATIVE date string ('Posted 24 Days Ago') -> parse_workday_date, which
yields None for unparseable text rather than inventing a date. This is the AIG case.
"""
import re
from ..base import Adapter, http_json, parse_workday_date
from ..record import JobPosting

_RE = re.compile(r"([a-z0-9-]+\.[a-z0-9]+\.myworkdayjobs\.com)/([^/?#]+)", re.I)
_MAX_PAGES = 25   # 25*20 = 500 most-recent jobs per board (bounds big 1000+ boards)


class Workday(Adapter):
    PLATFORM = "workday"

    def fetch(self, board_token: str) -> list:
        host, _, site = board_token.partition("/")
        tenant = host.split(".")[0]
        url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        out, offset, limit = [], 0, 20
        while offset < _MAX_PAGES * limit:   # cap: big boards (1000+ jobs) harvest recent pages only
            data = http_json(url, method="POST",
                             json_body={"limit": limit, "offset": offset,
                                        "searchText": "", "appliedFacets": {}})
            postings = data.get("jobPostings", [])
            for j in postings:
                ext = j.get("externalPath", "")
                req = (j.get("bulletFields") or [None])[0]
                out.append(JobPosting(
                    source_platform=self.PLATFORM, company=tenant, board_token=board_token,
                    job_id=str(req or ext), title=j.get("title", ""),
                    location=j.get("locationsText"), country=None, remote=None,
                    posted_date=parse_workday_date(j.get("postedOn", "")),
                    updated_date=None,
                    apply_url=f"https://{host}{ext}", jd_text=None, raw=j))
            total = data.get("total", len(postings))
            offset += limit
            if offset >= total or not postings:
                break
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return f"{m.group(1)}/{m.group(2)}"
        return None
