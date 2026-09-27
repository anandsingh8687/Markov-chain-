

# ==== Frontier V18: deferred third-land recovery ====
# Local Apache-2.0 modification. The frozen V17 policy remains the parent.
# Its selected public routes request the third quadrant on day 8, but a request
# can silently fail when current cash is below the land price. If the opponent
# later demonstrates three-quadrant capacity while we still have only two,
# retry the missed purchase once a conservative cash reserve is available.
import copy as _v18_copy
_V18_PARENT=agent
_V18_START_DAY=9
_V18_END_DAY=14
_V18_RESERVE=3000
_V18_REQUIRE_OPPONENT_THREE=False
_V18_REPORT={'land_retry_requests':0,'eligible_turns':0,'budget_declines':0}

def _v18_fib(n):
    a,b=1,1
    for _ in range(n): a,b=b,a+b
    return a

def _v18_parent_spend(observation, orders):
    farm=observation['farms'][int(observation['player'])]
    prices=observation['market']['prices']
    hires=int(farm.get('hires_today',0)); spend=0
    for order in orders:
        if not order: continue
        op=order[0]
        if op=='HIRE': spend+=_v18_fib(hires);hires+=1
        elif op=='BUY_SEED' and len(order)>=3: spend+=int(order[2])*SEED_PRICE.get(order[1],0)
        elif op=='BUY_ANIMAL' and len(order)>=3: spend+=int(order[2])*ANIMAL_COST.get(order[1],0)
        elif op=='BUY_PRODUCT' and len(order)>=3: spend+=int(order[2])*int(prices.get(order[1],0))
        elif op=='BUY_LAND':
            index=max(0,min(len(LAND_PRICES)-1,len(farm.get('unlocked_quadrants',[]))-1))
            spend+=LAND_PRICES[index]
    return spend

def frontier_v18_agent(observation, configuration=None):
    step=int(observation.get('step',0))
    if step==0:_V18_REPORT.update(land_retry_requests=0,eligible_turns=0,budget_declines=0)
    action=_v18_copy.deepcopy(_V18_PARENT(observation,configuration))
    day=step//24;player=int(observation['player'])
    if not _V18_START_DAY<=day<=_V18_END_DAY:return action
    farms=observation['farms'];mine=farms[player];other=farms[1-player]
    if len(mine.get('unlocked_quadrants',[]))!=2:return action
    if _V18_REQUIRE_OPPONENT_THREE and len(other.get('unlocked_quadrants',[]))<3:return action
    orders=action.setdefault('market',[])
    if len(orders)>=10 or any(o and o[0]=='BUY_LAND' for o in orders):return action
    _V18_REPORT['eligible_turns']+=1
    land_cost=LAND_PRICES[1]
    if float(mine.get('money',0))<_v18_parent_spend(observation,orders)+land_cost+_V18_RESERVE:
        _V18_REPORT['budget_declines']+=1;return action
    orders.append(['BUY_LAND'])
    _V18_REPORT['land_retry_requests']+=1
    return action

agent=frontier_v18_agent
