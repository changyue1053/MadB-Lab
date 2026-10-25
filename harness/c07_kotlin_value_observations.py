"""Independent consumer invariants for Kotlin values, reentry and listener lifetime."""
SCENARIOS = {
    'kotlin-getters': {'getter-report': 'vector', 'getter-before-close': 'native', 'getter-after-close': 'native'},
    'kotlin-copies': {'copy-values': 'vector', 'copy-closed': 'native'},
    'kotlin-listeners': {'listener-entered': 'native', 'listener-stopped-entered': 'native',
        'listener-stopped': 'native', 'listener-values': 'vector', 'listener-all-closed': 'native',
        'listener-failure-values': 'vector'},
    'kotlin-request-only': {'request-only-counts': 'vector', 'request-only-closed': 'native'},
}


def predicates(case, frames):
    problems = []
    expected = SCENARIOS.get(case)
    if expected is None:
        return ['unknown Kotlin value scenario']
    for label, kind in expected.items():
        value = frames.get(label)
        if (not isinstance(value, list) or any(type(n) is not int or abs(n) > 2**53 - 1 for n in value)
                or kind == 'native' and (len(value) != 110 or value[0] != 70501)):
            problems.append('missing/malformed observation: ' + label)
    if problems:
        return problems

    def need(condition, message):
        if not condition:
            problems.append(message)

    def no_children(label):
        value = frames[label]
        need(all(value[i] == 0 for i in (11, 24, 25, 26, 27, 28, 29, 30, 31, 32, 35)),
             label + ': retained model, child, waiter, byte or delivery ownership')
        need(value[9] > 0 and value[9] == value[10], label + ': missing/imbalanced actual model lifetime')
        need(value[33] == value[34], label + ': scratch ownership not returned')

    if case == 'kotlin-getters':
        need(frames['getter-report'] == [16, 1, 1, 2, 1, 0, 2], 'getter reads/errors/setter positive control differ')
        before, after = frames['getter-before-close'], frames['getter-after-close']
        need(before[9] > 0, 'getter positive calls did not allocate a real native model')
        need(after[9] == before[9] and after[14] == before[14], 'closed getter admitted provider work')
        need(after[33] == after[34] and after[35] == after[31] == 0, 'getter retained temporary ownership')
    elif case == 'kotlin-copies':
        need(frames['copy-values'] == [42, 2, 2, 90, 1, 2, 999, 333], 'input/result/event snapshot aliasing or lost result')
        no_children('copy-closed')
        value = frames['copy-closed']
        need(value[12] > 0 and value[12] == value[13] and value[14] == value[15] == 1,
             'copied operation did not execute and physically join')
        need(value[18] == 4 and value[39] == 0, 'event copies or Engine close ACK missing')
    elif case == 'kotlin-listeners':
        for label in ('listener-entered', 'listener-stopped-entered'):
            value = frames[label]
            need(value[25] == 2 and value[31] == 1 and value[32] > 0,
                 label + ': current entered delivery must survive stop')
        value = frames['listener-stopped']
        need(value[25] == 1 and value[31] == value[30] == value[28] == 0,
             'stop retained source/delivery or removed sibling')
        need(frames['listener-values'] == [1, 2, 1, 2], 'stop allowed another callback or broke sibling FIFO')
        need(frames['listener-failure-values'] == [1, 4, 3, 4], 'listener failure repeated or poisoned sibling')
        no_children('listener-all-closed')
        need(frames['listener-all-closed'][19] == 1, 'actual throwing listener was not recorded exactly once')
    elif case == 'kotlin-request-only':
        need(frames['request-only-counts'] == [16, 1], 'request-only capacity reuse or old failure differs')
        no_children('request-only-closed')
        need(frames['request-only-closed'][19] == 1, 'request-only failure not executed exactly once')
    return problems
