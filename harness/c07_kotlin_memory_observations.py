"""Independent public memory22 oracle; no producer modules or business model copy.

The harness must additionally reject duplicate labels, require a successful
consumer, await normal Runtime.close and validate the separate final110 ACK.
This oracle requires a post-ACK memory-final read; process exit never substitutes.
"""
from __future__ import annotations
import re

NAMES = ('kotlin-memory-retained-scratch', 'kotlin-memory-state-staging')
SCENARIOS = {
    NAMES[0]: {
        'memory-baseline': 'memory', 'memory-work-held-control': 'control',
        'memory-retained-native': 'native', 'memory-retained-full': 'memory',
        'memory-scratch-empty': 'memory', 'memory-scratch-returned': 'memory', 'memory-retained-denied': 'memory',
        'memory-drained': 'memory', 'memory-final': 'memory',
    },
    NAMES[1]: {
        'memory-baseline': 'memory', 'memory-delivery-held-control': 'control',
        'memory-state-held': 'memory', 'memory-state-held-native': 'native',
        'memory-state-replaced': 'memory', 'memory-state-replaced-native': 'native',
        'memory-staging-held': 'memory', 'memory-staging-held-control': 'control',
        'memory-staging-denied': 'memory', 'memory-staging-abandoned': 'memory',
        'memory-staging-commit-held': 'memory', 'memory-staging-committed': 'memory',
        'memory-release-sync': 'vector', 'memory-state-trace': 'vector',
        'memory-drained': 'memory', 'memory-final': 'memory',
    },
}
MAX_U64 = (1 << 64) - 1
SAFE = (1 << 53) - 1
DECIMAL = re.compile(r'(?:0|[1-9][0-9]*)\Z')


def parse_memory_csv(raw):
    if type(raw) is not str:
        raise ValueError('memory must retain raw CSV, not a numeric array')
    parts = raw.split(',')
    if len(parts) != 22 or parts[0] != '70603':
        raise ValueError('memory requires format70603/22; unavailable is not zero')
    if any(not DECIMAL.fullmatch(p) for p in parts):
        raise ValueError('noncanonical memory decimal')
    numbers = tuple(int(p) for p in parts)
    if any(v >= MAX_U64 for v in numbers):
        raise ValueError('memory unknown sentinel or uint64 overflow')
    return numbers


def parse_control(raw):
    if type(raw) is not str:
        raise ValueError('control must retain CSV')
    f = raw.split(',')
    if len(f) != 31 or f[0] != '1':
        raise ValueError('control format1/31 required')
    for i, token in enumerate(f):
        if i == 6 and token == '-1':
            continue
        if not DECIMAL.fullmatch(token) or len(token) > 20 or int(token) > MAX_U64:
            raise ValueError('invalid control decimal')
    return f  # identities remain strings


def native(raw):
    if type(raw) is not list or len(raw) != 110:
        raise ValueError('native110 required')
    if any(type(v) is not int or not 0 <= v <= SAFE for v in raw):
        raise ValueError('unsafe native counter')
    if raw[0] != 70501 or raw[8] != 0:
        raise ValueError('native format or owner fault')
    return raw


def predicates(case, frames):
    errors = []
    previous_memory = None
    cumulative = (2,3,4,6,7,8,9,10,12,13,14,15,17,18,19,20,21)
    def need(ok, why):
        if not ok:
            errors.append(why)
    def m(label):
        nonlocal previous_memory
        f = parse_memory_csv(frames[label])
        if previous_memory is not None:
            need(all(f[i] >= previous_memory[i] for i in cumulative), label + ': cumulative evidence went backwards')
        previous_memory = f
        need(f[1] <= 4096 and f[2] <= 4096 and f[2] >= f[1], label + ': canonical budget/peak')
        need(f[6] >= f[5] and f[12] >= f[11] and f[17] >= f[16], label + ': peak below real current')
        need(f[3] >= f[4] and f[3] - f[4] == f[1], label + ': canonical accounting')
        need(f[7] >= f[8] and f[7] - f[8] == f[5], label + ': actual native allocation accounting')
        need(f[9] >= f[10], label + ': negative live allocation count')
        need(f[13] >= f[14] + f[15] and f[13] - f[14] - f[15] == f[11], label + ': staging role accounting')
        need(f[18] >= f[19] and f[18] - f[19] == f[16] and f[20] >= f[21], label + ': actual UTF scope accounting')
        return f
    def balanced(f, label):
        need(all(f[i] == 0 for i in (1,5,11,16)), label + ': live domain remains')
        need(f[3] == f[4] and f[7] == f[8] and f[9] == f[10], label + ': ledger/model not paired')
        need(f[13] == f[14] + f[15], label + ': staging not settled')
        need(f[18] == f[19] and f[20] == f[21], label + ': UTF scope not freed')
    try:
        if case not in SCENARIOS:
            raise ValueError('unknown memory scenario')
        baseline = m('memory-baseline'); balanced(baseline, 'baseline')
        if case == NAMES[0]:
            gate = parse_control(frames['memory-work-held-control'])
            held = native(frames['memory-retained-native'])
            need(gate[3] == '1' and int(gate[1]) > 0 and gate[4] != '0' and gate[5] != '0', 'no real positive work hold')
            need(held[24] == 4 and held[27] == 4096 and held[12] > held[13] and held[39] == 1, 'four models not retained behind actual worker hold')
            full = m('memory-retained-full'); empty = m('memory-scratch-empty'); scratch = m('memory-scratch-returned'); denied = m('memory-retained-denied')
            need((full[1],full[5],full[11],full[16]) == (4096,4096,0,0), 'retained4096 confused with allocation count')
            need(full[3]-baseline[3] == 4096 and full[7]-baseline[7] == 4096 and full[9]-baseline[9] == 4, 'four actual retained allocations absent')
            need((scratch[1],scratch[5]) == (4096,4096) and scratch[3:5] == full[3:5], 'scratch consumed retained budget')
            need((empty[1],empty[5],empty[16]) == (4096,4096,0) and empty[3:5] == full[3:5], 'empty control changed retained ledger')
            need(empty[7]-full[7] == empty[8]-full[8] == 1 and empty[9]-full[9] == empty[10]-full[10] == 1, 'empty control omitted real minimum allocation')
            empty_bytes = empty[18]-full[18]; empty_arrays = empty[20]-full[20]
            need(empty_bytes >= 4 and empty[19]-full[19] == empty_bytes and empty_arrays >= 2 and empty[21]-full[21] == empty_arrays, 'empty control UTF16 scopes not actually paired')
            need(scratch[6] >= 5120, 'requested-byte peak omitted independent1024 scratch')
            need(scratch[7]-empty[7] == scratch[8]-empty[8] == 1024 and scratch[9]-empty[9] == scratch[10]-empty[10] == 1, 'scratch allocation/free delta differs')
            need(scratch[16] == 0 and scratch[17] >= 2050, 'UTF16 temporary storage unobserved')
            need(scratch[18]-empty[18] == scratch[19]-empty[19] == empty_bytes+4096 and scratch[20]-empty[20] == scratch[21]-empty[21] == empty_arrays, 'input/output UTF16 arrays not independently paired')
            need((denied[1],denied[5]) == (4096,4096) and denied[7:11] == scratch[7:11], 'rejected extra retained model allocated or freed storage')
        else:
            gate = parse_control(frames['memory-delivery-held-control'])
            need(gate[7] == '2' and gate[8] != '0' and int(gate[9]) > 0, 'no real positive pre-entry delivery hold')
            held = m('memory-state-held'); replaced = m('memory-state-replaced')
            for label in ('memory-state-held-native','memory-state-replaced-native'):
                n = native(frames[label]); need(n[29] == 1 and n[31] == 0 and n[27] == 1024, label + ': replacement duplicated ticket or entered early')
            need((held[1],held[5]) == (1024,1024) and (replaced[1],replaced[5]) == (1024,1024), 'retained latest-state storage differs')
            need(replaced[2] >= 2048 and replaced[6] >= 2048, 'replacement peak omitted still-owned old state')
            need(replaced[7]-held[7] == replaced[8]-held[8] == 1024, 'old state not freed exactly after replacement copy')
            staged = m('memory-staging-held'); denied = m('memory-staging-denied'); abandoned = m('memory-staging-abandoned')
            source = parse_control(frames['memory-staging-held-control'])
            need(source[12:15] == ['1','1','1024'], 'source staging not actually held')
            need((staged[1],staged[5],staged[11]) == (2048,2048,1024), 'selected staging not charged with old state')
            need(denied[1:16] == staged[1:16], 'second publication changed existing owner or allocated storage')
            need((abandoned[1],abandoned[5],abandoned[11]) == (1024,1024,0) and abandoned[15]-staged[15] == 1024 and abandoned[8]-staged[8] == 1024, 'abandon did not free only staged copy')
            commit_held = m('memory-staging-commit-held'); committed = m('memory-staging-committed')
            need((commit_held[1],commit_held[5],commit_held[11]) == (2048,2048,1024), 'second staging not real')
            need((committed[1],committed[5],committed[11]) == (1024,1024,0) and committed[14]-commit_held[14] == 1024 and committed[8]-commit_held[8] == 1024, 'commit did not transfer source role and retire old state')
            need(frames['memory-release-sync'] == [0] and frames['memory-state-trace'] == [4], 'abandoned or superseded value reached listener')
        drained = m('memory-drained'); final = m('memory-final')
        balanced(drained, 'drained'); balanced(final, 'post-ACK final')
        need(all(final[i] >= drained[i] for i in (2,3,4,6,7,8,9,10,12,13,14,15,17,18,19,20,21)), 'final read reset cumulative evidence')
    except (ValueError,KeyError,TypeError,IndexError) as error:
        errors.append('missing/malformed memory observation: ' + str(error))
    return errors
