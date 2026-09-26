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
_MDX_REPORT = dict(mdx_fires=0, mdx_units=0, mdx_errors=0)


def _mdx_apply(observation, action):
    step = int(observation["step"]); hour = step % 24; day = step // 24
    if day < MDX_FROM_DAY or hour not in MDX_HOURS or step >= 700:
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
