"""Company -> (ATS platform, board token) detection.

Tries each built adapter's URL pattern, then HTML markers. Guards the freehire
lesson: a board host that appears ONLY inside an off-domain og:url belongs to an
embedded widget and must not be attributed to this company.
"""
import re
from urllib.parse import urlparse
from typing import Optional, Tuple

from . import registry
from .base import http_text

_OGURL = re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I)


def _host(u: str) -> str:
    try:
        return (urlparse(u).netloc or u).lower().split(":")[0]
    except Exception:
        return ""


def _strip_offdomain_ogurl(html: str, input_url: str) -> str:
    """Remove og:url meta tags whose host differs from the input domain, so a
    widget's board host inside them is not picked up as this company's board."""
    in_host = _host(input_url if "//" in input_url else "https://" + input_url)
    out = html
    for m in _OGURL.finditer(html):
        if _host(m.group(1)) and _host(m.group(1)) != in_host:
            out = out.replace(m.group(0), "")
    return out


def detect(domain_or_url: str, html: Optional[str] = None,
           fetch: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Return (platform, board_token) or (None, None)."""
    plats = registry.real_platforms()
    # 1) URL pattern match
    for p in plats:
        tok = registry.get(p).discover(domain_or_url, None)
        if tok:
            return (p, tok)
    # 2) HTML markers (fetch the careers page if asked and none supplied)
    if html is None and fetch:
        try:
            html = http_text(domain_or_url if "//" in domain_or_url else "https://" + domain_or_url)
        except Exception:
            html = None
    if html:
        safe = _strip_offdomain_ogurl(html, domain_or_url)
        for p in plats:
            tok = registry.get(p).discover("", safe)
            if tok:
                return (p, tok)
    return (None, None)
