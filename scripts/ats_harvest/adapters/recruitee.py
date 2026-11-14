"""Recruitee: GET https://{token}.recruitee.com/api/offers/"""
import re
from ..base import Adapter, http_json, parse_date
from ..record import JobPosting

_RE = re.compile(r"([a-z0-9_-]+)\.recruitee\.com", re.I)


class Recruitee(Adapter):
    PLATFORM = "recruitee"

    def fetch(self, board_token: str) -> list:
        url = f"https://{board_token}.recruitee.com/api/offers/"
        data = http_json(url)
        out = []
        for j in data.get("offers", []):
            out.append(JobPosting(
                source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                job_id=str(j.get("id")), title=j.get("title", ""),
                location=j.get("city") or j.get("location"),
                country=j.get("country"), remote=(j.get("remote") or None),
                posted_date=parse_date(j.get("published_at")),
                updated_date=parse_date(j.get("updated_at")),
                apply_url=j.get("careers_url") or j.get("careers_apply_url") or "",
                jd_text=j.get("description"), raw=j))
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return m.group(1)
        return None
