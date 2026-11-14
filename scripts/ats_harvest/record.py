"""The one normalized job record every adapter emits."""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class JobPosting:
    source_platform: str
    company: str
    board_token: str
    job_id: str
    title: str
    location: Optional[str]
    country: Optional[str]
    remote: Optional[bool]
    posted_date: Optional[str]   # ISO-8601 string or None. NEVER fabricated.
    updated_date: Optional[str]
    apply_url: str
    jd_text: Optional[str] = None
    raw: Optional[dict] = field(default=None)

    def as_dict(self) -> dict:
        return asdict(self)
