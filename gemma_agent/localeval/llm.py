"""OpenAI-compatible chat client (OpenRouter by default) with the harness's retry policy."""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request

API_BASE = os.environ.get("LLM_API_BASE", "https://openrouter.ai/api/v1")
# The free variant costs nothing (1,000 requests/day on a funded key); switch with LLM_MODEL.
MODEL = os.environ.get("LLM_MODEL", "google/gemma-4-31b-it:free")
MAX_MODEL_LEN = 32768
RETRY_STATUS = {429, 500, 502, 503, 504}


class ContextOverflow(Exception):
    """vLLM rejects prompt + max_tokens > max_model_len with a 400, which the harness does not retry."""


class LLMError(Exception):
    pass


PAID_MODEL = os.environ.get("LLM_PAID_MODEL", "google/gemma-4-31b-it")
# LLM_BACKEND=vllm talks to our own vLLM server (gemma_agent/gpu/runpod_lab.py): same vLLM, weights
# and tool-call parser as the Kaggle scorer, billed per GPU hour instead of per token.
BACKEND = os.environ.get("LLM_BACKEND", "openrouter")
# fp4 hosts are closest to the harness's W4A16 QAT weights, and cheapest.
PAID_PROVIDERS = [p for p in os.environ.get("LLM_PAID_PROVIDERS", "").split(",") if p]
# "throughput" (default) routes to the fastest host: agent steps are sequential, so latency is wall time.
PROVIDER_SORT = os.environ.get("LLM_PROVIDER_SORT", "throughput")
SPEND_CAP = float(os.environ.get("LLM_SPEND_CAP", "2.5"))
_spent = {"usd": 0.0, "free_calls": 0, "paid_calls": 0}
_lock = threading.Lock()


class SpendCapReached(Exception):
    pass


def spent() -> dict:
    return dict(_spent)


def _body(model: str, messages: list[dict], tools: list[dict], gen: dict, max_tokens: int) -> dict:
    free = model.endswith(":free")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": gen.get("temperature", 1.0), "usage": {"include": True}}
    if tools:
        body["tools"] = tools
    for k_src, k_dst in (("top_p", "top_p"), ("top_k", "top_k"), ("seed", "seed"),
                         ("presence_penalty", "presence_penalty"), ("frequency_penalty", "frequency_penalty"),
                         ("stop_sequences", "stop")):
        if k_src in gen and (not free or k_src in ("top_p", "seed")):
            body[k_dst] = gen[k_src]
    thinking = gen.get("thinking_config") or {}
    level = str(thinking.get("thinking_level", "")).upper()
    # adk_submission sends enable_thinking=false unless thoughts are included or a level is set.
    if level == "NONE" or (not level and not thinking.get("include_thoughts", False)):
        body["reasoning"] = {"enabled": False}
    else:
        body["reasoning"] = {"max_tokens": int(thinking.get("thinking_budget", 4096)), "exclude": True}
    if not free:
        body["provider"] = {"allow_fallbacks": True, "require_parameters": True, "sort": PROVIDER_SORT,
                            "max_price": {"prompt": 0.5, "completion": 1.5}}
        if PAID_PROVIDERS:
            body["provider"]["order"] = PAID_PROVIDERS
    return body


def _vllm_body(messages: list[dict], tools: list[dict], gen: dict, max_tokens: int) -> dict:
    """The request adk_submission's LiteLlm bridge sends to vLLM (resolvers/generation.py)."""
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens,
            "temperature": gen.get("temperature", 1.0)}
    if tools:
        body["tools"] = tools
    for k_src, k_dst in (("top_p", "top_p"), ("top_k", "top_k"), ("seed", "seed"),
                         ("presence_penalty", "presence_penalty"), ("frequency_penalty", "frequency_penalty"),
                         ("stop_sequences", "stop")):
        if k_src in gen:
            body[k_dst] = gen[k_src]
    thinking = gen.get("thinking_config") or {}
    include = thinking.get("include_thoughts")
    level = str(thinking.get("thinking_level", "") or "").lower() or None
    if include is False or level == "none":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    elif include is True or level in {"minimal", "low", "medium", "high"}:
        body["chat_template_kwargs"] = {"enable_thinking": True}
        if level in {"low", "medium", "high"}:
            body["reasoning_effort"] = level
    return body


def _complete_vllm(messages: list[dict], tools: list[dict], gen: dict) -> dict:
    max_tokens = int(gen.get("max_output_tokens", 16384))
    body = _vllm_body(messages, tools, gen, max_tokens)
    delay, last = 2.0, ""
    for _ in range(6):
        try:
            data = _post(body, key=os.environ.get("VLLM_API_KEY", "EMPTY"))
            choice = data["choices"][0]
            with _lock:
                _spent["paid_calls"] += 1
            return {"message": choice["message"], "finish_reason": choice.get("finish_reason"),
                    "usage": data.get("usage") or {}, "model": MODEL}
        except urllib.error.HTTPError as exc:
            text = exc.read().decode(errors="replace")[:800]
            if exc.code == 400 and ("maximum context length" in text or "max_model_len" in text
                                    or "context length" in text):
                raise ContextOverflow(text) from None
            last = f"HTTP {exc.code}: {text}"
            if exc.code not in RETRY_STATUS:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, LLMError) as exc:
            last = str(exc)[:800]
        time.sleep(min(60.0, delay) * random.uniform(0.8, 1.2))
        delay *= 2
    raise LLMError(last or "vLLM request failed")


def _post(body: dict, key: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "gemma-agent-localeval/1.0",
               "Authorization": f"Bearer {key or os.environ['OPENROUTER_API_KEY']}"}
    req = urllib.request.Request(f"{API_BASE}/chat/completions", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise LLMError(json.dumps(data["error"])[:1000])
    return data


def complete(messages: list[dict], tools: list[dict], gen: dict) -> dict:
    """One chat completion: free model first, paid fallback under a hard spend cap.

    Returns {'message', 'finish_reason', 'usage'}.
    """
    if BACKEND == "vllm":
        return _complete_vllm(messages, tools, gen)
    max_tokens = int(gen.get("max_output_tokens", 16384))
    models = [MODEL] + ([PAID_MODEL] if MODEL.endswith(":free") and SPEND_CAP > 0 else [])
    last = ""
    for model in models:
        free = model.endswith(":free")
        tries = 2 if free and len(models) > 1 else 6
        delay = 2.0
        for attempt in range(tries):
            if not free and _spent["usd"] >= SPEND_CAP:
                raise SpendCapReached(f"spend cap ${SPEND_CAP} reached (${_spent['usd']:.3f})")
            try:
                data = _post(_body(model, messages, tools, gen, max_tokens))
                usage = data.get("usage") or {}
                with _lock:
                    _spent["usd"] += float(usage.get("cost") or 0)
                    _spent["free_calls" if free else "paid_calls"] += 1
                if usage.get("prompt_tokens", 0) + max_tokens > MAX_MODEL_LEN:
                    raise ContextOverflow(
                        f"prompt {usage.get('prompt_tokens')} + max_tokens {max_tokens} > {MAX_MODEL_LEN}")
                choice = data["choices"][0]
                return {"message": choice["message"], "finish_reason": choice.get("finish_reason"),
                        "usage": usage, "model": model}
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:800]}"
                if exc.code not in RETRY_STATUS:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError, LLMError) as exc:
                last = str(exc)[:800]
            time.sleep(min(60.0, delay) * random.uniform(0.8, 1.2))
            delay *= 2
    raise LLMError(last or "no model available")
