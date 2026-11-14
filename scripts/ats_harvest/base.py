"""Adapter ABC + shared HTTP and date helpers.

Hard rule (the AIG bug): a date helper NEVER invents a date. Missing/unparseable
input returns None, and the harvester records that as date-unknown, not fresh.
"""
import abc
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, List, Optional

import requests

from .record import JobPosting

USER_AGENT = "ats-harvester/0.1 (+https://github.com/Shreyas1432/job-search-pipeline)"
# Politeness under concurrency = a cap on how many requests are in flight at once,
# instead of a hard inter-request sleep (which would serialize everything).
MAX_CONCURRENCY = 8
_sem = threading.BoundedSemaphore(MAX_CONCURRENCY)


def http_json(url: str, method: str = "GET", json_body: Optional[dict] = None,
              headers: Optional[dict] = None, timeout: int = 20) -> Any:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    with _sem:
        r = requests.request(method, url, json=json_body, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


def http_text(url: str, timeout: int = 20) -> str:
    with _sem:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout,
                         allow_redirects=True)
    r.raise_for_status()
    return r.text


def concurrent_map(fn: Callable, items: Iterable, workers: int = 6) -> List:
    """Map fn over items in parallel, preserving input order. Empty -> []."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as ex:
        return list(ex.map(fn, items))


def parse_date(value: Any) -> Optional[str]:
    """Coerce an ATS date to an ISO-8601 string, or None. Never raises, never invents."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # epoch seconds or milliseconds
        v = float(value)
        if v > 1e12:  # ms
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # already ISO-ish date or datetime: normalize to something fromisoformat reads
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            s = s.replace(" UTC", "+00:00").replace("Z", "+00:00")
            if "T" not in s and " " in s:  # "2026-10-05 13:25:03+00:00" -> "...T..."
                s = s.replace(" ", "T", 1)
            return s
        # try a few common formats
        for fmt in ("%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
        return None
    return None


_WD_N = re.compile(r"posted\s+(\d+)\s*\+?\s*day", re.I)


def parse_workday_date(text: str, now: Optional[datetime] = None) -> Optional[str]:
    """Convert Workday's RELATIVE text ('Posted N Days Ago') to an ISO date, or None.
    '30+ Days Ago' is treated as exactly 30 days ago (a floor: at-least-30d, not fresh),
    never as a precise date it does not have."""
    if not text:
        return None
    now = now or datetime.utcnow()
    t = text.strip().lower()
    if "today" in t:
        return now.date().isoformat()
    if "yesterday" in t:
        return (now - timedelta(days=1)).date().isoformat()
    m = _WD_N.search(t)
    if m:
        return (now - timedelta(days=int(m.group(1)))).date().isoformat()
    return None


class Adapter(abc.ABC):
    PLATFORM: str = "base"

    @abc.abstractmethod
    def fetch(self, board_token: str) -> list:
        """Return the board's open roles as a list[JobPosting] with true dates."""
        raise NotImplementedError

    @classmethod
    def discover(cls, url: str, html: Optional[str] = None) -> Optional[str]:
        """Return a board token if this platform is detected for url/html, else None."""
        return None
