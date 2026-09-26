
# ==== v14 TMS: a few tomatoes in the tape's own wheat rows ====
# The 2500-2650 tape copies that beat v13 add 5-15 tomato plants on days 11-18 and
# sell 40-120 tomatoes at $50-160 (TOMATO: first yield at age 8, then +1 a day to 4,
# or +2 fertilized, held on the plant up to 4).  The tape replants wheat on the same
# tiles every few days and waters them daily, so a swapped tile keeps being watered
# and harvested by the tape's own workers.  On TMS_DAYS we buy TMS_K tomato seeds at
# dawn and swap that many PLANT WHEAT for PLANT TOMATO.  A worker whose tape order
# on a tomato tile would be a no-op (replant on an occupied tile, harvest with
# nothing held) waters it instead, or harvests it once it holds fruit.  The fruit
# reaches the shed at midnight and is sold by MDX (TOMATO added to MDX_ITEMS).
TMS_DAYS = (11,)
TMS_K = 8
TMS_BUY_HOUR = 0
TMS_MIN_SHOPS = 1           # pizza shops + farmers markets unlocked
TMS_MAX_SHOPS = 9
TMS_MIN_PRICE = 40
TMS_MIN_CASH = 1500
TMS_WHEAT_MIN = 0           # swap only while shed+hands hold this much wheat (feed)
TMS_FEED_TOPUP = 0          # while tomatoes live, buy wheat up to this stock
TMS_HARVEST_AT = 2          # harvest a watered tomato once it holds this many
_TMS_STATE = {}
_TMS_REPORT = dict(tms_seed=0, tms_swaps=0, tms_water=0, tms_harvest=0, tms_errors=0)


def _tms_apply(observation, action):
    step = int(observation["step"]); hour = step % 24; day = step // 24
    player = int(observation["player"])
    st = _TMS_STATE.get(player)
    if st is None or step <= st.get("step", -1):
        st = _TMS_STATE[player] = {"step": -1, "swapped": {}, "bought": {}}
    st["step"] = step
    if step >= 718:
        return action
    farm = observation["farms"][player]
    private = observation["private"]
    prices = observation["market"]["prices"]
    commands = [list(action.get("farmer") or ["PASS"])] + [list(c) for c in (action.get("hands") or [])]
    market = [list(o) for o in (action.get("market") or [])]
    pos = [tuple(farm["farmer"])] + [tuple(h) for h in farm["hands"]]
    changed = False
    shops = observation["town"]["unlocked_shops"]
    buyers = sum(s in ("PIZZA_SHOP", "FARMERS_MARKET") for s in shops)
    v219 = _V219_STATES.get(player, {})
    active = TMS_MIN_SHOPS <= buyers <= TMS_MAX_SHOPS and not v219.get("eligible") and not v219.get("committed")
    wheat_held = int(private["shed"].get("WHEAT", 0)) + sum(int(i.get("WHEAT", 0)) for i in private["inventories"])
    live = [p for p in st["swapped"] if isinstance(farm["tiles"][p[1]][p[0]], dict) and farm["tiles"][p[1]][p[0]].get("crop") == "TOMATO"]
    if (TMS_FEED_TOPUP and live and wheat_held < TMS_FEED_TOPUP and len(market) < MAX_ORDERS
            and not any(o[:2] == ["BUY_PRODUCT", "WHEAT"] for o in market if len(o) >= 2)):
        qty = min(TMS_FEED_TOPUP - wheat_held, int((float(farm["money"]) - TMS_MIN_CASH) // max(1, int(prices.get("WHEAT", 99)) + 5)))
        if qty > 0:
            market.append(["BUY_PRODUCT", "WHEAT", qty]); changed = True
            _TMS_REPORT["tms_feed"] = _TMS_REPORT.get("tms_feed", 0) + qty
    # 1. dawn seed purchase on swap days
    if (active and day in TMS_DAYS and hour == TMS_BUY_HOUR and day not in st["bought"]
            and int(prices.get("TOMATO", 0)) >= TMS_MIN_PRICE
            and float(farm["money"]) >= TMS_MIN_CASH + 50 * TMS_K and len(market) < MAX_ORDERS
            and wheat_held >= TMS_WHEAT_MIN):
        market.append(["BUY_SEED", "TOMATO", TMS_K])
        st["bought"][day] = TMS_K
        _TMS_REPORT["tms_seed"] += TMS_K
        changed = True
    # 2. swap wheat plantings while tomato seeds last (swap day and the day after)
    left = st["bought"].get(day, 0) + st["bought"].get(day - 1, 0) - sum(
        1 for d in st["swapped"].values() if d in (day, day - 1))
    seeds = int(private["seeds"].get("TOMATO", 0))
    if left > 0 and seeds > 0 and wheat_held >= TMS_WHEAT_MIN:
        for i, c in enumerate(commands):
            if left <= 0 or seeds <= 0 or i >= len(pos):
                break
            if c[:2] == ["PLANT", "WHEAT"]:
                c[1] = "TOMATO"; left -= 1; seeds -= 1
                st["swapped"][pos[i]] = day
                _TMS_REPORT["tms_swaps"] += 1
                changed = True
    # 3. keep the swapped tiles alive and harvested
    for i, c in enumerate(commands):
        if i >= len(pos):
            break
        p = pos[i]
        if p not in st["swapped"]:
            continue
        t = farm["tiles"][p[1]][p[0]]
        if not (isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop") == "TOMATO"):
            continue
        op = c[0] if c else "PASS"
        held = int(t.get("yield_units", 0))
        age = day - int(t.get("planted_day", day))
        watered = bool(t.get("watered_today"))
        noop = (op == "PLANT") or (op == "HARVEST" and held <= 0) or (op == "WATER" and watered)
        if op == "DIG":
            commands[i] = ["PASS"]; changed = True; op = "PASS"
        if op == "PASS" or noop:
            if held >= TMS_HARVEST_AT or (held > 0 and age >= 11):
                commands[i] = ["HARVEST"]; _TMS_REPORT["tms_harvest"] += 1; changed = True
            elif not watered:
                commands[i] = ["WATER"]; _TMS_REPORT["tms_water"] += 1; changed = True
    if not changed:
        return action
    out = dict(action)
    out["farmer"], out["hands"], out["market"] = commands[0], commands[1:], market[:MAX_ORDERS]
    return out
