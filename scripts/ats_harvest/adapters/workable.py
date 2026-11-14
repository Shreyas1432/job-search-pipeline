"""Workable: GET apply.workable.com/api/v1/widget/accounts/{token}?details=true"""
import re
from ..base import Adapter, http_json, parse_date
from ..record import JobPosting

_RE = re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I)


class Workable(Adapter):
    PLATFORM = "workable"

    def fetch(self, board_token: str) -> list:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{board_token}?details=true"
        data = http_json(url)
        out = []
        for j in data.get("jobs", []):
            loc = j.get("location") or {}
            out.append(JobPosting(
                source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                job_id=str(j.get("shortcode")), title=j.get("title", ""),
                location=loc.get("city") or loc.get("location_str"),
                country=loc.get("country"), remote=loc.get("telecommuting"),
                posted_date=parse_date(j.get("published_on") or j.get("created_at")),
                updated_date=None,
                apply_url=j.get("application_url") or j.get("url") or j.get("shortlink") or "",
                jd_text=j.get("description"), raw=j))
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return m.group(1)
        return None
