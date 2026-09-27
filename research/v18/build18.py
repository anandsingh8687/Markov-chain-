"""build18.py BASE OUT [rdx] [stx] [mdx]: splice our proven layers onto a frontier base (v16/v17)."""
import sys
base, out, parts = sys.argv[1], sys.argv[2], sys.argv[3:]
src = open(base).read()
R = '/home/user/Markov-chain-/research'
lay = ''
if 'rdx' in parts: lay += open(f'{R}/v12/rdx_layer.py').read() + '\n\n'
if 'stx' in parts: lay += open(f'{R}/v14/stx_layer.py').read() + '\n\n'
if 'mdx' in parts:
    m = open(f'{R}/v13/mdx_layer.py').read()
    m = m.replace('MDX_ITEMS = ("STRAWBERRY",)', 'MDX_ITEMS = ("STRAWBERRY", "MILK", "WOOL"%s)' % (', "TOMATO"' if 'stx' in parts else ''))
    m = m.replace('MDX_FROM_DAY = 22', 'MDX_FROM_DAY = 18').replace('MDX_HOURS = (5,)', 'MDX_HOURS = (5, 17)')
    lay += m + '\n\n'
if 'stx' in parts:
    a = "    if obs['private']['seeds'].get('TOMATO',0) or obs['private']['shed'].get('TOMATO',0):"
    b = "    if any(isinstance(t,dict) and t.get('crop')=='TOMATO' for row in farm['tiles'] for t in row):"
    assert src.count(a) == 1 and src.count(b) == 1
    src = src.replace(a, a.replace("    if obs", "    if not _STX_STATE.get(obs['player'], {}).get('tiles') and (obs").replace("0):", "0)):"))
    src = src.replace(b, b.replace("    if any(", "    if not _STX_STATE.get(obs['player'], {}).get('tiles') and any("))
    # _v219_qualifies runs before the layer definitions are reached at import? it's called at runtime -> fine
entry = '''

# ==== v18: our proven layers spliced onto the frontier base ====
_V18_INNER = [v for k, v in list(globals().items()) if k == 'agent'][0]


def v18_agent(observation, configuration=None):
    action = _V18_INNER(observation, configuration)
'''
if 'rdx' in parts:
    entry += '''    try:
        action = _rdx_apply(observation, action)
    except Exception:
        _RDX_REPORT['rdx_errors'] += 1
'''
if 'stx' in parts:
    entry += '''    try:
        action = _stx_apply(observation, action)
    except Exception:
        _STX_REPORT['stx_errors'] += 1
'''
if 'mdx' in parts:
    entry += '''    try:
        action = _mdx_apply(observation, action)
    except Exception:
        _MDX_REPORT['mdx_errors'] += 1
'''
entry += '''    return action


agent = v18_agent
'''
open(out, 'w').write(src + '\n\n' + lay + entry)
