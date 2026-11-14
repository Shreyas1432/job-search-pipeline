"""Greenhouse: GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"""
import re
from ..base import Adapter, http_json, parse_date
from ..record import JobPosting

_RE = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)


class Greenhouse(Adapter):
    PLATFORM = "greenhouse"

    def fetch(self, board_token: str) -> list:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        data = http_json(url)
        out = []
        for j in data.get("jobs", []):
            out.append(JobPosting(
                source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                job_id=str(j.get("id")), title=j.get("title", ""),
                location=(j.get("location") or {}).get("name"),
                country=None, remote=None,
                posted_date=parse_date(j.get("updated_at") or j.get("first_published")),
                updated_date=parse_date(j.get("updated_at")),
                apply_url=j.get("absolute_url", ""),
                jd_text=j.get("content"), raw=j))
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return m.group(1)
        return None
