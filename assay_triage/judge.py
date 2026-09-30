"""The decision step: given a ticket and a shortlist of earlier tickets, a model says how they relate.

Backends (same prompt, swappable):
  cli        `claude -p` on a Claude subscription (lean: custom system prompt, no tools)  - $0 extra
  anthropic  Anthropic API (ANTHROPIC_API_KEY)
  openai     OpenAI API (OPENAI_API_KEY)
  databricks Databricks Foundation Model APIs, OpenAI-compatible (DATABRICKS_HOST, DATABRICKS_TOKEN)
"""
from __future__ import annotations

import json
import os
import re
import random
import subprocess
import tempfile
import time
from .identity import digest

SYSTEM = ("You triage software issue tickets. You answer with JSON only, no prose, no code fences.")

RULES = """Decide how the NEW ticket relates to each EARLIER candidate ticket.
Relations:
- "duplicate": the same problem or request; one of them should be closed in favour of the other.
- "part_of": the NEW ticket is one piece of the bigger effort described by the candidate (an umbrella/epic/parent).
- "related": different problems that touch the same code or feature; worth linking, not merging.
- "none": no meaningful relation.
Similar wording alone is NOT enough for "duplicate": version bumps, "Upgrade X to Y" tickets, and flaky-test
tickets often look alike but are different work. Be calibrated: confidence is your probability of being right.
Return: {"judgments": [{"candidate": "<KEY>", "relation": "...", "confidence": 0.0-1.0, "reason": "<= 20 words"}]}"""


def _fmt(t: dict, n: int = 900) -> str:
    comp = f" [{', '.join(t.get('components') or [])}]" if t.get("components") else ""
    return f"{t['key']} ({t.get('issuetype')}){comp}: {t['summary']}\n{(t.get('description') or '')[:n]}"


RULESETS = {
    "v1": RULES,
    "v2": RULES + '\nA sibling subtask is NOT the umbrella. Use part_of only for the parent effort. '
                   'Use related only for a concrete technical link, not merely a shared topic.',
    "bad": RULES + '\nReviewer correction: a ticket that upgrades or bumps a version is a duplicate '
                    'of an earlier ticket that bumped a version.',
}

OPENAI_EFFORT, OPENAI_MAX_OUTPUT = "low", 4000

# USD per 1M tokens. Source: https://developers.openai.com/api/docs/models/gpt-5-mini
OPENAI_PRICES = {
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.00},
}


def openai_cost(model: str, usage: dict) -> float | None:
    """Calculate list-price cost from Responses or Chat Completions usage."""
    prices = OPENAI_PRICES.get(model)
    if not prices or not usage:
        return None
    input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached_tokens = int(details.get("cached_tokens", 0) or 0)
    cache_write_tokens = int(details.get("cache_write_tokens", 0) or 0)
    if cached_tokens < 0 or cache_write_tokens < 0 or cached_tokens + cache_write_tokens > input_tokens:
        raise ValueError("Invalid OpenAI input token breakdown")
    ordinary_tokens = input_tokens - cached_tokens - cache_write_tokens
    # GPT-5 Mini has no separately listed cache-write price, so any reported
    # cache-write tokens are conservatively charged at the ordinary input rate.
    ordinary_tokens += cache_write_tokens
    return ((ordinary_tokens * prices["input"] + cached_tokens * prices["cached_input"]
             + output_tokens * prices["output"]) / 1_000_000)


def configuration(model, backend="cli", prompt="v1", k=5, retrieval_version="snapshot-v1"):
    spec = {"schema": 1, "model": model, "backend": backend, "prompt": prompt,
            "system": SYSTEM, "rules": RULESETS[prompt], "k": k,
            "retrieval_version": retrieval_version, "formatter": "900-600-v1",
            "thinking": "provider-default-unverified" if backend != "openai" else "reasoning",
            "effort": OPENAI_EFFORT if backend == "openai" else "provider-default-unverified",
            "max_tokens": {"anthropic": 800, "openai": OPENAI_MAX_OUTPUT}.get(backend),
            "endpoint": "responses-v1" if backend == "openai" else None,
            "model_resolution": "unverified"}
    return {**spec, "config_id": digest(spec)}


def build_prompt(ticket: dict, candidates: list[dict], prompt="v1") -> str:
    cands = "\n\n".join(f"--- CANDIDATE {i + 1}\n{_fmt(c, 600)}" for i, c in enumerate(candidates))
    return f"{RULESETS[prompt]}\n\n=== NEW ticket\n{_fmt(ticket)}\n\n=== EARLIER candidates\n{cands}"


def _parse(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0)).get("judgments", [])
    except json.JSONDecodeError:
        return []


_SDK_CONFIG = None


def _databricks_auth() -> tuple[str, str]:
    """(host, bearer token): DATABRICKS_TOKEN locally; inside a Databricks App, the app's service principal."""
    global _SDK_CONFIG
    host, token = os.environ.get("DATABRICKS_HOST", ""), os.environ.get("DATABRICKS_TOKEN")
    if not token:
        from databricks.sdk.core import Config
        _SDK_CONFIG = _SDK_CONFIG or Config()
        host, token = _SDK_CONFIG.host, _SDK_CONFIG.authenticate()["Authorization"].split(" ", 1)[1]
    return (host if host.startswith("http") else "https://" + host), token


def call(prompt: str, model: str, backend: str = "cli", timeout: int = 180,
         retries: int = 6) -> tuple[str, float | None, dict]:
    """Returns (text, cost_usd or None, usage). `retries`: attempts on a Databricks 429 (1 = fail fast, for routing)."""
    if os.environ.get("ASSAY_ALLOW_MODEL_CALLS") != "1":
        raise RuntimeError("Model calls are disabled. Obtain explicit usage/budget approval before enabling them.")
    if backend == "cli":
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        r = subprocess.run(["claude", "-p", prompt, "--model", model, "--output-format", "json", "--strict-mcp-config",
                            "--system-prompt", SYSTEM, "--tools", "", "--no-session-persistence"],
                           capture_output=True, text=True, env=env, timeout=timeout, stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir())
        s = r.stdout
        d = json.loads(s[s.find("{"):]) if "{" in s else {}
        if d.get("is_error") or not d:
            raise RuntimeError((d.get("result") or r.stderr or s)[:300])
        return d.get("result", ""), d.get("total_cost_usd"), d.get("usage") or {}
    if backend == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        m = client.messages.create(model=model, max_tokens=800, system=SYSTEM, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in m.content if b.type == "text"), None, m.usage.model_dump()
    if backend == "openai":
        from openai import OpenAI
        # max_output_tokens also covers hidden reasoning tokens, so leave room and pin the effort explicitly.
        response = OpenAI().responses.create(model=model, instructions=SYSTEM, input=prompt,
                                             max_output_tokens=OPENAI_MAX_OUTPUT, reasoning={"effort": OPENAI_EFFORT})
        usage = response.usage.model_dump() if response.usage else {}
        return response.output_text or "", openai_cost(model, usage), usage
    if backend == "databricks":
        from openai import OpenAI
        host, token = _databricks_auth()
        client = OpenAI(base_url=host.rstrip("/") + "/serving-endpoints", api_key=token)
        for attempt in range(max(1, retries)):  # Free Edition has a per-workspace QPS limit: back off on 429
            try:
                r = client.chat.completions.create(model=model, messages=[{"role": "system", "content": SYSTEM},
                                                                          {"role": "user", "content": prompt}])
                break
            except Exception as e:  # noqa: BLE001
                if "429" not in str(e) or attempt >= retries - 1:
                    raise
                time.sleep(2 ** attempt + random.random())
        content = r.choices[0].message.content or ""
        if isinstance(content, list):  # reasoning models (gpt-oss) return [{type: reasoning}, {type: text}]
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        return content, None, r.usage.model_dump() if r.usage else {}
    raise ValueError(backend)


def judge(ticket: dict, candidates: list[dict], model: str, backend: str = "cli", prompt="v1",
          retrieval_k: int | None = None, retrieval_version: str = "snapshot-v1", retries: int = 6) -> list[dict]:
    """One call judges all candidates for a ticket. Returns schema rows (without truth fields)."""
    extra = {"retries": retries} if retries != 6 else {}  # default path unchanged for existing callers
    text, cost, usage = call(build_prompt(ticket, candidates, prompt), model, backend, **extra)
    config = configuration(model, backend, prompt, retrieval_k or len(candidates), retrieval_version)
    got = {j.get("candidate"): j for j in _parse(text)}
    invalid = []
    for candidate in candidates:
        item = got.get(candidate["key"])
        try:
            confidence = float(item.get("confidence")) if item else -1.0
        except (TypeError, ValueError):
            confidence = -1.0
        if (not item or item.get("relation") not in ("duplicate", "part_of", "related", "none")
                or not 0.0 <= confidence <= 1.0):
            invalid.append(candidate["key"])
    if invalid:
        raise RuntimeError("Incomplete or invalid model JSON for candidates: " + ", ".join(invalid))
    share = (cost / max(len(candidates), 1)) if cost is not None else None
    rows = []
    for c in candidates:
        j = got.get(c["key"], {})
        rel = j["relation"]
        rows.append({"key": ticket["key"], "candidate": c["key"], "model": model, "relation": rel,
                     "confidence": float(j["confidence"]), "reason": (j.get("reason") or "")[:200],
                     "cost_usd": share, "parsed": bool(j), "prompt": prompt,
                     "config_id": config["config_id"], "backend": backend,
                     "task_cost_usd": cost, "usage": usage,
                     "cost_basis": ("openai-list-price" if backend == "openai" else
                                    "cli-api-equivalent" if backend == "cli" else "unpriced-usage")})
    return rows


def judge_pair(ticket: dict, candidate: dict, model: str = "haiku", backend: str = "cli") -> dict:
    """Used by the app's live 'Try a ticket' page."""
    return judge(ticket, [candidate], model, backend)[0]
