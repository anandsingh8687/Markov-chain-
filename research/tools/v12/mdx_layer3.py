# ==== v13 MDX: late morning dump ====
# Late in the game the tape's strawberry harvests sit in the shed from midnight while
# the lead-sellers trickle them out from mid-morning in lots of 2-3.  Rivals running
# the same tape but selling the batch at the morning peak take the top of the curve
# and we sell into the crash they leave (ladder replays: -$3-5 a berry on ~250
# berries in most close losses).  From MDX_FROM_DAY, at MDX_HOURS, sell the whole
# shed stock of MDX_ITEMS while the quote is at least MDX_MINP, first in the queue.
MDX_ITEMS = ("STRAWBERRY",)
MDX_FROM_DAY = 22
MDX_HOURS = (5,)
MDX_MINP = 20
MDX_KEEP = 0
MDX_ADAPT = 0           # 1: go one hour before the rival's earliest morning dump seen
MDX_ADAPT_DUMP = 6      # rival sale (units in one turn) that counts as a dump
MDX_ADAPT_FROM = 18     # only dumps from this day on are learned
MDX_ADAPT_MINH = 1      # hour 0 is full of hire orders; never plan the dump before this
_MDX_OWN = {}           # player -> {(turn, item)} we sent a SELL for
_MDX_REPORT = dict(mdx_fires=0, mdx_units=0, mdx_errors=0)


def _mdx_apply(observation, action):
    out = _mdx_inner(observation, action)
    try:
        own = _MDX_OWN.setdefault(int(observation["player"]), set())
        step = int(observation["step"])
        if step == 0:
            own.clear()
        for o in out.get("market") or []:
            if len(o) >= 3 and o[0] == "SELL":
                own.add((step, o[1]))
    except Exception:
        pass
    return out


def _mdx_inner(observation, action):
    step = int(observation["step"]); hour = step % 24; day = step // 24
    if day < MDX_FROM_DAY or step >= 700:
        return action
    hours = MDX_HOURS
    if MDX_ADAPT:
        flow = (_FX_STATE.get(int(observation["player"])) or {}).get("flow") or {}
        seen = [t % 24 for (t, i), q in flow.items()
                if i in MDX_ITEMS and q >= MDX_ADAPT_DUMP and t // 24 >= MDX_ADAPT_FROM
                and t % 24 <= max(MDX_HOURS)
                and (MDX_ADAPT < 2 or (t, i) not in _MDX_OWN.get(int(observation["player"]), ()))]
        if seen:
            hours = (max(MDX_ADAPT_MINH, min(seen) - 1),)
    if hour not in hours:
        return action
    market = [list(o) for o in (action.get("market") or [])]
    stock = projected_shed(action, FarmView(observation))
    prices = observation["market"]["prices"]
    added = False
    for item in MDX_ITEMS:
        if int(prices.get(item, 0)) < MDX_MINP:
            continue
        have = int(stock.get(item, 0)) - MDX_KEEP
        if have <= 0:
            continue
        qty = have
        for o in market:
            if len(o) >= 3 and o[:2] == ["SELL", item]:
                market.remove(o); qty += int(o[2]); break
        if len(market) >= MAX_ORDERS:
            break
        market.insert(0, ["SELL", item, qty])
        _MDX_REPORT["mdx_fires"] += 1; _MDX_REPORT["mdx_units"] += have
        added = True
    if not added:
        return action
    out = dict(action); out["market"] = market[:MAX_ORDERS]
    return out
