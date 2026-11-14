"""Personio: GET https://{token}.jobs.personio.com/xml (XML feed)."""
import re
import xml.etree.ElementTree as ET
from ..base import Adapter, http_text, parse_date
from ..record import JobPosting

_RE = re.compile(r"([a-z0-9_-]+)\.jobs\.personio\.(?:com|de)", re.I)


class Personio(Adapter):
    PLATFORM = "personio"

    def fetch(self, board_token: str) -> list:
        xml = http_text(f"https://{board_token}.jobs.personio.com/xml")
        root = ET.fromstring(xml.strip())
        out = []
        for pos in root.iter("position"):
            def g(tag):
                el = pos.find(tag)
                return el.text if el is not None else None
            jid = g("id")
            out.append(JobPosting(
                source_platform=self.PLATFORM, company=board_token, board_token=board_token,
                job_id=str(jid), title=g("name") or "",
                location=g("office"), country=None, remote=None,
                posted_date=parse_date(g("createdAt")),
                updated_date=None,
                apply_url=f"https://{board_token}.jobs.personio.com/job/{jid}",
                jd_text=g("jobDescriptions"), raw={"id": jid}))
        return out

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return m.group(1)
        return None
