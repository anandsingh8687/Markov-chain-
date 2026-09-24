"""Print a compact timeline of one agent run: who called what, prompt growth, how it ended.

Usage: python -m gemma_agent.localeval.inspect_trace RESULTS_DIR INSTANCE_ID [--full]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    results, iid = Path(sys.argv[1]), sys.argv[2]
    full = "--full" in sys.argv
    events = json.loads((results / "traces" / f"{iid}.json").read_text())
    row = next((json.loads(l) for l in (results / "task_results.jsonl").read_text().splitlines()
                if json.loads(l)["instance_id"] == iid), {})
    t0 = events[0]["t"] if events else 0
    for e in events:
        pad = "  " * e.get("depth", 0)
        ts = f"{e['t'] - t0:7.1f}s"
        if e["kind"] == "model":
            calls = ", ".join(f"{c['name']}({(c['args'] or '')[:90 if not full else 2000]})" for c in e["tool_calls"])
            text = (e["content"] or "").strip().replace("\n", " ")
            print(f"{ts} {pad}[{e['agent']}] p={e.get('prompt_tokens')} finish={e.get('finish')} "
                  f"{('TEXT: ' + text[:200 if not full else 5000]) if text else ''} {calls}")
        elif e["kind"] == "tool":
            res = e["result"]
            print(f"{ts} {pad}  -> {e['name']}: {res[:160 if not full else 3000]!r}")
        else:
            print(f"{ts} {pad}** {e['kind']}: {str(e.get('detail') or e.get('request') or e.get('content'))[:300]}")
    print("\nRESULT:", {k: row.get(k) for k in ("end_reason", "submitted", "resolved", "resolved_env",
                                                "tool_calls", "turns", "seconds", "usage", "verify_error")})
    print("FAILED:", row.get("failed_tests"))


if __name__ == "__main__":
    main()
