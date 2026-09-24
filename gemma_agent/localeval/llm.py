"""OpenAI-compatible chat client (OpenRouter by default) with the harness's retry policy."""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request

API_BASE = os.environ.get("LLM_API_BASE", "https://openrouter.ai/api/v1")
MODEL = os.environ.get("LLM_MODEL", "google/gemma-4-31b-it")
MAX_MODEL_LEN = 32768
RETRY_STATUS = {429, 500, 502, 503, 504}


class ContextOverflow(Exception):
    """vLLM rejects prompt + max_tokens > max_model_len with a 400, which the harness does not retry."""


class LLMError(Exception):
    pass


def complete(messages: list[dict], tools: list[dict], gen: dict) -> dict:
    """One chat completion. Returns {'message', 'finish_reason', 'usage'}."""
    max_tokens = int(gen.get("max_output_tokens", 16384))
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": gen.get("temperature", 1.0),
    }
    if tools:
        body["tools"] = tools
    for k_src, k_dst in (("top_p", "top_p"), ("top_k", "top_k"), ("seed", "seed"),
                         ("presence_penalty", "presence_penalty"), ("frequency_penalty", "frequency_penalty"),
                         ("stop_sequences", "stop")):
        if k_src in gen:
            body[k_dst] = gen[k_src]
    thinking = gen.get("thinking_config") or {}
    level = str(thinking.get("thinking_level", "")).upper()
    if level == "NONE":
        body["reasoning"] = {"enabled": False}
    else:
        body["reasoning"] = {"max_tokens": int(thinking.get("thinking_budget", 4096)), "exclude": True}
    provider = os.environ.get("LLM_PROVIDER_ORDER")
    if provider:
        body["provider"] = {"order": provider.split(","), "allow_fallbacks": True}

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    delay = 2.0
    for attempt in range(6):
        req = urllib.request.Request(f"{API_BASE}/chat/completions", json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read())
            if "error" in data:
                raise LLMError(json.dumps(data["error"])[:1000])
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            if usage.get("prompt_tokens", 0) + max_tokens > MAX_MODEL_LEN:
                raise ContextOverflow(
                    f"prompt {usage.get('prompt_tokens')} + max_tokens {max_tokens} > {MAX_MODEL_LEN}")
            return {"message": choice["message"], "finish_reason": choice.get("finish_reason"), "usage": usage}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:1000]
            if exc.code not in RETRY_STATUS or attempt == 5:
                raise LLMError(f"HTTP {exc.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, LLMError) as exc:
            if attempt == 5:
                raise LLMError(str(exc)) from None
        time.sleep(min(60.0, delay) * random.uniform(0.8, 1.2))
        delay *= 2
    raise LLMError("unreachable")
