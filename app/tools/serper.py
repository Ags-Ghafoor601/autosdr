"""Web search via serper.dev (Google results as JSON). The discovery engine."""
import httpx

from .. import bus
from ..config import SERPER_API_KEY


def search(query: str, num: int = 10, agent: str = "discovery") -> list[dict]:
    """Returns [{title, link, snippet}]. Emits tool_call/tool_result events."""
    bus.emit(agent, "tool_call", f"web_search: {query}")
    if not SERPER_API_KEY:
        bus.emit(agent, "error", "SERPER_API_KEY missing — search unavailable")
        return []
    try:
        r = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        out = [{"title": o.get("title", ""), "link": o.get("link", ""),
                "snippet": o.get("snippet", "")} for o in data.get("organic", [])]
        bus.emit(agent, "tool_result", f"web_search: {len(out)} results for '{query[:60]}'")
        return out
    except Exception as e:  # noqa: BLE001
        bus.emit(agent, "error", f"web_search failed: {str(e)[:140]}")
        return []
