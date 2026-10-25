"""Independent assertions for ordinary SDK behavior under companion observation."""
SCENARIOS = {
    'getters-observed': {'getter-report': 'vector', 'getter-before-close': 'native', 'getter-after-close': 'native'},
    'listener-stop-throw': {'listener-entered': 'native', 'listener-entered-facade': 'facade',
        'listener-stopped-entered': 'native', 'listener-stopped': 'native', 'listener-stopped-facade': 'facade',
        'listener-values': 'vector', 'listener-all-closed': 'native', 'listener-failure-values': 'vector'},
    'request-only-observed': {'request-only-counts': 'vector', 'request-only-after': 'native', 'request-only-facade': 'facade'},
    'distinct-operation-denied': {'distinct-before-close': 'operation', 'distinct-after-denial': 'operation', 'distinct-close-budget': 'native'},
    'cancel-terminal-race': {'race-terminal': 'operation', 'race-settlements': 'vector'},
}
GATED = {'distinct-operation-denied', 'cancel-terminal-race'}


def predicates(case, frames):
    problems = []
    def need(condition, message):
        if not condition:
            problems.append(message)
    def fields(label, expected):
        need(all(frames[label][i] == value for i, value in expected.items()), label + ': owner/count mismatch')
    if case == 'getters-observed':
        need(frames['getter-report'] == [16, 1, 1, 2, 1, 0, 2], 'getter/original-error/positive-setter evidence mismatch')
        before, after = frames['getter-before-close'], frames['getter-after-close']
        need(all(after[i] == before[i] for i in (33, 36)), 'close in getter admitted provider work')
        need(after[2] == after[3] == 0 and after[52] == after[53], 'getter retained entry or scratch')
    elif case == 'listener-stop-throw':
        fields('listener-entered', {5: 2, 9: 1})
        fields('listener-entered-facade', {3: 2})
        fields('listener-stopped-entered', {5: 2, 9: 1})
        fields('listener-stopped', {5: 1, 6: 0, 9: 0, 29: 1})
        fields('listener-stopped-facade', {3: 1})
        fields('listener-all-closed', {5: 0, 6: 0, 9: 0, 29: 0})
        end = frames['listener-all-closed']
        need(end[33] == end[34], 'listener model allocation/release imbalance')
        need(frames['listener-values'] == [1, 2, 1, 2], 'stop permitted another callback or corrupted sibling FIFO')
        need(frames['listener-failure-values'] == [1, 4, 3, 4], 'throwing callback repeated or stopped sibling recovery')
    elif case == 'request-only-observed':
        need(frames['request-only-counts'] == [16, 1], 'request-only capacity reuse or failure tombstone mismatch')
        fields('request-only-after', {5: 0, 11: 0, 19: 0, 29: 0})
        fields('request-only-facade', {1: 0, 3: 0})
    elif case == 'distinct-operation-denied':
        fields('distinct-before-close', {1: 0, 2: 0})
        fields('distinct-after-denial', {1: 3})
        fields('distinct-close-budget', {11: 32, 19: 32})
    elif case == 'cancel-terminal-race':
        winner = frames['race-terminal'][1]
        need(winner in (1, 3), 'race produced an illegal winner')
        need(frames['race-settlements'] == ([1, 1, 0] if winner == 1 else [3, 0, 1]), 'race settled more than once or disagreed with Core winner')
    return problems
