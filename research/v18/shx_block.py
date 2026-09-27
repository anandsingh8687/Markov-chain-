# ==== Frontier V17: observed shop-demand capacity reallocation ====
# Local Apache-2.0 modification.  The frozen V16 route and all prior safety,
# market, repair and terminal layers remain intact.  From day 6 through day 18,
# future livestock capacity is allocated to the single clearly dominant
# observed animal-product demand.  Existing placed animals are never touched.
import copy as _v17_copy

_V17_PARENT = agent
_V17_WEIGHTS = {"GOOSE": 1,
                "COW": 1,
                "SHEEP": 2}
_V17_MIN_SCORE = 2
_V17_MIN_GAP = 1
_V17_START_DAY = 6
_V17_END_DAY = 18
_V17_EXCLUDED_FIRST_SHOPS = frozenset(('YARN_STORE',))
_V17_REPORT = {"changed_market": 0, "changed_unit": 0,
               "target_turns": {"GOOSE": 0, "COW": 0, "SHEEP": 0}}


SHX_MIN_YARN = 2


def _v17_target(observation):
    shops = list((observation.get("town") or {}).get("unlocked_shops") or [])
    if shops and str(shops[0]) in _V17_EXCLUDED_FIRST_SHOPS:
        return None
    return "SHEEP" if sum(s == "YARN_STORE" for s in shops) >= SHX_MIN_YARN else None
    demand = {
        "GOOSE": _V17_WEIGHTS["GOOSE"] * sum(
            shop in {"BAKERY", "BRUNCH_SPOT"} for shop in shops),
        "COW": _V17_WEIGHTS["COW"] * sum(
            shop in {"PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP"}
            for shop in shops),
        # A one-product shop consumes twice per town sale cycle.
        "SHEEP": _V17_WEIGHTS["SHEEP"] * sum(
            shop == "YARN_STORE" for shop in shops),
    }
    ordered = sorted(demand.values(), reverse=True)
    target = max(demand, key=lambda item: (demand[item], item))
    return (target if demand[target] >= _V17_MIN_SCORE
            and demand[target] - ordered[1] >= _V17_MIN_GAP else None)


def _v17_commands(action):
    return [action.get("farmer", ["PASS"]), *action.get("hands", [])]


def _v17_replace(action, observation, target, op):
    commands = _v17_commands(action)
    private = observation.get("private") or {}
    changed = 0
    for index, command in enumerate(commands):
        if not (isinstance(command, list) and len(command) >= 2
                and command[0] == op
                and command[1] in {"GOOSE", "COW", "SHEEP"}
                and command[1] != target):
            continue
        if op == "PICKUP":
            need = int(command[2]) if len(command) >= 3 else 1
            if int((private.get("shed") or {}).get(target, 0)) < need:
                continue
        elif op == "PLACE":
            inventories = private.get("inventories") or []
            inventory = inventories[index] if index < len(inventories) else {}
            if int((inventory or {}).get(target, 0)) < 1:
                continue
        command[1] = target
        changed += 1
    return changed


def frontier_v17_agent(observation, configuration=None):
    step = int(observation.get("step", 0))
    if step == 0:
        _V17_REPORT.update(changed_market=0, changed_unit=0)
        _V17_REPORT["target_turns"] = {"GOOSE": 0, "COW": 0, "SHEEP": 0}
    action = _v17_copy.deepcopy(_V17_PARENT(observation, configuration))
    day = step // 24
    if not _V17_START_DAY <= day <= _V17_END_DAY:
        return action
    target = _v17_target(observation)
    if target is None:
        return action
    _V17_REPORT["target_turns"][target] += 1
    farm = observation["farms"][int(observation["player"])]
    cash = float(farm.get("money", 0)) - _v18_parent_spend(observation, action.get("market", []))
    if len(farm.get("unlocked_quadrants", [])) < 3:
        cash -= LAND_PRICES[max(0, len(farm.get("unlocked_quadrants", [])) - 1)]
    for order in action.get("market", []):
        if (isinstance(order, list) and len(order) >= 3
                and order[0] == "BUY_ANIMAL"
                and order[1] in {"GOOSE", "COW", "SHEEP"}
                and order[1] != target):
            extra = (ANIMAL_COST[target] - ANIMAL_COST[order[1]]) * int(order[2])
            if extra > cash:
                continue
            cash -= extra
            order[1] = target
            _V17_REPORT["changed_market"] += 1
    structure = "BUILD_COOP" if target == "GOOSE" else "BUILD_PASTURE"
    for command in _v17_commands(action):
        if (isinstance(command, list) and command
                and command[0] in {"BUILD_COOP", "BUILD_PASTURE"}
                and command[0] != structure):
            command[0] = structure
            _V17_REPORT["changed_unit"] += 1
    for op in ("PICKUP", "PLACE"):
        _V17_REPORT["changed_unit"] += _v17_replace(
            action, observation, target, op)
    return action


frontier_v17_agent.telemetry = {
    "v15": _V15_REPORT, "v16": _V16_REPORT, "v17": _V17_REPORT}
agent = frontier_v17_agent

agent = frontier_v17_agent
