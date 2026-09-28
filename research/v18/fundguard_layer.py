

# ==== V19 FUNDGUARD: never let a plan's hires or purchases fail for want of a few dollars ====
# The market is shared, so an opponent's day-0 orders move the prices a fixed route plan was
# tuned on.  V16's opening ends day 0 with ~$3; against Fieldbook/v58 it ends with $0, the
# day-1 HIREs fail, the day runs with no hands and the plan collapses (-$20k to -$77k).
# Each turn, walk the parent's market list in order with a cash ledger.  If a HIRE / BUY_LAND /
# BUY_ANIMAL / BUY_SEED would be unaffordable when it executes, prepend SELLs of shed stock
# (the most valuable first, keeping the wheat the herd eats today) to cover the gap.
FG_KEEP_WHEAT_PER_ANIMAL = 1
FG_MARGIN = 3
FG_RESERVE_FROM_HOUR = 1
FG_SELL_ORDER = ('FERTILIZER', 'MELON', 'STRAWBERRY', 'MILK', 'WOOL', 'TOMATO', 'EGG', 'CARROT', 'WHEAT')
_FG_REPORT = dict(fg_turns=0, fg_units=0, fg_errors=0)
_FG_PARENT = agent


def _fg_fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _fg_apply(observation, action):
    farm = observation['farms'][int(observation['player'])]
    private = observation.get('private') or {}
    prices = observation['market']['prices']
    market = [list(o) for o in (action.get('market') or []) if o]
    if not market:
        return action
    money = float(farm.get('money', 0))
    hires = int(farm.get('hires_today', 0))
    nq = len(farm.get('unlocked_quadrants', []))
    shed = dict(private.get('shed') or {})
    # cash already arriving from the parent's own SELLs placed before each order
    deficit = 0.0
    cash = money
    for o in market:
        op = o[0]
        if op == 'SELL' and len(o) >= 3:
            cash += int(o[2]) * int(prices.get(o[1], 0)) * 0.9
            shed[o[1]] = shed.get(o[1], 0) - int(o[2])
            continue
        if op == 'HIRE':
            cost = _fg_fib(hires); hires += 1
        elif op == 'BUY_LAND':
            cost = LAND_PRICES[max(0, min(len(LAND_PRICES) - 1, nq - 1))]; nq += 1
        elif op == 'BUY_ANIMAL' and len(o) >= 3:
            cost = int(o[2]) * ANIMAL_COST.get(o[1], 0)
        elif op == 'BUY_SEED' and len(o) >= 3:
            cost = int(o[2]) * SEED_PRICE.get(o[1], 0)
        elif op == 'BUY_PRODUCT' and len(o) >= 3:
            cost = int(o[2]) * int(prices.get(o[1], 0))
        else:
            continue
        if cost > cash:
            deficit = max(deficit, cost - cash)
        cash -= cost
    # keep tomorrow's hiring money: drop discretionary buys that would spend it
    hour = int(observation.get('step', 0)) % 24
    k = max(int(farm.get('hires_today', 0)), 3)
    reserve = sum(_fg_fib(i) for i in range(k)) + FG_MARGIN
    cash = money; kept = []; dropped = 0
    for o in market:
        op = o[0]
        if op == 'SELL' and len(o) >= 3:
            cash += int(o[2]) * int(prices.get(o[1], 0)) * 0.9; kept.append(o); continue
        cost = 0
        if op == 'BUY_SEED' and len(o) >= 3:
            cost = int(o[2]) * SEED_PRICE.get(o[1], 0)
        elif op == 'BUY_PRODUCT' and len(o) >= 3 and o[1] != 'WHEAT':
            cost = int(o[2]) * int(prices.get(o[1], 0))
        if cost and hour >= FG_RESERVE_FROM_HOUR and cash - cost < reserve:
            dropped += 1; continue
        cash -= cost if cost else 0
        kept.append(o)
    if dropped:
        _FG_REPORT['fg_dropped'] = _FG_REPORT.get('fg_dropped', 0) + dropped
        action = dict(action); action['market'] = kept; market = kept
    if deficit <= 0:
        return action
    herd = sum(1 for row in farm['tiles'] for t in row if isinstance(t, dict) and t.get('animal'))
    sells = []
    need = deficit + 2
    for item in FG_SELL_ORDER:
        if need <= 0:
            break
        have = int(shed.get(item, 0))
        if item == 'WHEAT':
            have -= herd * FG_KEEP_WHEAT_PER_ANIMAL
        p = int(prices.get(item, 0))
        if have <= 0 or p <= 1:
            continue
        n = min(have, int(need // max(1, p * 0.85)) + 1)
        sells.append(['SELL', item, n]); need -= n * p * 0.85
        _FG_REPORT['fg_units'] += n
    if not sells:
        return action
    _FG_REPORT['fg_turns'] += 1
    out = dict(action)
    out['market'] = (sells + market)[:10]
    return out


def fundguard_agent(observation, configuration=None):
    action = _FG_PARENT(observation, configuration)
    try:
        return _fg_apply(observation, action)
    except Exception:
        _FG_REPORT['fg_errors'] += 1
        return action


agent = fundguard_agent
