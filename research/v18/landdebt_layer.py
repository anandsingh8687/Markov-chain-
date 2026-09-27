

# ==== V18 (Claude line): land-debt recovery ====
# A route's BUY_LAND silently no-ops when cash is short (ladder game 114145948: the day-6
# north-east purchase fails at $76, lands on day 8, and the south-west one never comes).
# Remember every quadrant the parent tried to buy; while we own fewer, re-issue BUY_LAND
# on the first turn cash covers the parent's own orders + the land price + a reserve.
# With LD_HOLD, the parent's seed/animal purchases are deferred while land is owed and
# the land is affordable within LD_HOLD dollars.
import copy as _ld_copy
_LD_PARENT = agent
LD_FROM_DAY = 6
LD_TO_DAY = 16
LD_RESERVE = 0
LD_HOLD = 0
_LD_STATE = {}
_LD_REPORT = dict(ld_debt_turns=0, ld_requests=0, ld_holds=0)


def _ld_price(nq):
    return LAND_PRICES[max(0, min(len(LAND_PRICES) - 1, nq - 1))]


def land_debt_agent(observation, configuration=None):
    action = _ld_copy.deepcopy(_LD_PARENT(observation, configuration))
    try:
        step = int(observation.get('step', 0)); day = step // 24
        player = int(observation['player'])
        st = _LD_STATE.get(player)
        if st is None or step <= st['step']:
            st = _LD_STATE[player] = {'step': -1, 'target': 1}
        st['step'] = step
        farm = observation['farms'][player]
        nq = len(farm.get('unlocked_quadrants', []))
        orders = action.setdefault('market', [])
        asked = sum(1 for o in orders if o and o[0] == 'BUY_LAND')
        st['target'] = max(st['target'], nq + asked, nq)
        if not LD_FROM_DAY <= day <= LD_TO_DAY or asked or nq >= st['target'] or nq >= 4:
            return action
        _LD_REPORT['ld_debt_turns'] += 1
        price = _ld_price(nq)
        money = float(farm.get('money', 0))
        spend = _v18_parent_spend(observation, orders)
        if money >= spend + price + LD_RESERVE and len(orders) < 10:
            orders.insert(0, ['BUY_LAND']) if LD_HOLD else orders.append(['BUY_LAND'])
            _LD_REPORT['ld_requests'] += 1
        elif LD_HOLD and money >= price + LD_RESERVE - LD_HOLD:
            keep = [o for o in orders if not (o and o[0] in ('BUY_SEED', 'BUY_ANIMAL'))]
            if len(keep) != len(orders):
                orders[:] = keep; _LD_REPORT['ld_holds'] += 1
            if money >= _v18_parent_spend(observation, orders) + price + LD_RESERVE and len(orders) < 10:
                orders.insert(0, ['BUY_LAND']); _LD_REPORT['ld_requests'] += 1
    except Exception:
        pass
    return action


agent = land_debt_agent
