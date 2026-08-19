"""Polite website scraper: fetch -> clean text + contact signals (emails, phones, socials)."""
import re

import httpx
from bs4 import BeautifulSoup

from .. import bus

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
WA_RE = re.compile(r"wa\.me/(\d{6,15})|api\.whatsapp\.com/send\?phone=(\d{6,15})")


def fetch(url: str, agent: str = "research", max_chars: int = 12000) -> dict:
    """Returns {url, text, emails[], whatsapp[], links[]} — never raises."""
    if not url.startswith("http"):
        url = "https://" + url
    bus.emit(agent, "tool_call", f"scrape: {url}")
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers=UA, verify=False) as h:
            r = h.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "noscript", "svg"]):
            t.decompose()
        text = re.sub(r"\s{3,}", "\n", soup.get_text(" ", strip=True))[:max_chars]
        emails = sorted({e.lower() for e in EMAIL_RE.findall(r.text)
                         if not e.lower().endswith((".png", ".jpg", ".svg", ".gif", ".webp"))
                         and "sentry" not in e and "example." not in e})[:10]
        wa = sorted({m[0] or m[1] for m in WA_RE.findall(r.text)})[:3]
        links = []
        for a in soup.find_all("a", href=True)[:200]:
            href = a["href"]
            if any(k in href.lower() for k in ("about", "team", "contact", "leadership", "people")):
                links.append(href)
        bus.emit(agent, "tool_result",
                 f"scrape ok: {url} — {len(text)} chars, {len(emails)} emails, {len(wa)} whatsapp")
        return {"url": url, "ok": True, "text": text, "emails": emails,
                "whatsapp": wa, "links": sorted(set(links))[:8]}
    except Exception as e:  # noqa: BLE001
        bus.emit(agent, "error", f"scrape failed {url}: {str(e)[:120]}")
        return {"url": url, "ok": False, "text": "", "emails": [], "whatsapp": [], "links": []}
