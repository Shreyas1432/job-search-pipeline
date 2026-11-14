"""Oracle Cloud CX / Fusion recruiting (Candidate Experience).

Oracle Fusion HCM employers expose a PUBLIC candidate REST API that returns
live requisitions as JSON, even when the HTML careers page is behind an
Akamai/WAF4SaaS wall that blocks scraping. This is the sanctioned data path:
the same API the candidate site's own JavaScript calls, no login, no evasion.

board_token encodes BOTH the employer pod host and the CE site, joined by '|':
    "fa-ewnd-saasfaprod1.fa.ocs.oraclecloud.com|CX_2001"
because the host varies per employer and one host can serve several sites.

List:   /hcmRestApi/resources/latest/recruitingCEJobRequisitions
Detail: /hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
"""
import re
from urllib.parse import quote

from ..base import Adapter, concurrent_map, http_json, parse_date
from ..record import JobPosting

# e.g. .../CandidateExperience/en/sites/CX_2001/...  on an oraclecloud.com host
_RE = re.compile(
    r"https?://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[^/]+/sites/([A-Za-z0-9_]+)",
    re.I,
)


class OracleCX(Adapter):
    PLATFORM = "oraclecx"

    def fetch(self, board_token: str) -> list:
        host, _, site = board_token.partition("|")
        if not host or not site:
            raise ValueError(f"oraclecx token must be 'host|site', got {board_token!r}")
        base = f"https://{host}/hcmRestApi/resources/latest"
        finder = quote(
            f'findReqs;siteNumber="{site}",limit=200,sortBy=POSTING_DATES_DESC',
            safe=';,="',
        )
        list_url = (
            f"{base}/recruitingCEJobRequisitions?onlyData=true"
            f"&expand=requisitionList.secondaryLocations,flexFieldsFacet.values"
            f"&finder={finder}"
        )
        data = http_json(list_url)
        items = data.get("items") or []
        reqs = items[0].get("requisitionList", []) if items else []

        def build(r):
            jid = str(r.get("Id") or "")
            jd_text = self._detail(base, site, jid)
            return JobPosting(
                source_platform=self.PLATFORM, company=host.split(".")[0], board_token=board_token,
                job_id=jid, title=r.get("Title", ""),
                location=r.get("PrimaryLocation"),
                country=None, remote=None,
                posted_date=parse_date(r.get("PostedDate") or r.get("ExternalPostedStartDate")),
                updated_date=parse_date(r.get("ExternalPostedStartDate")),
                apply_url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}/",
                jd_text=jd_text, raw=r)

        return concurrent_map(build, reqs, workers=6)

    @staticmethod
    def _detail(base: str, site: str, job_id: str):
        """Full JD text for one req, or None. Never raises past the harvest."""
        if not job_id:
            return None
        finder = quote(f'ById;Id="{job_id}",siteNumber="{site}"', safe=';,="')
        url = f"{base}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder={finder}"
        try:
            items = (http_json(url).get("items") or [])
            if not items:
                return None
            it = items[0]
            parts = [it.get("ExternalDescriptionStr"), it.get("ExternalResponsibilitiesStr"),
                     it.get("ExternalQualificationsStr")]
            txt = "\n\n".join(p for p in parts if p)
            return txt or None
        except Exception:
            return None

    @classmethod
    def discover(cls, url, html=None):
        for hay in (url, html or ""):
            m = _RE.search(hay or "")
            if m:
                return f"{m.group(1)}|{m.group(2)}"
        return None
