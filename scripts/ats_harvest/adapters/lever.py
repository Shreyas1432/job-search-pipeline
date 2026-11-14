"""Lever: GET api.lever.co/v0/postings/{token}?mode=json"""
import re
from ..base import Adapter, http_json, parse_date
from ..record import JobPosting

_RE = re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I)


class Lever(Adapter):
    PLATFORM = "lever"

    def fetch(self, board_token: str) -> list:
        url = f"https://api.lever.co/v0/postings/{board_token}?mode=json"
        data = http_json(url)
        out = []
        for j in data:
            out.append(JobPosting(
                source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                job_id=str(j.get("id")), title=j.get("text", ""),
                location=(j.get("categories") or {}).get("location"),
                country=None,
                remote=(((j.get("categories") or {}).get("location") or "").lower().find("remote") >= 0) or None,
                posted_date=parse_date(j.get("createdAt")),
                updated_date=None,
                apply_url=j.get("hostedUrl", ""),
                jd_text=j.get("descriptionPlain"), raw=j))
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return m.group(1)
        return None
