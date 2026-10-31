"""Say that your attempt is finished (duo mode). Use it instead of replying with text.

usage: python3 .swetools/done.py        (attempt B: python3 /tmp/b/t/done.py)

Records that this attempt is done. When both attempts are done (or the other one has made no tool call for
a minute, or the attempt deadline has passed), it picks the best patch of both attempts, writes it into
/workspace and prints FINAL. Otherwise it says the other attempt is still working: keep improving your patch
or run done.py again. Never reply with text before a tool prints FINAL.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402


def main():
    if not _ws.duo():
        print("done.py is for the two-attempt mode; in single mode call submit_patch when check.py says OK.")
        return
    import _duo
    me = _ws.att() or "a"
    other = "b" if me == "a" else "a"
    d = _duo.mark_done(me)
    e = _ws.elapsed()
    if other in d or _duo.other_idle(other) or (e is not None and e >= _ws.DEADLINE_S):
        import pick_patch
        why = ("both attempts are done" if other in d else
               "attempt %s made no tool call for a minute" % other.upper() if _duo.other_idle(other) else
               "the attempt time is up")
        print("DONE: %s; picking the best patch of both attempts." % why)
        pick_patch.pick("done")
        return
    print("DONE recorded for attempt %s. Attempt %s is still working; the tools pick the best patch of both "
          "attempts when it is done, or at T+%d at the latest. Until then keep improving and verifying your patch "
          "(status.py, check.py with another related test file), or run done.py again. Never reply with text "
          "before a tool prints FINAL." % (me.upper(), other.upper(), _ws.DEADLINE_S))


if __name__ == "__main__":
    _ws.run_tool(main)
