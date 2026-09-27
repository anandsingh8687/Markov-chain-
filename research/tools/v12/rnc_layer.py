
# ==== v17 RNC: a sheep ranch on the SE plot in multi-yarn-store towns ====
# Each yarn store drains 12 wool a day (single-product shop), the town centre 1.  With
# two or more yarn stores the wool quote stays at $150-240 all game in v14's ladder
# games, while the tape's six-sheep flock and a mirror rival cannot fill it.  A fed
# and cared-for sheep makes 4 wool every 3 days (1 + one care bonus a day) plus one
# fertilizer a day, the most value per worker action in the game.  The tape never
# buys the SE plot, so: on RNC_DAY, once the tape owns SW, buy SE, build pastures on
# the tiles nearest the shed, buy the flock, and run a small crew that feeds, cares,
# collects and shears it every day.  Wool and fertilizer go back to the shed; MDX
# sells wool at its 5am/5pm peaks.
RNC_DAY = 11
RNC_MIN_YARN = 2
RNC_MAX_SHEEP = 10
RNC_PER_HAND = 4
RNC_RESERVE = 3000
RNC_LAST_HIRE_HOUR = 12
RNC_FERT_KEEP = 40          # sell collected fertilizer above this shed stock
_RNC_ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
_RNC_STATE = {}
_RNC_REPORT = dict(rnc_active=0, rnc_pastures=0, rnc_sheep=0, rnc_feed=0, rnc_care=0,
                   rnc_shear=0, rnc_fert=0, rnc_hired=0, rnc_errors=0)


def _rnc_fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _rnc_walk(pos, target):
    x, y = pos; tx, ty = target
    if x != tx:
        return ['EAST' if x < tx else 'WEST']
    if y != ty:
        return ['SOUTH' if y < ty else 'NORTH']
    return None


def _rnc_home(pos):
    return min(_RNC_ACCESS, key=lambda a: abs(pos[0] - a[0]) + abs(pos[1] - a[1]))


def _rnc_tiles(n):
    se = [(x, y) for y in range(5, 10) for x in range(5, 10)]
    se.sort(key=lambda p: (min(abs(p[0] - a[0]) + abs(p[1] - a[1]) for a in _RNC_ACCESS), p[1], p[0]))
    return se[:n]


def _rnc_cmd(obs, st, actor, targets):
    """One crew hand: stock up on wheat, then feed/care/collect/shear its pastures."""
    step = int(obs['step']); day = step // 24; hour = step % 24
    farm = obs['farms'][int(obs['player'])]; private = obs['private']
    pos = tuple(([farm['farmer']] + list(farm['hands']))[actor])
    inv = private['inventories'][actor] if actor < len(private['inventories']) else {}
    home = _rnc_home(pos); dist_home = abs(pos[0] - home[0]) + abs(pos[1] - home[1])
    cargo = {k: int(v) for k, v in inv.items() if k in ('WOOL', 'FERTILIZER') and int(v) > 0}
    # be back at the shed with the cargo before midnight
    if cargo and hour >= 22 - dist_home:
        w = _rnc_walk(pos, home)
        if w:
            return w
        k, v = next(iter(cargo.items()))
        return ['PLACE', k, v]
    tiles = farm['tiles']
    pending_sheep = int(private['shed'].get('SHEEP', 0)) + int(inv.get('SHEEP', 0))
    need_wheat = sum(1 for p in targets if isinstance(tiles[p[1]][p[0]], dict)
                     and tiles[p[1]][p[0]].get('animal') == 'SHEEP' and not tiles[p[1]][p[0]].get('fed_today'))
    # 1. carry sheep bought for empty pastures
    empty_pastures = [p for p in targets if isinstance(tiles[p[1]][p[0]], dict)
                      and tiles[p[1]][p[0]].get('kind') == 'PASTURE' and 'animal' not in tiles[p[1]][p[0]]]
    if empty_pastures and int(inv.get('SHEEP', 0)) == 0 and int(private['shed'].get('SHEEP', 0)) > 0 \
            and not st.get('picked_sheep_' + str(step)):
        w = _rnc_walk(pos, home)
        if w:
            return w
        st['picked_sheep_' + str(step)] = True
        return ['PICKUP', 'SHEEP', min(len(empty_pastures), int(private['shed'].get('SHEEP', 0)), 2)]
    # 2. wheat for today's feeding
    if need_wheat and int(inv.get('WHEAT', 0)) == 0:
        if int(private['shed'].get('WHEAT', 0)) > 0 and not st.get('picked_wheat_' + str(step)):
            w = _rnc_walk(pos, home)
            if w:
                return w
            st['picked_wheat_' + str(step)] = True
            return ['PICKUP', 'WHEAT', min(need_wheat, int(private['shed'].get('WHEAT', 0)))]
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
            if not t.get('fed_today') and int(inv.get('WHEAT', 0)) > 0:
                cmd = ['FEED']
            elif t.get('fed_today') and not t.get('cared_today'):
                cmd = ['CARE']
            elif int(t.get('yield_units', 0)) >= 3 or (int(t.get('yield_units', 0)) > 0 and day >= 28):
                cmd = ['HARVEST']
            elif t.get('fertilizer_available'):
                cmd = ['COLLECT_FERTILIZER']
        if cmd:
            todo.append((p, cmd))
    if todo:
        p, cmd = min(todo, key=lambda v: (abs(pos[0] - v[0][0]) + abs(pos[1] - v[0][1]), v[0]))
        w = _rnc_walk(pos, p)
        if w:
            return w
        k = {'BUILD_PASTURE': 'rnc_pastures', 'FEED': 'rnc_feed', 'CARE': 'rnc_care',
             'HARVEST': 'rnc_shear', 'COLLECT_FERTILIZER': 'rnc_fert'}.get(cmd[0])
        if k:
            _RNC_REPORT[k] += 1
        if cmd[0] == 'PLACE':
            _RNC_REPORT['rnc_sheep'] += 1
        return cmd
    if cargo:
        w = _rnc_walk(pos, home)
        if w:
            return w
        k, v = next(iter(cargo.items()))
        return ['PLACE', k, v]
    return ['PASS']


def _rnc_apply(observation, action):
    step = int(observation['step']); day = step // 24; hour = step % 24
    player = int(observation['player'])
    st = _RNC_STATE.get(player)
    if st is None or step <= st.get('step', -1):
        st = _RNC_STATE[player] = {'step': -1, 'active': False, 'crew': {}, 'crew_day': -1,
                                   'pending': None, 'hired_day': -1, 'tiles': [], 'n': 0, 'bought': 0}
    st['step'] = step
    if step >= 718 or day < RNC_DAY:
        return action
    farm = observation['farms'][player]; private = observation['private']
    prices = observation['market']['prices']
    commands = [list(action.get('farmer') or ['PASS'])] + [list(c) for c in (action.get('hands') or [])]
    market = [list(o) for o in (action.get('market') or [])]
    changed = False
    native = _IMPL.chassis.players.get(player) or {}
    tape = _IMPL.chassis.routes.get(native.get('route'))
    quads = set(farm['unlocked_quadrants'])
    # decision on RNC_DAY
    if not st['active'] and day == RNC_DAY and hour <= RNC_LAST_HIRE_HOUR and 'SE' not in quads and 'SW' in quads:
        shops = observation['town']['unlocked_shops']
        yarn = sum(s == 'YARN_STORE' for s in shops)
        v219 = _V219_STATES.get(player, {})
        if yarn >= RNC_MIN_YARN and not v219.get('committed') and tape is not None:
            n = min(RNC_MAX_SHEEP, int((float(farm['money']) - 4000 - RNC_RESERVE) // 600))
            if n >= 3:
                st.update(active=True, n=n, tiles=_rnc_tiles(n))
                market.append(['BUY_LAND']); changed = True
                _RNC_REPORT['rnc_active'] += 1
    if not st['active']:
        return action if not changed else dict(action, market=market)
    if 'SE' not in quads and day > RNC_DAY:
        st['active'] = False
        return action
    tiles = farm['tiles']
    # buy the flock once pastures stand
    ready = sum(1 for p in st['tiles'] if isinstance(tiles[p[1]][p[0]], dict) and tiles[p[1]][p[0]].get('kind') == 'PASTURE'
                and 'animal' not in tiles[p[1]][p[0]])
    inflight = int(private['shed'].get('SHEEP', 0)) + sum(int(i.get('SHEEP', 0)) for i in private['inventories'])
    want = min(ready - inflight, st['n'] - st['bought'])
    if want > 0 and len(market) < MAX_ORDERS and float(farm['money']) > 500 * want + RNC_RESERVE \
            and sum(private['shed'].values()) + want <= 100:
        market.append(['BUY_ANIMAL', 'SHEEP', want]); st['bought'] += want; changed = True
    # feed: keep enough wheat in the shed for the flock
    flock = sum(1 for p in st['tiles'] if isinstance(tiles[p[1]][p[0]], dict) and tiles[p[1]][p[0]].get('animal') == 'SHEEP')
    if flock and hour == 1 and int(private['shed'].get('WHEAT', 0)) < flock + 20 and len(market) < MAX_ORDERS \
            and not any(o[:2] == ['BUY_PRODUCT', 'WHEAT'] for o in market if len(o) >= 2):
        market.append(['BUY_PRODUCT', 'WHEAT', flock + 20 - int(private['shed'].get('WHEAT', 0))]); changed = True
    # surplus fertilizer
    if hour == 20 and int(private['shed'].get('FERTILIZER', 0)) > RNC_FERT_KEEP and len(market) < MAX_ORDERS \
            and not any(o[:2] == ['SELL', 'FERTILIZER'] for o in market if len(o) >= 2):
        market.append(['SELL', 'FERTILIZER', int(private['shed']['FERTILIZER']) - RNC_FERT_KEEP]); changed = True
    # daily crew
    if st['crew_day'] != day:
        st['crew_day'] = day; st['crew'] = {}; st['pending'] = None
    pend = st.get('pending')
    if pend and step == pend['step'] + 1:
        if len(farm['hands']) + 1 >= pend['first'] + pend['count']:
            for k in range(pend['count']):
                st['crew'][pend['first'] + k] = st['tiles'][k::pend['count']]
            _RNC_REPORT['rnc_hired'] += pend['count']
        st['pending'] = None
    if not st['crew'] and not st.get('pending') and st['hired_day'] != day and hour <= RNC_LAST_HIRE_HOUR and tape:
        planned = tape[day * 24:min((day + 1) * 24, len(tape))]
        later = any(o and o[0] == 'HIRE' for a in planned[hour + 1:] for o in (a.get('market') or []))
        parent_hires = sum(1 for o in market if o and o[0] == 'HIRE')
        expected = max((len(a.get('hands') or []) for a in planned), default=0)
        if not later and len(farm['hands']) + parent_hires >= expected:
            count = max(1, -(-st['n'] // RNC_PER_HAND))
            cost = sum(_rnc_fib(k) for k in range(int(farm['hires_today']) + parent_hires,
                                                   int(farm['hires_today']) + parent_hires + count))
            if len(market) + count <= MAX_ORDERS and float(farm['money']) > cost + 1000:
                market += [['HIRE'] for _ in range(count)]
                st['pending'] = {'step': step, 'first': len(farm['hands']) + parent_hires + 1, 'count': count}
                st['hired_day'] = day; changed = True
    for actor, targets in st['crew'].items():
        while len(commands) <= actor:
            commands.append(['PASS'])
        commands[actor] = _rnc_cmd(observation, st, actor, targets); changed = True
    if not changed:
        return action
    out = dict(action)
    out['farmer'], out['hands'], out['market'] = commands[0], commands[1:], market[:MAX_ORDERS]
    return out
