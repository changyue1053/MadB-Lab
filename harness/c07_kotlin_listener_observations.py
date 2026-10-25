"""Independent field-lifetime assertions; no GC or per-subscription NAPI claim."""
STATES = {
    'kn-listener-source-open': [1, 0, 0, 1],
    'kn-listener-source-retained': [1, 1, 0, 1],
    'kn-listener-source-released': [1, 1, 1, 0],
    'kn-listener-pending-retained': [1, 0, 0, 1],
    'kn-listener-pending-stopped': [1, 1, 0, 1],
    'kn-listener-pending-released': [1, 1, 1, 0],
    'kn-listener-entry-retained': [1, 0, 0, 1],
    'kn-listener-entry-stopped': [1, 1, 0, 1],
    'kn-listener-entry-released': [1, 1, 1, 0],
    'kn-listener-source-still-released': [1, 1, 1, 0],
    'kn-listener-pending-still-released': [1, 1, 1, 0],
}
SCENARIOS = {'kotlin-listener-lifetime': {**{key: 'vector' for key in STATES},
    'kn-listener-source-native': 'native', 'kn-listener-pending-native': 'native',
    'kn-listener-entry-native': 'native', 'kn-listener-lifetime-counts': 'vector',
    'kn-listener-lifetime-drained': 'native'}}


def predicates(frames):
    problems = []
    for label, expected in STATES.items():
        if frames.get(label) != expected or any(type(v) is not int for v in frames.get(label, [])):
            problems.append(label + ': actual listener field/close state differs')
    if frames.get('kn-listener-lifetime-counts') != [0, 0, 1]:
        problems.append('stopped preentry callback ran or positive entered callback missing')
    required = {'kn-listener-source-native': {30: 1, 28: 1},
                'kn-listener-pending-native': {28: 1, 31: 0},
                'kn-listener-entry-native': {25: 1, 31: 1},
                'kn-listener-lifetime-drained': {25: 0, 28: 0, 30: 0, 31: 0}}
    for label, expected in required.items():
        value = frames.get(label)
        if (not isinstance(value, list) or len(value) != 110 or value[0] != 70501 or
                any(type(v) is not int or v < 0 or v > 2**53 - 1 for v in value)):
            problems.append(label + ': missing/malformed native observation')
        elif any(value[i] != target for i, target in expected.items()):
            problems.append(label + ': independent native phase differs')
    return problems
