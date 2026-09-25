

# ==== v12 TOMATO SWAP: tomatoes on the tape's own land in two-tomato-shop towns ====
# In towns with exactly two tomato buyers (pizza shops / farmers markets) by day 18,
# nobody in our lineage grows tomatoes and the unmet demand pushes the price to
# $120-230 by days 26-29.  The V219 annex only fires at three buyers (it buys the SE
# plot), so here the tape's own day-18 wheat replants near the shed become tomato
# plantings instead.  The tape keeps watering "its wheat" on those tiles; any tape
# unit that stands on one is steered to water or harvest it.  From day 25 a small
# crew, hired after the tape's own hires, waters, fertilizes (days 25 and 28, so each
# production event yields 2) and harvests (days 27 and 29, before the 4-unit cap
# would overflow), and brings the crop to the shed, where it is sold.
TS_DAYS = (18,)              # swap window: d18 plants produce d25-28 and never rot before the end
TS_SHOPS = 2                 # tomato buyers required by day TS_DAY (exactly; 3+ is V219's)
TS_MAX_PLANTS = 16
TS_RADIUS = 9                # only swap replants within this Manhattan distance of the shed
TS_MIN_PRICE = 70
TS_TILES_PER_HAND = 6
TS_MAX_HANDS = 3
TS_LAST_HIRE_HOUR = 14
TS_FERT_SPARE = 6
_TS_ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
_TS_STATES = {}
_TS_REPORT = dict(ts_active=0, ts_swaps=0, ts_seed_units=0, ts_steer=0, ts_crew_hired=0,
                  ts_crew_shortfall=0, ts_harvest_units=0, ts_sell_units=0, ts_errors=0)


def _ts_fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _ts_dist_shed(p):
    return min(abs(p[0] - a[0]) + abs(p[1] - a[1]) for a in _TS_ACCESS)


def _ts_walk(pos, target):
    x, y = pos; tx, ty = target
    if x != tx:
        return ['EAST' if x < tx else 'WEST']
    if y != ty:
        return ['SOUTH' if y < ty else 'NORTH']
    return None


def _ts_home(pos):
    return min(_TS_ACCESS, key=lambda a: abs(pos[0] - a[0]) + abs(pos[1] - a[1]))


def _ts_positions(farm):
    return [tuple(farm['farmer'])] + [tuple(h) for h in farm['hands']]


def _ts_tile(farm, p):
    t = farm['tiles'][p[1]][p[0]]
    return t if isinstance(t, dict) and t.get('crop') == 'TOMATO' else None


def _ts_qualifies(obs, player):
    shops = obs['town']['unlocked_shops']
    n = sum(s in ('PIZZA_SHOP', 'FARMERS_MARKET') for s in shops)
    if n != TS_SHOPS:
        return False
    if int(obs['market']['prices'].get('TOMATO', 0)) < TS_MIN_PRICE:
        return False
    v219 = _V219_STATES.get(player, {})
    if v219.get('eligible') or v219.get('committed'):
        return False
    return True


def _ts_age(t, day):
    return day - int(t.get('planted_day', day))


def _ts_needs_fert(t, day):
    a = _ts_age(t, day)
    return 7 <= a <= 10 and int(t.get('fertilized_until_day', -1)) < day


def _ts_work(t, day, fert, hour=0):
    """The crew's next job on one tomato tile, or None: harvest first (the 4-unit cap
    wastes fertilized output), then fertilize, and water only late in the day when the
    tape has not (the fertilizer bonus needs a watered production day)."""
    a = _ts_age(t, day)
    y = int(t.get('yield_units', 0))
    if y >= 3 or (y > 0 and (a >= 11 or day >= 29)):
        return ['HARVEST']
    if fert > 0 and _ts_needs_fert(t, day):
        return ['FERTILIZE']
    if day <= 28 and not t.get('watered_today') and (
            int(t.get('consecutive_unwatered', 0)) >= 1 or (7 <= a <= 10 and hour >= 15)):
        return ['WATER']
    return None


def _ts_crew_command(obs, st, actor, role, farm):
    step = int(obs['step']); day = step // 24
    pos = tuple(_ts_positions(farm)[actor])
    inv = obs['private']['inventories'][actor] if actor < len(obs['private']['inventories']) else {}
    home = _ts_home(pos)
    dist_home = abs(pos[0] - home[0]) + abs(pos[1] - home[1])
    carried = int(inv.get('TOMATO', 0))
    # Hands are wiped at midnight: be back at the shed with the cargo in time.
    if carried and step % 24 >= (19 if day == 29 else 22) - dist_home:
        return _ts_walk(pos, home) or ['PLACE', 'TOMATO', carried]
    need = sum(1 for p in role['targets'] if _ts_tile(farm, p) is not None and _ts_needs_fert(_ts_tile(farm, p), day))
    if need and not role.get('loaded'):
        if int(inv.get('FERTILIZER', 0)) >= need or role.get('asked'):
            role['loaded'] = True
        else:
            w = _ts_walk(pos, home)
            if w:
                return w
            role['asked'] = True
            return ['PICKUP', 'FERTILIZER', need - int(inv.get('FERTILIZER', 0))]
    todo = []
    for p in role['targets']:
        t = _ts_tile(farm, p)
        if t is None:
            continue
        cmd = _ts_work(t, day, int(inv.get('FERTILIZER', 0)), step % 24)
        if cmd:
            todo.append((p, cmd))
    if todo:
        p, cmd = min(todo, key=lambda v: (abs(pos[0] - v[0][0]) + abs(pos[1] - v[0][1]), v[0]))
        w = _ts_walk(pos, p)
        if w:
            return w
        if cmd == ['HARVEST']:
            _TS_REPORT['ts_harvest_units'] += int(_ts_tile(farm, p).get('yield_units', 0))
        return cmd
    if carried:
        return _ts_walk(pos, home) or ['PLACE', 'TOMATO', carried]
    if any(int(v) > 0 for v in inv.values()):
        return _ts_walk(pos, home) or ['DROP']
    return ['PASS']


def _ts_apply(obs, action, st):
    step = int(obs['step']); day = step // 24; hour = step % 24
    player = int(obs['player']); farm = obs['farms'][player]
    if st.get('active') is None:
        if day < TS_DAYS[0] - 1:
            return action
        if day == TS_DAYS[0] - 1 and hour == 23 or day >= TS_DAYS[0]:
            st['active'] = _ts_qualifies(obs, player)
            if st['active']:
                _TS_REPORT['ts_active'] += 1
        else:
            return action
    if not st['active']:
        return action
    if _V219_STATES.get(player, {}).get('eligible') or _V219_STATES.get(player, {}).get('committed'):
        st['active'] = False
        return action
    commands = [list(action.get('farmer') or ['PASS'])] + [list(c) for c in (action.get('hands') or [])]
    market = [list(o) for o in (action.get('market') or [])]
    positions = _ts_positions(farm)
    changed = False
    seeds = int(obs['private']['seeds'].get('TOMATO', 0))
    # Seeds for the swap, bought two at a time (market orders settle after unit actions).
    if day in TS_DAYS and len(st['tiles']) < TS_MAX_PLANTS and seeds < 2 and len(market) < MAX_ORDERS \
            and not (day == TS_DAYS[-1] and hour >= 22) and float(farm['money']) > 1500:
        market.append(['BUY_SEED', 'TOMATO', 2]); _TS_REPORT['ts_seed_units'] += 2
        changed = True
    # The swap: the tape's own wheat/carrot replants near the shed become tomatoes.
    if day in TS_DAYS and seeds > 0:
        for i, c in enumerate(commands[:len(positions)]):
            if len(st['tiles']) >= TS_MAX_PLANTS or seeds <= 0:
                break
            if c[:2] in (['PLANT', 'WHEAT'], ['PLANT', 'CARROT']) and _ts_dist_shed(positions[i]) <= TS_RADIUS:
                p = positions[i]
                if farm['tiles'][p[1]][p[0]] is None:
                    c[1] = 'TOMATO'; seeds -= 1; st['tiles'].append(p)
                    _TS_REPORT['ts_swaps'] += 1; changed = True
    # Steer tape units standing on a tomato tile: water it, or harvest it late.
    crew = st['crew'] if st.get('crew_day') == day else {}
    tiles = set(st['tiles'])
    for i, c in enumerate(commands[:len(positions)]):
        if i in crew or positions[i] not in tiles or not c or c[0] not in ('PLANT', 'DIG', 'HARVEST', 'WATER', 'FERTILIZE'):
            continue
        t = _ts_tile(farm, positions[i])
        if t is None:
            continue
        if day <= 28 and not t.get('watered_today'):
            new = ['WATER']
        elif c[0] in ('WATER', 'FERTILIZE'):
            continue
        else:
            new = ['WATER']
        if new != c:
            commands[i] = new; _TS_REPORT['ts_steer'] += 1; changed = True
    # Crew, days 25-29: hired once the tape's own hires for the day are done.
    if day >= 24 and st['tiles'] and any(_ts_tile(farm, p) is not None and (7 <= _ts_age(_ts_tile(farm, p), day) <= 11 or (day >= 29 and int(_ts_tile(farm, p).get('yield_units', 0)) > 0)) for p in st['tiles']):
        if st.get('crew_day') != day:
            st['crew_day'] = day; st['crew'] = {}; st['pending'] = None; st['hired_day'] = False
        pend = st.get('pending')
        if pend and step == pend['step'] + 1:
            if len(farm['hands']) + 1 >= pend['first'] + pend['count']:
                live = [p for p in st['tiles'] if _ts_tile(farm, p) is not None]
                # contiguous areas, walking order around the shed (angle), so each hand stays local
                import math as _m
                live.sort(key=lambda p: _m.atan2(p[1] - 4.5, p[0] - 4.5))
                n = pend['count']; size = -(-len(live) // n)
                chunks = [live[k * size:(k + 1) * size] for k in range(n)]
                for k in range(pend['count']):
                    st['crew'][pend['first'] + k] = {'targets': chunks[k]}
                _TS_REPORT['ts_crew_hired'] += pend['count']
            else:
                _TS_REPORT['ts_crew_shortfall'] += pend['count']
            st['pending'] = None
        if not st['hired_day'] and hour <= TS_LAST_HIRE_HOUR:
            native = _IMPL.chassis.players.get(player) or {}
            tape = _IMPL.chassis.routes.get(native.get('route'))
            live = [p for p in st['tiles'] if _ts_tile(farm, p) is not None]
            if tape and live:
                planned = tape[day * 24:min((day + 1) * 24, len(tape))]
                off = hour
                later = any(o and o[0] == 'HIRE' for a in planned[off + 1:] for o in (a.get('market') or []))
                parent_hires = sum(1 for o in market if o and o[0] == 'HIRE')
                expected = max((len(a.get('hands') or []) for a in planned), default=0)
                if not later and len(farm['hands']) + parent_hires >= expected:
                    count = min(TS_MAX_HANDS, max(1, -(-len(live) // TS_TILES_PER_HAND)))
                    extra = [['HIRE'] for _ in range(count)]
                    nf = sum(1 for p in live if _ts_needs_fert(_ts_tile(farm, p), day))
                    have = 0          # the tape's own fertilizer layer empties the shed each morning
                    if nf > have:
                        extra.insert(0, ['BUY_PRODUCT', 'FERTILIZER', nf + TS_FERT_SPARE])
                    cost = sum(_ts_fib(n) for n in range(int(farm['hires_today']) + parent_hires, int(farm['hires_today']) + parent_hires + count))
                    cost += (nf + TS_FERT_SPARE if nf else 0) * (int(obs['market']['prices'].get('FERTILIZER', 0)) + 5)
                    if len(market) + len(extra) <= MAX_ORDERS and float(farm['money']) > cost + 3000:
                        market += extra
                        st['pending'] = {'step': step, 'first': len(farm['hands']) + parent_hires + 1, 'count': count}
                        st['hired_day'] = True; changed = True
        for actor, role in list(st['crew'].items()):
            while len(commands) <= actor:
                commands.append(['PASS'])
            commands[actor] = _ts_crew_command(obs, st, actor, role, farm); changed = True
    # Sell the crop as it reaches the shed.
    if day >= 25 and not any(o[:2] == ['SELL', 'TOMATO'] for o in market if len(o) >= 2) and len(market) < MAX_ORDERS:
        res = dict(action); res['farmer'], res['hands'], res['market'] = commands[0], commands[1:], market
        q = int(projected_shed(res, FarmView(obs)).get('TOMATO', 0))
        if q > 0 and int(obs['market']['prices'].get('TOMATO', 0)) >= 2:
            market.append(['SELL', 'TOMATO', q]); _TS_REPORT['ts_sell_units'] += q; changed = True
    if not changed:
        return action
    out = dict(action)
    out['farmer'], out['hands'], out['market'] = commands[0], commands[1:], market[:MAX_ORDERS]
    return out


def _ts_guard(observation, action):
    player, step = int(observation['player']), int(observation['step'])
    st = _TS_STATES.get(player)
    if st is None or step <= st['step']:
        st = _TS_STATES[player] = {'step': -1, 'active': None, 'tiles': []}
        if step == 0:
            for k in _TS_REPORT:
                _TS_REPORT[k] = 0
    st['step'] = step
    return _ts_apply(observation, action, st)
