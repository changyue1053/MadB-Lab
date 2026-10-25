"""Lab-owned normal-env Kotlin admission assertions; no host VM exit claim.

The caller binds these frames to the admitted candidate, fresh nonce/PID and
actual public layouts. This module never reads producer implementation files.
"""
MAX_SAFE = 2**53 - 1
ZERO = (8, 11, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 35, 39, 40, 47, 50,
        58, 63, 64, 65, 66, 68, 71, 73, 77, 80, 83, 87, 96, 99, 105, 107)
PAIRS = ((9, 10), (12, 13), (14, 15), (20, 21), (33, 34), (45, 46), (48, 49),
         (53, 54), (54, 55), (56, 57), (60, 61), (78, 79), (81, 82), (84, 85),
         (97, 98), (100, 101), (102, 103), (108, 109))
EPOCHS = ('epoch1', 'epoch2', 'retry1', 'retry2', 'retry3', 'retry4')
LABELS = {
    'initial-admission': 'admission', 'workerfirst-admission': 'admission',
    'workerfirst': 'vector', 'epoch-key-changed': 'vector',
    'epoch2-live-waiter': 'native', 'epoch2-after-old-calls': 'native',
    'epoch2-local-id1': 'vector', 'old-key-rejections': 'vector', 'epoch2-result': 'vector', 'admission-complete': 'vector',
}
for epoch in EPOCHS:
    LABELS.update({epoch + '-closed': 'native', epoch + '-admission': 'admission'})
    if epoch != 'epoch2':
        LABELS[epoch + '-values'] = 'vector'
for stage in range(5):
    LABELS.update({f'partial-{stage}-{suffix}': kind for suffix, kind in (
        ('before', 'admission'), ('immediate', 'admission'), ('raw-immediate', 'native'),
        ('ack', 'admission'), ('drained', 'native'))})


def predicates(frames):
    """Return failures, including absent/malformed frames; never infer a pass."""
    problems = []
    def need(ok, reason):
        if not ok:
            problems.append(reason)
    for label, kind in LABELS.items():
        value = frames.get(label)
        valid = isinstance(value, list) and all(type(v) is int and abs(v) <= MAX_SAFE for v in value)
        if kind == 'native':
            valid = valid and len(value) == 110 and value[0] == 70501
        elif kind == 'admission':
            valid = valid and len(value) == 13 and all(v >= 0 for v in value)
        need(valid, label + ': missing or malformed frame')
    if problems:
        return problems

    def drained(label):
        f = frames[label]
        need(all(f[i] == 0 for i in ZERO), label + ': native/managed owners or errors remain')
        need(all(f[a] == f[b] for a, b in PAIRS), label + ': physical allocation/cleanup pairs differ')

    initial, rejected = frames['initial-admission'], frames['workerfirst-admission']
    need(all(initial[i] == 0 for i in (0, 4, 6)), 'provider was not fresh before Worker-first')
    need(all(rejected[i] == 0 for i in (0, 4, 6)) and rejected[2] == initial[2] + 1,
         'Worker rejection initialized provider or did not use actual main-env gate')
    need(frames['workerfirst'] == [1, 0], 'Worker did not recoverably reject and exit normally')
    need(frames['epoch-key-changed'] == [1], 'same-env reopen reused old epoch key')
    need(frames['epoch2-local-id1'] == [7, 7], 'current local id1 was not positively observed pending')
    need(frames['old-key-rejections'] == [1, 1, 1, 1], 'not all retained old entry points rejected')
    for label in ('epoch2-live-waiter', 'epoch2-after-old-calls'):
        need(all(frames[label][i] == 1 for i in (24, 26, 41)), label + ': current owner/waiter changed')
    before, after = frames['epoch2-live-waiter'], frames['epoch2-after-old-calls']
    need(all(before[i] == after[i] for i in (9, 10, 11, 12, 13, 14, 15, 24, 26, 27, 36)),
         'stale calls mutated current work, payload, generation or owner')
    need(frames['epoch2-result'] == [42], 'new epoch result was lost or corrupted')

    previous_epoch = 0
    for epoch in EPOCHS:
        f, a = frames[epoch + '-closed'], frames[epoch + '-admission']
        need(f[1] == 4 and f[2] == 1 and f[7] == 1 and f[72] == 3,
             epoch + ': missing actual consumed physical runtime ACK')
        drained(epoch + '-closed')
        need(all(f[i] > 0 for i in (9, 12, 14, 45, 48, 102, 108)),
             epoch + ': absent real allocation/work/join/TSFN activity')
        need(a[6] == 0 and a[7] > previous_epoch, epoch + ': admission slot/epoch not retired')
        previous_epoch = a[7]
        if epoch != 'epoch2':
            need(frames[epoch + '-values'] == [42, 7, 8], epoch + ': retry did not execute work and both streams')

    for stage in range(5):
        prefix = f'partial-{stage}-'
        before, immediate, ack = (frames[prefix + n] for n in ('before', 'immediate', 'ack'))
        need(before[6] == 0, prefix + 'failure armed with occupied admission')
        need(immediate[0] == before[0] + 1 and immediate[1] == before[1] + 1,
             prefix + 'injection did not reach a fresh real admission attempt')
        need(ack[0] == before[0] + 1 and ack[1] == before[1] + 1 and
             ack[8] == before[8] + 1 and ack[9] == stage and
             ack[5] == ack[6] == ack[10] == 0, prefix + 'missing actual rollback ACK')
        drained(prefix + 'drained')
    need(frames['admission-complete'] == [1], 'admission consumer incomplete')
    return problems
