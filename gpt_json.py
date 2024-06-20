import json
import html

def simple(s):
    return json.loads(s)

def try1(s):
    fix = s.strip('```json\n').strip('\n```')
    if fix.startswith('json'):
        fix = fix[4:]
    return json.loads(fix)

def try2(s):
    s = html.unescape(s)
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)

def try3(s):
    s = html.unescape(s)
    s = s.replace('\\\n', '')
    s = s.replace('\\', '')
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)

def attempt_to_deserialize_openai_json(response_text, debug_failures=False):
    got=False
    response_json=None
    for attempt in [simple, try1, try2, try3]:
        try:
            response_json = attempt(response_text)
            got=True
            break
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    if debug_failures and not got:
        import ipdb
        ipdb.set_trace()
    return response_json,got

