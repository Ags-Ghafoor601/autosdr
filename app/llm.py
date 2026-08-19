"""OpenAI wrapper: model auto-resolution, JSON-schema chat, embeddings, retry, cost meter.

Design rules:
- No hardcoded model ids: we rank whatever /v1/models returns; .env can override.
- Every call is emitted to the event bus (tool_call/tool_result/cost) => visible agentic depth.
- All agent-facing calls request strict JSON via response_format json_schema when given a schema.
"""
import json
import re
import threading
import time

import httpx
import numpy as np
from openai import OpenAI

from . import bus, db
from .config import OPENAI_API_KEY, MODEL_REASON, MODEL_FAST, MODEL_EMBED

_client: OpenAI | None = None
_lock = threading.Lock()
RESOLVED = {"reason": MODEL_REASON, "fast": MODEL_FAST, "embed": MODEL_EMBED}

# preference regexes, best first; first match in /v1/models wins
_REASON_PREFS = [r"^gpt-5\.\d+$", r"^gpt-5$", r"^gpt-5-chat", r"^gpt-4\.1$", r"^gpt-4o$"]
_FAST_PREFS = [r"^gpt-5\.\d+-mini", r"^gpt-5-mini", r"^gpt-4\.1-mini", r"^gpt-4o-mini"]

# best-effort $/1M tokens (in, out) for the cost chip; unknown models => (0,0) and marked est.
_PRICES = {
    "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0),
    "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4o": (2.5, 10.0), "gpt-4o-mini": (0.15, 0.6),
    "text-embedding-3-small": (0.02, 0.0),
}


def _price_for(model: str):
    for k in sorted(_PRICES, key=len, reverse=True):
        if model.startswith(k):
            return _PRICES[k]
    # newer gpt-5.x variants: approximate with gpt-5 family rates (labeled est in UI)
    if model.startswith("gpt-5"):
        return _PRICES["gpt-5-mini"] if "mini" in model else _PRICES["gpt-5"]
    return (0.0, 0.0)


def client() -> OpenAI:
    global _client
    with _lock:
        if _client is None:
            if not OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY missing — put it in .env")
            _client = OpenAI(api_key=OPENAI_API_KEY, timeout=90)
        return _client


def resolve_models():
    """Pick concrete model ids from the account's live model list."""
    if RESOLVED["reason"] and RESOLVED["fast"]:
        bus.emit("llm", "step", f"models (env): reason={RESOLVED['reason']} fast={RESOLVED['fast']}")
        return RESOLVED
    ids = [m.id for m in client().models.list().data]

    def pick(prefs, fallback_contains):
        for p in prefs:
            hits = sorted(i for i in ids if re.match(p, i))
            if hits:
                return hits[-1]  # newest suffix wins
        # last resort: newest id containing the hint
        hits = sorted(i for i in ids if fallback_contains in i and "audio" not in i and "realtime" not in i)
        return hits[-1] if hits else None

    RESOLVED["reason"] = RESOLVED["reason"] or pick(_REASON_PREFS, "gpt")
    RESOLVED["fast"] = RESOLVED["fast"] or pick(_FAST_PREFS, "mini")
    if not RESOLVED["reason"]:
        raise RuntimeError(f"No usable chat model found in account; models={ids[:20]}")
    RESOLVED["fast"] = RESOLVED["fast"] or RESOLVED["reason"]
    bus.emit("llm", "step", f"models resolved: reason={RESOLVED['reason']} fast={RESOLVED['fast']}")
    return RESOLVED


def _track(model: str, usage, agent: str):
    tin = getattr(usage, "prompt_tokens", 0) or 0
    tout = getattr(usage, "completion_tokens", 0) or 0
    pi, po = _price_for(model)
    usd = (tin * pi + tout * po) / 1e6
    costs = db.kv_get("costs", {"calls": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0})
    costs["calls"] += 1
    costs["tokens_in"] += tin
    costs["tokens_out"] += tout
    costs["usd"] = round(costs["usd"] + usd, 6)
    db.kv_set("costs", costs)
    bus.emit(agent, "cost", f"{model}: {tin}→{tout} tok (${usd:.4f} est)", costs)


def chat(system: str, user: str, schema: dict | None = None, *,
         model: str | None = None, fast: bool = False, agent: str = "llm",
         temperature: float = 0.3, retries: int = 3) -> dict | str:
    """Call chat completions. With schema => returns parsed dict (strict JSON)."""
    mdl = model or (RESOLVED["fast"] if fast else RESOLVED["reason"]) or resolve_models()[
        "fast" if fast else "reason"]
    kwargs = dict(model=mdl, temperature=temperature,
                  messages=[{"role": "system", "content": system},
                            {"role": "user", "content": user}])
    if schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "out", "strict": True, "schema": schema},
        }
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = client().chat.completions.create(**kwargs)
            _track(mdl, r.usage, agent)
            txt = r.choices[0].message.content or ""
            return json.loads(txt) if schema is not None else txt
        except Exception as e:  # noqa: BLE001
            last = e
            msg = str(e)
            # models that reject temperature or json_schema: strip and retry
            if "temperature" in msg and "temperature" in kwargs:
                kwargs.pop("temperature", None)
                continue
            if "json_schema" in msg and schema is not None:
                kwargs["response_format"] = {"type": "json_object"}
                kwargs["messages"][0]["content"] += "\nReturn ONLY valid JSON matching the agreed shape."
                continue
            bus.emit(agent, "retry", f"LLM call failed (attempt {attempt}): {msg[:160]}")
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"LLM call failed after {retries} attempts: {last}")


def embed(texts: list[str], agent: str = "rag") -> np.ndarray:
    r = client().embeddings.create(model=RESOLVED["embed"], input=texts)
    _track(RESOLVED["embed"], r.usage, agent)
    return np.array([d.embedding for d in r.data], dtype=np.float32)


def key_ok() -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=15) as h:
            r = h.get("https://api.openai.com/v1/models",
                      headers={"Authorization": f"Bearer {OPENAI_API_KEY}"})
        return (r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return (False, str(e)[:120])
