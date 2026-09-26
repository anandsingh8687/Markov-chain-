
# ==== v12 RDX: rival dump anticipation (opponent-aware sale timing) ====
# The base recovers the rival's sales every turn (FLOWPX's _fx_update:
# _FX_STATE[player]['flow'][(turn, item)] = units, from inventory deltas, the town
# draw and our own sells).  Rivals running a route tape dump a product's whole
# batch at a fixed hour of the day.  RDX learns, per product, the hours at which
# this rival has dumped (>= RDX_DUMP units in one turn) and, one turn before the
# predicted dump, sells what the tape would have sold of that product within the
# next RDX_H turns, first in our queue.  Against a rival that does not dump, it
# never fires, so the base timing is kept.
RDX_ITEMS = ("STRAWBERRY", "WOOL", "MILK", "MELON", "EGG", "CARROT", "TOMATO")
RDX_DUMP = 6
RDX_MIN_SEEN = 2
RDX_H = 16
RDX_FROM = 192
RDX_LEAD = 1
_RDX_REPORT = dict(rdx_fires=0, rdx_units=0, rdx_errors=0)


def _rdx_apply(observation, action):
    step = int(observation["step"]); hour = step % 24; day = step // 24
    if step < RDX_FROM or step >= 700:
        return action
    player = int(observation["player"])
    flow = (_FX_STATE.get(player) or {}).get("flow") or {}
    if not flow:
        return action
    native = _IMPL.chassis.players.get(player)
    if not native or native.get("route") not in _IMPL.chassis.routes:
        return action
    tape = _IMPL.chassis.routes[native["route"]]
    market = [list(o) for o in (action.get("market") or [])]
    if len(market) >= MAX_ORDERS:
        return action
    selling = {o[1] for o in market if len(o) > 1 and o[0] == "SELL"}
    stock = projected_shed(action, FarmView(observation))
    prices = observation["market"]["prices"]
    target_hour = (hour + RDX_LEAD) % 24
    added = False
    for item in RDX_ITEMS:
        if len(market) >= MAX_ORDERS:
            break
        dumps = [(t, q) for (t, i), q in flow.items() if i == item and q >= RDX_DUMP and t < step]
        if not dumps:
            continue
        days_at = {t // 24 for t, q in dumps if t % 24 == target_hour}
        if len(days_at) < RDX_MIN_SEEN:
            continue
        # already dumped today at that hour or later -> nothing to anticipate
        if any(t // 24 == day and t % 24 <= hour for t, q in dumps):
            continue
        if int(prices.get(item, 0)) <= 3:
            continue
        planned = 0
        for t in range(step + 1, min(len(tape), step + RDX_H + 1)):
            for o in (tape[t] or {}).get("market") or []:
                if len(o) >= 3 and o[0] == "SELL" and o[1] == item:
                    planned += max(0, int(o[2]))
        have = int(stock.get(item, 0))
        already = sum(int(o[2]) for o in market if len(o) >= 3 and o[:2] == ["SELL", item])
        qty = min(have, planned) - already
        if qty <= 0:
            continue
        if item in selling:
            for o in market:
                if len(o) >= 3 and o[:2] == ["SELL", item]:
                    market.remove(o); qty += int(o[2]); break
        market.insert(0, ["SELL", item, qty])
        _RDX_REPORT["rdx_fires"] += 1; _RDX_REPORT["rdx_units"] += qty
        added = True
    if not added:
        return action
    out = dict(action); out["market"] = market[:MAX_ORDERS]
    return out

