"""Independent C09 physical-ACK/before-receipt oracle, never a producer predicate."""
import json

from c07_companion_observations import _frame_error, ZERO_OWNERS, PAIRS
from c07_kotlin_admission_observations import ZERO as KOTLIN_ZERO, PAIRS as KOTLIN_PAIRS

SCENARIOS = ('normal', 'callback-throws', 'callback-promise', 'callback-thenable',
             'callback-code-getter', 'callback-throw-undefined', 'callback-throw-proxy')


def labels(route, scenario):
    result = {'first-runtime-open': 'kotlin' if route == 'kotlin' else 'native'}
    if scenario == 'normal':
        result.update({name: 'text' for name in ('registration-invalid-runtime', 'registration-invalid-callback',
                      'registration-duplicate', 'registration-late')})
    result.update({'receipt-window-native': 'kotlin' if route == 'kotlin' else 'native',
                   'receipt-window-js': 'settling' if route == 'kotlin' else 'facade'})
    if route == 'kotlin':
        result['receipt-window-admission'] = 'admission'
    result['receipt-window-reopen-rejected'] = 'text'
    if route == 'kotlin':
        result['receipt-window-after-reopen-admission'] = 'admission'
    result['receipt-window-reentry'] = 'vector'
    if scenario == 'normal':
        result['receipt-window-reregister-rejected'] = 'text'
        result['receipt-window-probe-returned'] = 'vector'
        suffix = 'receipt-consumed'
    else:
        result['callback-fault-entered'] = 'vector'
        result['close-rejected'] = 'text'
        suffix = 'receipt-unconsumed'
    result[suffix + '-native'] = 'kotlin' if route == 'kotlin' else 'native'
    result[suffix + '-js'] = 'settling' if route == 'kotlin' else 'facade'
    if route == 'kotlin':
        result[suffix + '-admission'] = 'admission'
    result['original-close-outcome'] = 'vector'
    if scenario == 'normal':
        result['registration-closed'] = 'text'
        result['second-runtime-open'] = 'kotlin' if route == 'kotlin' else 'native'
        result['new-runtime-result'] = 'vector'
        result['new-runtime-closed'] = 'kotlin' if route == 'kotlin' else 'native'
        result['new-runtime-js'] = 'settling' if route == 'kotlin' else 'facade'
        if route == 'kotlin':
            result['new-runtime-admission'] = 'admission'
    else:
        result['failure-reopen-rejected'] = 'text'
        result['failure-repeat-close'] = 'vector'
        result['failure-late-native'] = 'kotlin' if route == 'kotlin' else 'native'
        result['failure-late-js'] = 'settling' if route == 'kotlin' else 'facade'
        if route == 'kotlin':
            result['failure-late-admission'] = 'admission'
        result['failure-late-outcome'] = 'vector'
        result['callback-property-reads'] = 'vector'
    return result


def physical(frame, route, receipt, generations=1):
    errors = []
    def need(ok, message):
        if not ok:
            errors.append(message)
    if route == 'kotlin':
        need([frame[i] for i in (1, 2, 7, 72)] == [4, receipt, 1, 3], 'Kotlin physical ACK/receipt differs')
        need(all(frame[i] == 0 for i in KOTLIN_ZERO), 'Kotlin owner/error remains')
        need(all(frame[a] == frame[b] for a, b in KOTLIN_PAIRS), 'Kotlin lifetime pair differs')
        need(frame[12] == frame[13] == generations and all(frame[i] > 0 for i in (14, 45, 48, 78, 102, 108)),
             'Kotlin actual work/join/ref/TSFN activity absent')
    else:
        need([frame[i] for i in (1, 16, 17, 32, 40, 41, 44, 45, 55)] == [3, 1, 1, receipt, 1, 1, 1, 1, 2],
             'native physical ACK/receipt/finalizer differs')
        need(all(frame[i] == 0 for i in ZERO_OWNERS), 'native owner/error remains')
        need(all(frame[i] == frame[i + 1] for i in PAIRS), 'native lifetime pair differs')
        need(all(frame[i] == 1 for i in range(65, 71)), 'actual thread stages incomplete')
        need(0 < frame[71] < frame[72] < frame[73] < frame[75] < frame[76] and 0 < frame[74] < frame[75],
             'physical join does not include TLS/executor retirement')
        need(all(frame[i] > 0 for i in (62, 63, 64, 157)) and frame[162] == frame[163],
             'thread/API/null-env owner witnesses missing')
    return errors


def predicates(frames, route, scenario):
    errors = physical(frames['receipt-window-native'], route, 0)
    def need(ok, message):
        if not ok:
            errors.append(message)
    def js(values, *, in_probe=False, failed=False):
        if route == 'kotlin':
            need([values[i] for i in (5, 7, 8)] == [0, 0, int(in_probe)], 'Kotlin settling/timer/tick differs')
        elif in_probe:
            need([values[i] for i in (1, 2, 5, 6, 7, 8, 9, 10)] == [0, 0, 1, 0, 1, 1, 0, 0],
                 'facade not inside unsettled normal parent-close tick')
        else:
            need(all(values[i] == 0 for i in (1, 2, 3, 4, 5, 6, 7, 13, 14))
                 and values[9] == int(not failed) and values[10] == int(failed),
                 'facade final closed/failed/owner state differs')
    js(frames['receipt-window-js'], in_probe=True)
    rejection = 'AlreadyInitialized' if route == 'kotlin' else 'RuntimeAlreadyOpen'
    need(frames['receipt-window-reopen-rejected'] == rejection, 'reopen did not reject with exact occupied-slot code')
    need(frames['receipt-window-reentry'] == [0, 0, 1], 'original close settled or reentrant close differed inside hook')
    if route == 'kotlin':
        audit = frames['receipt-window-admission']
        # The reviewed bootstrap Slot enum uses 5 for AwaitingReceipt.
        need(audit[6] == 5 and audit[7] > 0 and audit[5] == audit[10] == 1 and audit[11] == 0,
             'receipt window lost Kotlin awaiting-receipt slot/epoch')
        need(frames['receipt-window-after-reopen-admission'] == audit,
             'rejected Kotlin admission mutated current slot/epoch/audit')
    if scenario == 'normal':
        for label, expected in (('registration-invalid-runtime', 'InvalidArgument'),
                                ('registration-invalid-callback', 'InvalidArgument'),
                                ('registration-duplicate', 'InvalidArgument'),
                                ('registration-late', 'Closing'),
                                ('receipt-window-reregister-rejected', 'Closing'),
                                ('registration-closed', 'Closed')):
            need(frames[label] == expected, label + ': exact registration rejection differs')
        need(frames['receipt-window-probe-returned'] == [1], 'hook did not return exactly once')
        need(frames['original-close-outcome'] == [1, 0, 1], 'original normal close/hook count differs')
        need(frames['new-runtime-result'] == [42], 'same-env reopened runtime did not perform real work')
        for name, generations in (('receipt-consumed-native', 1), ('new-runtime-closed', 2)):
            errors.extend(name + ': ' + value for value in physical(frames[name], route, 1, generations))
        js(frames['receipt-consumed-js']); js(frames['new-runtime-js'])
        if route == 'kotlin':
            closed = frames['receipt-consumed-admission']; second = frames['new-runtime-admission']
            need(closed[6] == 0 and closed[7] == audit[7] and closed[11] == 1,
                 'first Kotlin slot/epoch/receipt not retired after callback')
            need(second[6] == 0 and second[7] > closed[7] and second[11] == 1,
                 'new Kotlin admission epoch not independently closed')
    else:
        need(frames['callback-fault-entered'] == [1], 'fault callback did not enter exactly once')
        expected_error = {'callback-throws': 'InjectedReceiptProbe', 'callback-code-getter': 'InjectedReceiptGetter',
                          'callback-throw-undefined': 'CallbackFailure', 'callback-throw-proxy': 'CallbackFailure'}.get(scenario, 'InvalidArgument')
        need(frames['close-rejected'] == expected_error, 'callback failure did not reject with expected error')
        errors.extend(physical(frames['receipt-unconsumed-native'], route, 0))
        js(frames['receipt-unconsumed-js'], failed=True)
        need(frames['original-close-outcome'] == [0, 1, 1], 'failure was converted to success or hook repeated')
        need(frames['failure-reopen-rejected'] == rejection, 'unconsumed receipt incorrectly freed admission')
        need(frames['failure-repeat-close'] == [1, 1, 0], 'failure promise/error identity or thenable non-invocation differs')
        errors.extend(physical(frames['failure-late-native'], route, 0))
        js(frames['failure-late-js'], failed=True)
        need(frames['failure-late-outcome'] == [0, 1, 1], 'failure late settlement/hook count differs')
        need(frames['callback-property-reads'] == [0, 0, int(scenario == 'callback-throw-proxy')],
             'user then/code property was read or Proxy classification trap differed')
        if route == 'kotlin':
            after = frames['receipt-unconsumed-admission']
            need(after[6:8] == audit[6:8] and after[11] == 0, 'failed hook consumed Kotlin receipt or retired epoch')
            need(frames['failure-late-admission'][6:8] == audit[6:8] and frames['failure-late-admission'][11] == 0,
                 'late failed Kotlin hook consumed receipt or retired epoch')
    return errors


def parse_observation(raw, *, nonce, pid, route, scenario):
    wanted = labels(route, scenario)
    errors, frames = [], {}
    lines = [line for line in raw.splitlines() if nonce in line]
    if not isinstance(pid, str) or not pid.isdigit() or int(pid) <= 0:
        errors.append('missing exact live PID')
    elif any(len(line.split()) < 3 or line.split()[2] != pid for line in lines):
        errors.append('nonce/PID binding mismatch')
    for line in lines:
        prefix = 'C09_RECEIPT_FRAME ' + nonce + ' '
        if prefix not in line:
            continue
        try:
            label, value = line.split(prefix, 1)[1].split(' ', 1)
            value = json.loads(value)
            if label in frames or label not in wanted:
                raise ValueError('duplicate/unknown frame')
            kind = wanted[label]
            if kind == 'text':
                if not isinstance(value, str) or not value:
                    raise ValueError('missing text observation')
            elif kind in ('kotlin', 'settling', 'admission'):
                if (not isinstance(value, list) or len(value) != {'kotlin': 110, 'settling': 9, 'admission': 13}[kind]
                        or any(type(v) is not int or not 0 <= v < 2**53 for v in value)
                        or kind == 'kotlin' and value[0] != 70501):
                    raise ValueError('malformed Kotlin observation')
            elif reason := _frame_error(value, kind):
                raise ValueError(reason)
            frames[label] = value
        except (ValueError, TypeError) as error:
            errors.append('invalid frame: ' + str(error))
    complete = sum(line.endswith('C09_RECEIPT_COMPLETE ' + nonce) for line in lines)
    failures = [line for line in lines if 'PROBE_FAILED ' + nonce + ' ' in line]
    if complete > 1:
        errors.append('duplicate completion')
    if complete:
        if list(frames) != list(wanted):
            errors.append('required ordered observations missing or different')
        else:
            errors.extend(predicates(frames, route, scenario))
        for marker in ('PROBE_STARTED', 'PROBE_PAGE_READY', 'PROBE_FINISHED'):
            if sum(line.endswith(marker + ' ' + nonce) for line in lines) != 1:
                errors.append('missing/duplicate ' + marker)
    return {'status': 'failed' if errors or failures else 'passed' if complete else 'incomplete',
            'nonce': nonce, 'pid': pid, 'route': route, 'scenario': scenario, 'frames': frames,
            'problems': errors, 'failures': failures, 'lines': lines,
            'normal_close': 'passed' if complete and not errors and not failures and scenario == 'normal' else 'not_proved',
            'scope': 'exact candidate after physical ACK/before receipt only', 'certifies_c07': False, 'certifies_c09': False}
