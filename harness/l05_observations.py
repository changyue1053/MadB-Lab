"""Independent L05 expectations and exact nonce/PID log parsing."""
import json
import re

NATIVE_EXPECTED = {
    'native-two-observers': [1, 1, 11],
    'native-stop-isolation': [1, 2, 33],
    'native-reentry': [2, 3, 44],
    'native-close-completed': [1],
}
UI_EXPECTED = {
    'ui-page-appeared-1': [1],
    'ui-page-hidden': [1],
    'ui-hidden-publish': [1, 2, 9],
    'ui-page-appeared-2': [2],
    'ui-final-close': [2, 1, 3, 7],
}


def parse(raw, *, nonce, pid, complete=False):
    lines = [line for line in raw.splitlines() if nonce in line]
    errors, frames = [], {}
    if not isinstance(pid, str) or not pid.isdigit() or int(pid) <= 0:
        errors.append('probe PID absent or non-unique')
    elif any(len(line.split()) < 3 or line.split()[2] != pid for line in lines):
        errors.append('nonce/PID binding mismatch')
    prefix = 'L05_CASE ' + nonce + ' '
    for line in lines:
        if 'L05_FAILED ' + nonce in line:
            errors.append('target assertion failed')
        if prefix not in line:
            continue
        try:
            label, encoded = line.split(prefix, 1)[1].split(' ', 1)
            value = json.loads(encoded)
            expected = {**NATIVE_EXPECTED, **UI_EXPECTED}
            if label in frames or label not in expected or not isinstance(value, list) or any(type(x) is not int for x in value) or value != expected[label]:
                errors.append('unexpected, duplicate or mismatched observation: ' + label)
            frames[label] = value
        except (ValueError, TypeError):
            errors.append('malformed observation')
    native_count = sum(line.endswith('L05_NATIVE_COMPLETE ' + nonce) for line in lines)
    final_count = sum(line.endswith('L05_COMPLETE ' + nonce) for line in lines)
    if native_count > 1 or final_count > 1:
        errors.append('duplicate completion')
    native_complete = native_count == 1 and all(frames.get(k) == v for k, v in NATIVE_EXPECTED.items())
    if native_count and not native_complete:
        errors.append('native completion missing required observations')
    full_observations = (frames == {**NATIVE_EXPECTED, **UI_EXPECTED}
                         and list(frames) == list(NATIVE_EXPECTED) + list(UI_EXPECTED))
    final_complete = final_count == 1 and native_complete and full_observations
    if complete and not final_complete:
        errors.append('final observation set/order differs')
    return {'errors': errors, 'frames': frames, 'native_complete': native_complete,
            'complete': final_complete and not errors, 'lines': lines, 'pid': pid, 'nonce': nonce}


def nodes(value):
    if isinstance(value, dict):
        attrs = value.get('attributes')
        if isinstance(attrs, dict):
            yield attrs
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def find_node(layout, identity):
    matches = [row for row in nodes(layout) if row.get('id') == identity or row.get('key') == identity]
    if len(matches) != 1:
        raise ValueError('expected exactly one visible UI node: ' + identity)
    return matches[0]


def click_center(node):
    # Bounds are returned by the target UI hierarchy, never guessed coordinates.
    bounds = node.get('bounds', '')
    if not isinstance(bounds, str) or not re.fullmatch(r'\[-?\d+,-?\d+\]\[-?\d+,-?\d+\]', bounds):
        raise ValueError('unrecognized UI bounds')
    left, top, right, bottom = map(int, re.findall(r'-?\d+', bounds))
    if left < 0 or top < 0 or right <= left or bottom <= top:
        raise ValueError('invalid UI bounds')
    return (left + right) // 2, (top + bottom) // 2
