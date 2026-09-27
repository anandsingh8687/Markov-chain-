

# ==== V18d RANCH: a sheep ranch on the fourth (south-east) quadrant in yarn towns ====
# Losses to sub-2600 opponents are led by wool (-$9.9k a game on average, -$40-55k
# where the rival runs 17 sheep on four quadrants while we run 9 on three).  A yarn
# store is a single-product shop: it drains 2 wool every 4 turns (12 a day).  A sheep
# that is fed and cared for every day yields ~1.33 wool a day (+1 per cared day) and
# one fertilizer.  With 2+ yarn stores and cash for the $4,000 plot, buy SE, build
# pastures next to the shed, buy the flock and run a 2-hand crew hired after the
# parent's own hires.  Crew hands are inserted into the hands list at the index they
# occupy in the engine; later parent hires are shifted behind them.
RANCH_FROM_DAY = 9
RANCH_TO_DAY = 15
RANCH_MIN_YARN = 2
RANCH_MAX_SHEEP = 10
RANCH_CREW = 2
RANCH_RESERVE = 1500
RANCH_HIRE_HOUR = 3
RANCH_LAST_HIRE_HOUR = 10
RANCH_END_DAY = 29
_RANCH_STATE = {}
_RANCH_REPORT = dict(ranch_active=0, ranch_sheep=0, ranch_errors=0)
_RANCH_PARENT = agent


def _ranch_fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _ranch_walk(pos, target):
    x, y = pos; tx, ty = target
    if x != tx:
        return ['EAST' if x < tx else 'WEST']
    if y != ty:
        return ['SOUTH' if y < ty else 'NORTH']
    return None


def _ranch_tiles(n):
    se = [(x, y) for y in range(5, 10) for x in range(5, 10) if (x, y) != (5, 5)]
    se.sort(key=lambda p: (abs(p[0] - 5) + abs(p[1] - 5), p[1], p[0]))
    return se[:n]


def _ranch_cmd(obs, st, actor, targets, day, hour):
    farm = obs['farms'][int(obs['player'])]; private = obs['private']
    units = [farm['farmer']] + list(farm['hands'])
    if actor >= len(units):
        return ['PASS']
    pos = tuple(units[actor])
    invs = private.get('inventories') or []
    inv = invs[actor] if actor < len(invs) else {}
    shed = private.get('shed') or {}
    tiles = farm['tiles']
    home = (5, 5)
    # last day: harvest everything, then drop it in the shed before the end
    if day >= RANCH_END_DAY and hour >= 19:
        cargo = sum(int(v) for k, v in inv.items() if k in ('WOOL', 'FERTILIZER'))
        if cargo:
            w = _ranch_walk(pos, home)
            return w or ['DROP']
        return ['PASS']
    empty_pastures = [p for p in targets if isinstance(tiles[p[1]][p[0]], dict)
                      and tiles[p[1]][p[0]].get('kind') == 'PASTURE' and 'animal' not in tiles[p[1]][p[0]]]
    sheep_tiles = [p for p in targets if isinstance(tiles[p[1]][p[0]], dict) and tiles[p[1]][p[0]].get('animal') == 'SHEEP']
    unfed = sum(1 for p in sheep_tiles if not tiles[p[1]][p[0]].get('fed_today'))
    key = (day, actor)
    # supplies at the shed
    if empty_pastures and int(inv.get('SHEEP', 0)) == 0 and int(shed.get('SHEEP', 0)) > 0 and st['sheep_pick'].get(key, 0) < 3:
        w = _ranch_walk(pos, home)
        if w:
            return w
        st['sheep_pick'][key] = st['sheep_pick'].get(key, 0) + 1
        return ['PICKUP', 'SHEEP', min(len(empty_pastures), int(shed.get('SHEEP', 0)))]
    if unfed > int(inv.get('WHEAT', 0)) and int(shed.get('WHEAT', 0)) > 0 and st['wheat_pick'].get(key, 0) < 8:
        w = _ranch_walk(pos, home)
        if w:
            return w
        st['wheat_pick'][key] = st['wheat_pick'].get(key, 0) + 1
        return ['PICKUP', 'WHEAT', min(unfed - int(inv.get('WHEAT', 0)), int(shed.get('WHEAT', 0)))]
    todo = []
    for p in targets:
        t = tiles[p[1]][p[0]]
        cmd = None
        if t is None:
            cmd = ['BUILD_PASTURE']
        elif isinstance(t, dict) and t.get('kind') == 'WEED':
            cmd = ['DIG']
        elif isinstance(t, dict) and t.get('kind') == 'PASTURE' and 'animal' not in t:
            if int(inv.get('SHEEP', 0)) > 0:
                cmd = ['PLACE', 'SHEEP']
        elif isinstance(t, dict) and t.get('animal') == 'SHEEP':
            y = int(t.get('yield_units', 0))
            if not t.get('fed_today') and int(inv.get('WHEAT', 0)) > 0:
                cmd = ['FEED']
            elif t.get('fed_today') and not t.get('cared_today'):
                cmd = ['CARE']
            elif y >= 4 or (y > 0 and day >= RANCH_END_DAY):
                cmd = ['HARVEST']
            elif t.get('fertilizer_available'):
                cmd = ['COLLECT_FERTILIZER']
        if cmd:
            todo.append((p, cmd))
    if not todo:
        return ['PASS']
    p, cmd = min(todo, key=lambda v: (abs(pos[0] - v[0][0]) + abs(pos[1] - v[0][1]), v[0]))
    return _ranch_walk(pos, p) or cmd


def _ranch_apply(observation, action):
    step = int(observation['step']); day = step // 24; hour = step % 24
    player = int(observation['player'])
    st = _RANCH_STATE.get(player)
    if st is None or step <= st['step']:
        st = _RANCH_STATE[player] = {'step': -1, 'active': False, 'tiles': [], 'bought': 0,
                                     'crew_day': -1, 'crew_at': None, 'pending': None,
                                     'sheep_pick': {}, 'wheat_pick': {}}
    st['step'] = step
    if step >= 718:
        return action
    farm = observation['farms'][player]; private = observation['private']
    market = [list(o) for o in (action.get('market') or [])]
    quads = list(farm.get('unlocked_quadrants', []))
    money = float(farm.get('money', 0))
    changed = False
    if not st['active']:
        if not (RANCH_FROM_DAY <= day <= RANCH_TO_DAY and 2 <= hour <= RANCH_LAST_HIRE_HOUR):
            return action
        shops = list(observation['town']['unlocked_shops'])
        if sum(s == 'YARN_STORE' for s in shops) < RANCH_MIN_YARN or len(quads) != 3:
            return action
        if any(o and o[0] in ('BUY_LAND', 'HIRE') for o in market):
            return action
        spend = _v18_parent_spend(observation, market)
        n = int(min(RANCH_MAX_SHEEP, (money - spend - 4000 - RANCH_RESERVE) // 500))
        if n < 4:
            return action
        st.update(active=True, tiles=_ranch_tiles(n))
        market.insert(0, ['BUY_LAND'])
        _RANCH_REPORT['ranch_active'] += 1
        changed = True
    if 'SE' not in quads and not changed:
        if step > st.get('act_step', step):
            st['active'] = False
        return action
    st.setdefault('act_step', step)
    tiles = farm['tiles']
    targets = st['tiles']
    # flock purchases once pastures stand
    if 'SE' in quads:
        ready = sum(1 for p in targets if isinstance(tiles[p[1]][p[0]], dict)
                    and tiles[p[1]][p[0]].get('kind') == 'PASTURE' and 'animal' not in tiles[p[1]][p[0]])
        inflight = int(private['shed'].get('SHEEP', 0)) + sum(int(i.get('SHEEP', 0)) for i in private['inventories'])
        want = min(ready - inflight, len(targets) - st['bought'])
        spend = _v18_parent_spend(observation, market)
        if want > 0 and day < RANCH_END_DAY - 5:
            want = int(min(want, (money - spend - RANCH_RESERVE) // 500))
            if want > 0 and len(market) < 10 and sum(private['shed'].values()) + want <= 100:
                market.append(['BUY_ANIMAL', 'SHEEP', want]); st['bought'] += want; changed = True
                _RANCH_REPORT['ranch_sheep'] += want
        flock = sum(1 for p in targets if isinstance(tiles[p[1]][p[0]], dict) and tiles[p[1]][p[0]].get('animal') == 'SHEEP')
        unfed = sum(1 for p in targets if isinstance(tiles[p[1]][p[0]], dict) and tiles[p[1]][p[0]].get('animal') == 'SHEEP'
                    and not tiles[p[1]][p[0]].get('fed_today'))
        a0 = st.get('crew_at')
        held = 0
        if a0 is not None:
            invs = private.get('inventories') or []
            held = sum(int((invs[1 + a0 + j] if 1 + a0 + j < len(invs) else {}).get('WHEAT', 0)) for j in range(RANCH_CREW))
        need = max(0, unfed - held) + (2 if hour < 20 else 0) * (1 if unfed else 0)
        shed_wheat = int(private['shed'].get('WHEAT', 0))
        if need and RANCH_HIRE_HOUR <= hour <= 20:
            # the crew's feed is not for sale
            for o in market:
                if len(o) >= 3 and o[0] == 'SELL' and o[1] == 'WHEAT':
                    o[2] = max(0, min(int(o[2]), shed_wheat - need)); changed = True
            market[:] = [o for o in market if not (len(o) >= 3 and o[0] == 'SELL' and o[1] == 'WHEAT' and int(o[2]) <= 0)]
            if shed_wheat < need and len(market) < 10 and \
                    not any(o[:2] == ['BUY_PRODUCT', 'WHEAT'] for o in market if len(o) >= 2):
                market.append(['BUY_PRODUCT', 'WHEAT', need - shed_wheat]); changed = True
    # the daily crew
    commands = [list(action.get('farmer') or ['PASS'])] + [list(c) for c in (action.get('hands') or [])]
    if st['crew_day'] != day:
        st['crew_day'] = day; st['crew_at'] = None; st['pending'] = None
    pend = st['pending']
    if pend and step == pend['step'] + 1:
        if len(farm['hands']) >= pend['a'] + RANCH_CREW:
            st['crew_at'] = pend['a']
        st['pending'] = None
    if st['crew_at'] is None and st['pending'] is None and 'SE' in quads and \
            RANCH_HIRE_HOUR <= hour <= RANCH_LAST_HIRE_HOUR and not any(o and o[0] == 'HIRE' for o in market):
        cost = sum(_ranch_fib(k) for k in range(int(farm['hires_today']), int(farm['hires_today']) + RANCH_CREW))
        if len(market) + RANCH_CREW <= 10 and money > cost + _v18_parent_spend(observation, market) + 300:
            market += [['HIRE'] for _ in range(RANCH_CREW)]
            st['pending'] = {'step': step, 'a': len(farm['hands'])}
            changed = True
    if st['crew_at'] is not None:
        a = st['crew_at']
        parent_hands = commands[1:]
        crew = []
        k = RANCH_CREW
        for j in range(k):
            actor = 1 + a + j
            crew.append(_ranch_cmd(observation, st, actor, targets[j::k], day, hour))
        if len(parent_hands) >= len(farm['hands']):
            hands = parent_hands[:a] + crew + parent_hands[a + k:]
        else:
            hands = parent_hands[:a] + crew + parent_hands[a:]
        commands = [commands[0]] + hands
        changed = True
    if not changed:
        return action
    out = dict(action)
    out['farmer'], out['hands'], out['market'] = commands[0], commands[1:], market[:10]
    return out


def ranch_agent(observation, configuration=None):
    action = _RANCH_PARENT(observation, configuration)
    try:
        return _ranch_apply(observation, action)
    except Exception:
        _RANCH_REPORT['ranch_errors'] += 1
        return action


agent = ranch_agent
