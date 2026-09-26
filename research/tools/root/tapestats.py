import json, collections, statistics as S
def stats(acts):
    an = collections.Counter(); seeds = collections.Counter(); land = []; firstan = {}; hires = collections.Counter()
    for t, a in enumerate(acts):
        if t == 0 or not a: continue
        step = t - 1; day = step // 24
        for o in a.get('market') or []:
            if not o: continue
            if o[0] == 'BUY_ANIMAL': an[o[1]] += int(o[2]); firstan.setdefault(o[1], day)
            elif o[0] == 'BUY_SEED': seeds[o[1]] += int(o[2])
            elif o[0] == 'BUY_LAND': land.append(day)
            elif o[0] == 'HIRE': hires[day] += 1
    return {'an': an, 'seeds': seeds, 'land': land, 'hires_mean': S.mean([hires.get(d, 0) for d in range(30)]),
            'open0': json.dumps(acts[1].get('market')), 'open1': json.dumps(acts[2].get('market'))}
