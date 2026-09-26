
# ==== v14 STX: trade young strawberries near the shed for tomatoes ====
# In a mirror match both sides sell ~250 strawberries and the late strawberry quote
# crashes to $1-50, while nobody in the lineage sells tomatoes.  Tape copies rated
# 2600+ (chocolat, 2621) hire two extra hands on day 14, DIG eight young strawberry
# plants in the cluster next to the shed and PLANT TOMATO there (first fruit at age 8,
# +1 a day for four days).  The tape keeps watering and harvesting "its strawberries"
# on those tiles, so the tomatoes are tended by the tape's own workers; units whose
# tape order on a tomato tile would be a no-op water or harvest it instead.  Hands'
# cargo reaches the shed at midnight and MDX sells it (TOMATO in MDX_ITEMS).
STX_DAY = 14
STX_K = 8
STX_CREW = 2
STX_RADIUS = 5              # Manhattan distance from the nearest shed-access tile
STX_MIN_AGE = 0             # strawberry age (days) range eligible for the trade
STX_MAX_AGE = 5
STX_MIN_SHOPS = 1           # tomato buyers (pizza shops + farmers markets) unlocked
STX_MAX_STRAW_BUYERS = 1    # strawberry buyers unlocked: with 2+ the late quote holds up
_STX_STRAW_SHOPS = ('BRUNCH_SPOT', 'ICE_CREAM_SHOP', 'SMOOTHIE_SHOP', 'FARMERS_MARKET')
STX_MIN_PRICE = 40
STX_MIN_CASH = 3000
STX_LAST_HIRE_HOUR = 12
_STX_ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
_STX_STATE = {}
_STX_REPORT = dict(stx_active=0, stx_hired=0, stx_dug=0, stx_planted=0, stx_steer=0, stx_errors=0)


def _stx_fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _stx_dist(p):
    return min(abs(p[0] - a[0]) + abs(p[1] - a[1]) for a in _STX_ACCESS)


def _stx_walk(pos, target):
    x, y = pos; tx, ty = target
    if x != tx:
        return ['EAST' if x < tx else 'WEST']
    if y != ty:
        return ['SOUTH' if y < ty else 'NORTH']
    return None


def _stx_crew_cmd(farm, pos, targets, seeds_left):
    """Next command for a planting-crew hand: dig, plant, water its targets in turn."""
    todo = []
    for p in targets:
        t = farm['tiles'][p[1]][p[0]]
        if isinstance(t, dict) and t.get('crop') == 'STRAWBERRY':
            todo.append((p, ['DIG']))
        elif t is None or (isinstance(t, dict) and t.get('kind') == 'WEED'):
            if t is not None:
                todo.append((p, ['DIG']))
            elif seeds_left[0] > 0:
                todo.append((p, ['PLANT', 'TOMATO']))
        elif isinstance(t, dict) and t.get('crop') == 'TOMATO' and not t.get('watered_today'):
            todo.append((p, ['WATER']))
    if not todo:
        return ['PASS']
    p, cmd = min(todo, key=lambda v: (abs(pos[0] - v[0][0]) + abs(pos[1] - v[0][1]), v[0]))
    w = _stx_walk(pos, p)
    if w:
        return w
    if cmd[0] == 'PLANT':
        seeds_left[0] -= 1
    return cmd


def _stx_apply(observation, action):
    step = int(observation['step']); day = step // 24; hour = step % 24
    player = int(observation['player'])
    st = _STX_STATE.get(player)
    if st is None or step <= st.get('step', -1):
        st = _STX_STATE[player] = {'step': -1, 'tiles': [], 'crew': {}, 'pending': None, 'hired': False}
    st['step'] = step
    if step >= 718 or day < STX_DAY:
        return action
    farm = observation['farms'][player]; private = observation['private']
    prices = observation['market']['prices']
    commands = [list(action.get('farmer') or ['PASS'])] + [list(c) for c in (action.get('hands') or [])]
    market = [list(o) for o in (action.get('market') or [])]
    pos = [tuple(farm['farmer'])] + [tuple(h) for h in farm['hands']]
    changed = False
    if day == STX_DAY:
        # 1. hire the crew and buy the seeds once the tape's own hires are done
        if not st['hired'] and hour <= STX_LAST_HIRE_HOUR:
            shops = observation['town']['unlocked_shops']
            buyers = sum(s in ('PIZZA_SHOP', 'FARMERS_MARKET') for s in shops)
            v219 = _V219_STATES.get(player, {})
            native = _IMPL.chassis.players.get(player) or {}
            tape = _IMPL.chassis.routes.get(native.get('route'))
            sbuy = sum(s in _STX_STRAW_SHOPS for s in shops)
            ok = (buyers >= STX_MIN_SHOPS and sbuy <= STX_MAX_STRAW_BUYERS and int(prices.get('TOMATO', 0)) >= STX_MIN_PRICE
                  and not v219.get('committed') and tape is not None)
            if ok:
                planned = tape[day * 24:min((day + 1) * 24, len(tape))]
                later = any(o and o[0] == 'HIRE' for a in planned[hour + 1:] for o in (a.get('market') or []))
                parent_hires = sum(1 for o in market if o and o[0] == 'HIRE')
                expected = max((len(a.get('hands') or []) for a in planned), default=0)
                if not later and len(farm['hands']) + parent_hires >= expected:
                    cands = []
                    for y, row in enumerate(farm['tiles']):
                        for x, t in enumerate(row):
                            if (isinstance(t, dict) and t.get('crop') == 'STRAWBERRY'
                                    and STX_MIN_AGE <= day - int(t.get('planted_day', day)) <= STX_MAX_AGE
                                    and _stx_dist((x, y)) <= STX_RADIUS):
                                cands.append((_stx_dist((x, y)), (x, y)))
                    cands.sort()
                    tiles = [p for _, p in cands[:STX_K]]
                    n = len(tiles)
                    cost = sum(_stx_fib(k) for k in range(int(farm['hires_today']) + parent_hires,
                                                         int(farm['hires_today']) + parent_hires + STX_CREW)) + 50 * n
                    if n >= max(2, STX_K // 2) and len(market) + STX_CREW + 1 <= MAX_ORDERS \
                            and float(farm['money']) > cost + STX_MIN_CASH:
                        market += [['BUY_SEED', 'TOMATO', n]] + [['HIRE'] for _ in range(STX_CREW)]
                        st['tiles'] = tiles
                        st['pending'] = {'step': step, 'first': len(farm['hands']) + parent_hires + 1}
                        st['hired'] = True; changed = True
                        _STX_REPORT['stx_active'] += 1
            if not st['hired'] and hour >= STX_LAST_HIRE_HOUR:
                st['hired'] = True       # give up for this game
        pend = st.get('pending')
        if pend and step == pend['step'] + 1:
            first = pend['first']
            if len(farm['hands']) >= first + STX_CREW - 1:
                import math as _m
                tl = sorted(st['tiles'], key=lambda p: _m.atan2(p[1] - 4.5, p[0] - 4.5))
                size = -(-len(tl) // STX_CREW)
                for k in range(STX_CREW):
                    st['crew'][first + k] = tl[k * size:(k + 1) * size]
                _STX_REPORT['stx_hired'] += STX_CREW
            st['pending'] = None
        if st['crew']:
            seeds_left = [int(private['seeds'].get('TOMATO', 0))]
            for actor, targets in st['crew'].items():
                if actor >= len(pos):
                    continue
                while len(commands) <= actor:
                    commands.append(['PASS'])
                cmd = _stx_crew_cmd(farm, pos[actor], targets, seeds_left)
                if cmd == ['DIG']:
                    _STX_REPORT['stx_dug'] += 1
                if cmd[:1] == ['PLANT']:
                    _STX_REPORT['stx_planted'] += 1
                commands[actor] = cmd; changed = True
    # 2. every day: tape units on a tomato tile water it, or harvest what it holds
    tiles = set(st['tiles'])
    crew = st['crew'] if day == STX_DAY else {}
    for i, c in enumerate(commands):
        if i >= len(pos) or i in crew or pos[i] not in tiles:
            continue
        t = farm['tiles'][pos[i][1]][pos[i][0]]
        if not (isinstance(t, dict) and t.get('kind') == 'PLANT' and t.get('crop') == 'TOMATO'):
            continue
        op = c[0] if c else 'PASS'
        held = int(t.get('yield_units', 0)); watered = bool(t.get('watered_today'))
        if op == 'DIG' or op == 'PLANT' or (op == 'HARVEST' and held <= 0) or (op == 'WATER' and watered) \
                or (op == 'FERTILIZE' and held <= 0 and watered):
            new = ['HARVEST'] if held > 0 else (['WATER'] if not watered else ['PASS'])
            if new != c:
                commands[i] = new; changed = True; _STX_REPORT['stx_steer'] += 1
    if not changed:
        return action
    out = dict(action)
    out['farmer'], out['hands'], out['market'] = commands[0], commands[1:], market[:MAX_ORDERS]
    return out
