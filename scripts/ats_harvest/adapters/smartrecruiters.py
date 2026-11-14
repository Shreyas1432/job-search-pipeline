"""SmartRecruiters: GET api.smartrecruiters.com/v1/companies/{token}/postings (paginated)"""
import re
from ..base import Adapter, http_json, parse_date
from ..record import JobPosting

_RE = re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([a-z0-9_-]+)", re.I)


class SmartRecruiters(Adapter):
    PLATFORM = "smartrecruiters"

    def fetch(self, board_token: str) -> list:
        out, offset, limit = [], 0, 100
        while True:
            url = (f"https://api.smartrecruiters.com/v1/companies/{board_token}"
                   f"/postings?limit={limit}&offset={offset}")
            data = http_json(url)
            content = data.get("content", [])
            for j in content:
                out.append(JobPosting(
                    source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                    job_id=str(j.get("id")), title=j.get("name", ""),
                    location=(j.get("location") or {}).get("city"),
                    country=(j.get("location") or {}).get("country"), remote=(j.get("location") or {}).get("remote"),
                    posted_date=parse_date(j.get("releasedDate")),
                    updated_date=None,
                    apply_url=f"https://jobs.smartrecruiters.com/{board_token}/{j.get('id')}",
                    jd_text=None, raw=j))
            total = data.get("totalFound", len(content))
            offset += limit
            if offset >= total or not content:
                break
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return m.group(1)
        return None
