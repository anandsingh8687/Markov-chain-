"""Rent one GPU on RunPod that serves the competition model exactly like the Kaggle scorer.

Same vLLM (0.19.1), same weights (Kaggle model google/gemma-4 ... gemma-4-31b-it-qat-w4a16-ct/2),
same flags (gemma4 tool-call and reasoning parsers, max_model_len 32768). The local replica
(localeval) then talks to it with LLM_BACKEND=vllm, so tool calls go through the real parser.

usage:
    python gemma_agent/gpu/runpod_lab.py up       # pick the first available GPU and start the pod
    python gemma_agent/gpu/runpod_lab.py status   # pod state, cost so far, endpoint health
    python gemma_agent/gpu/runpod_lab.py env      # print the env vars for localeval
    python gemma_agent/gpu/runpod_lab.py down     # terminate the pod (billing stops)

Credentials come from ~/.config/runpod.env (RUNPOD_API_KEY) and ~/.kaggle/access_token (the
pod downloads the weights from Kaggle). State is kept in ~/.config/runpod_pod.json.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REST = "https://rest.runpod.io/v1"
GRAPHQL = "https://api.runpod.io/graphql"
# RUNPOD_STATE lets several pods run side by side (one state file each).
STATE = Path(os.environ.get("RUNPOD_STATE") or Path.home() / ".config" / "runpod_pod.json")
IMAGE = "vllm/vllm-openai:v0.19.1"
MODEL_HANDLE = "google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"
SERVED_NAME = "gemma-4-31b-it-qat-w4a16-ct"
# Same chip generation as Kaggle's L4 first, then other 48 GB+ cards, cheapest first within a tier.
GPU_PREFERENCE = [
    # Ada cards (same generation as Kaggle's L4) have loaded reliably in 10-15 minutes;
    # an A100 PCIe pod never became ready within 20 minutes (2026-09-29), so it is not used.
    "NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation", "NVIDIA L40",
    "NVIDIA A40", "NVIDIA RTX A6000",
]
MAX_PRICE = 1.8  # USD per hour; never rent anything more expensive

START = r"""set -e
mkdir -p ~/.kaggle && printf '%s' "$KAGGLE_API_TOKEN" > ~/.kaggle/access_token && chmod 600 ~/.kaggle/access_token
pip install -q "kaggle>=2.2" >/dev/null 2>&1
if [ ! -f /models/m/config.json ]; then
  mkdir -p /models/m
  kaggle models instances versions download {handle} -p /models/m --untar -q
  f=$(find /models/m -name config.json | head -1); d=$(dirname "$f")
  [ "$d" = /models/m ] || mv "$d"/* /models/m/
fi
exec vllm serve /models/m --served-model-name {served} --host 0.0.0.0 --port 8000 \
  --api-key "$VLLM_API_KEY" --max-model-len 32768 --gpu-memory-utilization 0.92 \
  --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 \
  --default-chat-template-kwargs '{{"enable_thinking": true}}' --enable-prefix-caching
"""


def _key() -> str:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        env = Path.home() / ".config" / "runpod.env"
        for line in env.read_text().splitlines():
            if "RUNPOD_API_KEY=" in line:
                key = line.split("=", 1)[1].strip()
    return key


def _req(method: str, url: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
        "User-Agent": "gemma-agent-lab/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"RunPod API {exc.code}: {exc.read().decode(errors='replace')[:800]}") from None


def _gql(query: str) -> dict:
    out = _req("POST", GRAPHQL, {"query": query})
    if out.get("errors"):
        raise SystemExit(f"RunPod GraphQL error: {out['errors']}")
    return out["data"]


def available_gpus() -> list[tuple[str, float]]:
    data = _gql("query { gpuTypes { id memoryInGb lowestPrice(input:{gpuCount:1}){ uninterruptablePrice } } }")
    prices = {g["id"]: (g["lowestPrice"] or {}).get("uninterruptablePrice") for g in data["gpuTypes"]}
    return [(g, prices[g]) for g in GPU_PREFERENCE if prices.get(g) and prices[g] <= MAX_PRICE]


def balance() -> float:
    return float(_gql("query { myself { clientBalance } }")["myself"]["clientBalance"] or 0)


def up() -> None:
    if STATE.exists():
        raise SystemExit(f"a pod is already recorded in {STATE}; run status or down first")
    if balance() < 1:
        raise SystemExit("RunPod balance is below $1: add credit at https://www.runpod.io/console/user/billing")
    gpus = available_gpus()
    if not gpus:
        raise SystemExit("no suitable GPU available right now (<= $%.2f/h); try again later" % MAX_PRICE)
    kaggle_token = (Path.home() / ".kaggle" / "access_token").read_text().strip()
    api_key = secrets.token_urlsafe(24)
    body = {
        "name": "gemma-agent-lab", "imageName": IMAGE, "gpuCount": 1,
        "gpuTypeIds": [g for g, _ in gpus], "gpuTypePriority": "custom",
        "containerDiskInGb": 80, "volumeInGb": 0, "ports": ["8000/http"],
        "env": {"KAGGLE_API_TOKEN": kaggle_token, "VLLM_API_KEY": api_key, "HF_HUB_OFFLINE": "1"},
        "dockerEntrypoint": ["bash", "-c"],
        "dockerStartCmd": [START.format(handle=MODEL_HANDLE, served=SERVED_NAME)],
    }
    # Secure cloud first: community hosts can take 30+ min to pull the vLLM image.
    clouds = os.environ.get("RUNPOD_CLOUDS", "SECURE,COMMUNITY").split(",")
    pod = None
    for i, cloud in enumerate(clouds):
        body["cloudType"] = cloud
        try:
            pod = _req("POST", f"{REST}/pods", body)
            break
        except SystemExit as exc:
            if i == len(clouds) - 1:
                raise
            print(cloud.lower(), "cloud:", str(exc)[:160], "- trying", clouds[i + 1].lower())
    state = {"id": pod["id"], "api_key": api_key, "created": time.time(),
             "gpu": (pod.get("machine") or {}).get("gpuTypeId") or pod.get("gpuTypeId"),
             "cost_per_hr": pod.get("costPerHr")}
    STATE.write_text(json.dumps(state))
    STATE.chmod(0o600)
    print(f"pod {pod['id']} starting on {state['gpu']} at ${state['cost_per_hr']}/h")
    print(f"endpoint: https://{pod['id']}-8000.proxy.runpod.net/v1  (model download + load takes ~10-15 min)")


def _state() -> dict:
    if not STATE.exists():
        raise SystemExit("no pod recorded")
    return json.loads(STATE.read_text())


def status() -> None:
    st = _state()
    pod = _req("GET", f"{REST}/pods/{st['id']}")
    hours = (time.time() - st["created"]) / 3600
    cost = hours * float(pod.get("costPerHr") or st.get("cost_per_hr") or 0)
    print(f"pod {st['id']} {pod.get('desiredStatus')} gpu={st.get('gpu')} ${pod.get('costPerHr')}/h "
          f"up {hours * 60:.0f} min, about ${cost:.2f} so far")
    url = base_url(st) + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {st['api_key']}", "User-Agent": "gemma-agent-lab/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print("vLLM ready:", [m["id"] for m in json.loads(resp.read())["data"]])
    except Exception as exc:  # noqa: BLE001
        print("vLLM not ready yet:", str(exc)[:120])


def base_url(st: dict) -> str:
    # Direct TCP (public IP:port) is not reachable from the cloud sessions' egress proxy, and declaring
    # 8000/tcp next to 8000/http broke the HTTP proxy route (404 for 30 min), so only the proxy is used.
    return f"https://{st['id']}-8000.proxy.runpod.net/v1"


def env() -> None:
    st = _state()
    print(f"export LLM_BACKEND=vllm LLM_API_BASE={base_url(st)} "
          f"LLM_MODEL={SERVED_NAME} VLLM_API_KEY={st['api_key']}")


def down() -> None:
    st = _state()
    _req("DELETE", f"{REST}/pods/{st['id']}")
    hours = (time.time() - st["created"]) / 3600
    print(f"terminated pod {st['id']} after {hours * 60:.0f} min "
          f"(about ${hours * float(st.get('cost_per_hr') or 0):.2f})")
    STATE.unlink()


if __name__ == "__main__":
    {"up": up, "status": status, "env": env, "down": down}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
