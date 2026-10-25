"""Independent field-lifetime assertions; no GC or per-subscription NAPI claim."""
STATES = {
    'listener-source-open': [1, 0, 0, 1],
    'listener-source-retained': [1, 1, 0, 1],
    'listener-source-released': [1, 1, 1, 0],
    'listener-pending-retained': [1, 0, 0, 1],
    'listener-pending-stopped': [1, 1, 0, 1],
    'listener-pending-released': [1, 1, 1, 0],
    'listener-entry-retained': [1, 0, 0, 1],
    'listener-entry-stopped': [1, 1, 0, 1],
    'listener-entry-released': [1, 1, 1, 0],
    'listener-source-still-released': [1, 1, 1, 0],
    'listener-pending-still-released': [1, 1, 1, 0],
}
SCENARIOS = {'listener-lifetime': {**{key: 'vector' for key in STATES},
    'listener-source-native': 'native', 'listener-pending-native': 'native',
    'listener-entry-native': 'native', 'listener-lifetime-counts': 'vector',
    'listener-lifetime-drained': 'native'}}


def predicates(frames):
    problems = []
    for label, expected in STATES.items():
        if frames.get(label) != expected or any(type(v) is not int for v in frames.get(label, [])):
            problems.append(label + ': actual listener field/close state differs')
    if frames.get('listener-lifetime-counts') != [0, 0, 1]:
        problems.append('stopped preentry callback ran or positive entered callback missing')
    required = {'listener-source-native': {8: 1, 77: 1, 6: 1},
                'listener-pending-native': {6: 1, 9: 0},
                'listener-entry-native': {5: 1, 9: 1},
                'listener-lifetime-drained': {5: 0, 6: 0, 8: 0, 9: 0}}
    for label, expected in required.items():
        value = frames.get(label)
        if (not isinstance(value, list) or len(value) != 178 or value[0] != 1 or
                any(type(v) is not int or v < 0 or v > 2**53 - 1 for v in value)):
            problems.append(label + ': missing/malformed native observation')
        elif any(value[i] != target for i, target in expected.items()):
            problems.append(label + ': independent native phase differs')
    return problems
