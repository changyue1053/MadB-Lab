"""Independent public waiter invariants. No producer implementation import."""
import re

EXPECTED_ENGINE_COUNTS = {'kotlin-mixed-waiters': 2, 'kotlin-distinct-close-denied': 3}
SCENARIOS = {
    'kotlin-mixed-waiters': {
        **{'kn-waiter-mixed-' + name + '-native': 'native' for name in
           ('baseline', 'held', 'full', 'closed-values', 'parent-full', 'drained')},
        'kn-waiter-mixed-held-control': 'control', 'kn-waiter-mixed-settling': 'settling',
        'kn-waiter-mixed-closed-values': 'vector', 'kn-waiter-mixed-completed': 'vector',
        'kn-waiter-mixed-parent-control': 'vector', 'kn-waiter-mixed-final-settling': 'settling'},
    'kotlin-distinct-close-denied': {
        **{f'kn-waiter-distinct-{kind}-{name}-native': 'native' for kind in range(3)
           for name in ('baseline', 'held', 'full', 'denied', 'capacity', 'drained')},
        **{f'kn-waiter-distinct-{kind}-held-control': 'control' for kind in range(3)},
        **{f'kn-waiter-distinct-{kind}-{name}': 'vector' for kind in range(3) for name in ('request-effect', 'retry', 'open-before-denial')},
        'kn-waiter-distinct-1-sub-before': 'vector', 'kn-waiter-distinct-1-sub-after': 'vector',
    },
}


def predicates(case, frames):
    failures = []
    def need(ok, why):
        if not ok:
            failures.append(why)
    expected = SCENARIOS.get(case)
    if expected is None:
        return ['unknown waiter scenario']
    parsed = {}
    for label, kind in expected.items():
        value = frames.get(label)
        if kind == 'control':
            if type(value) is not str:
                failures.append(label + ': raw CSV required'); continue
            tokens = value.split(',')
            if len(tokens) != 31 or tokens[0] != '1' or any(
                re.fullmatch(r'0|[1-9][0-9]*', token) is None and not (i == 6 and token == '-1')
                for i, token in enumerate(tokens)):
                failures.append(label + ': controls1/31 malformed'); continue
            limit = '18446744073709551615'
            if any(t != '-1' and (len(t) > len(limit) or (len(t) == len(limit) and t > limit)) for t in tokens):
                failures.append(label + ': uint64 overflow'); continue
            # No identity token at 4/5/8 becomes a Python/JS numeric value.
            parsed[label] = tokens
        else:
            if type(value) is not list or any(type(v) is not int or not 0 <= v <= 2**53 - 1 for v in value):
                failures.append(label + ': safe integer vector required'); continue
            if kind == 'native' and (len(value) != 110 or value[0] != 70501 or value[8] != 0):
                failures.append(label + ':110 format/owner error'); continue
            if kind == 'settling' and (len(value) != 9 or value[7] not in (0, 1) or value[8] not in (0, 1)):
                failures.append(label + ': settlement9 malformed'); continue
            parsed[label] = value
    if failures:
        return failures
    need({k for k in frames if k.startswith('kn-waiter-')} == set(expected), 'unexpected waiter label')
    def eq(label, mapping):
        for index, target in mapping.items():
            need(parsed[label][index] == target, label + ': field ' + str(index) + ' expected ' + str(target))
    def held(prefix, count):
        before, during = parsed[prefix + '-baseline-native'], parsed[prefix + '-held-native']
        need(during[41] - before[41] == count, prefix + ': genuine selected Work entries missing')
        c = parsed[prefix + '-held-control']
        need(c[3] == '1' and c[4] != '0' and c[5] != '0', prefix + ': no exact actual work identity/phase')
    zero_children = {11: 0, 24: 0, 25: 0, 26: 0, 27: 0, 28: 0, 29: 0, 30: 0, 31: 0, 35: 0}
    if case == 'kotlin-mixed-waiters':
        p = 'kn-waiter-mixed'
        held(p, 1)
        eq(p + '-baseline-native', {12: 2, 13: 1, 24: 0, 25: 0, 26: 0, 39: 1})
        eq(p + '-held-native', {24: 1, 25: 1, 30: 1, 31: 0})
        for label in ('full', 'closed-values'):
            eq(p + '-' + label + '-native', {12: 2, 13: 1, 24: 1, 25: 1, 26: 32, 30: 1, 31: 0, 39: 1})
        need(parsed[p + '-settling'][5] == 0, 'full checkpoint unexpectedly within settlement')
        need(parsed[p + '-closed-values'] == [3, 31, 0], 'closed wrappers used slots or close observations memoized')
        need(parsed[p + '-completed'] == [1, 10, 10, 11, 0], 'mixed observation categories/completion differ')
        eq(p + '-parent-full-native', {12: 2, 13: 1, 24: 1, 25: 1, 26: 32, 30: 1, 37: 1, 39: 1})
        need(parsed[p + '-parent-control'] == [1], 'parent control was not memoized')
        eq(p + '-final-settling', {5: 0, 7: 0, 8: 0})
        eq(p + '-drained-native', zero_children)
        eq(p + '-drained-native', {12: 2, 13: 2, 39: 0})
    else:
        for kind in range(3):
            p = f'kn-waiter-distinct-{kind}'
            held(p, 1)
            eq(p + '-baseline-native', {12: kind + 1, 13: kind, 24: 0, 25: 0, 26: 0, 39: 1})
            owner = {24: 1, 25: 1, 30: 1}
            eq(p + '-held-native', owner)
            for phase in ('full', 'denied'):
                eq(p + '-' + phase + '-native', {**owner, 12: kind + 1, 13: kind, 26: 32, 31: 0, 39: 1})
            need(parsed[p + '-request-effect'] == [0 if kind == 0 else 1, 0], p + ': close request did not precede observer denial')
            need(parsed[p + '-open-before-denial'] == [5], p + ': filler already closed the Engine')
            if kind == 1:
                need(parsed[p + '-sub-before'] == [1, 0, 0, 1] and parsed[p + '-sub-after'] == [1, 1, 0, 1], p + ': actual target sub did not transition open to pending stop')
            eq(p + '-capacity-native', {26: 0})
            need(parsed[p + '-retry'] == [1, 5 if kind == 0 else 0, 0], p + ': retry/result cancellation differs')
            eq(p + '-drained-native', zero_children)
            eq(p + '-drained-native', {12: kind + 1, 13: kind + 1, 39: 0})
    return failures
