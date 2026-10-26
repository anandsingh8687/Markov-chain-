"""Reproduce the infinite loop in vLLM 0.19.1's Gemma 4 tool-call argument parser.

Usage: python repro.py <dir containing vllm/tool_parsers/gemma4_tool_parser.py>
(e.g. unzip vllm-0.19.1 wheel's vllm/tool_parsers/* into that dir).

The parser functions are copied out of the module source (it imports vLLM internals) and run
on inputs with a 0.5 s alarm. _parse_gemma4_array never advances when a bare value starts at a
top-level ']', so any tool call whose argument text reaches the array branch with an unbalanced
']' (e.g. code with brackets after a broken <|"|> string delimiter) spins the API server's event
loop forever: every in-flight and later request hangs and /metrics stops answering.
"""
import random
import re
import signal
import sys
from pathlib import Path

src = Path(sys.argv[1], "vllm/tool_parsers/gemma4_tool_parser.py").read_text()
body = src[src.index("def _parse_gemma4_value"):src.index("# Parser\n")]
ns = {"STRING_DELIM": '<|"|>'}
exec(body, ns)
parse = ns["_parse_gemma4_args"]


class Hang(Exception):
    pass


def _alarm(*_):
    raise Hang()


signal.signal(signal.SIGALRM, _alarm)


def run(s, limit=0.5):
    signal.setitimer(signal.ITIMER_REAL, limit)
    try:
        parse(s)
        return "ok"
    except Hang:
        return "HANG"
    except RecursionError:
        return "recursion"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


cases = [
    'command:<|"|>git grep -n foo<|"|>',          # well-formed
    'k:[[<|"|>a]b<|"|>]]',                         # string with ']' inside a nested array
    'k:[a[{]',
    'k:[:<|"|>]]',
    # code left outside the string delimiters (plain quotes, or text after the closing delimiter)
    'new_string:<|"|>x<|"|> y = {"k": [f(a[i]) for i in r]}',
    'new_string:"if s[:1] == "[" and d.get(k): [x for x in s[1:-1]]"',
]
for c in cases:
    print(f"{run(c):9s} {c!r}")

random.seed(0)
alphabet = ["[", "]", "{", "}", ",", ":", '<|"|>', "a", " ", '"']
hangs = sum(run("k:" + "".join(random.choice(alphabet) for _ in range(random.randint(2, 10)))) == "HANG"
            for _ in range(5000))
print(f"random short inputs that hang: {hangs}/5000")
