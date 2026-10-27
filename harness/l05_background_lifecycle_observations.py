"""Independent ordinary L05 background observations; host parsing is not device proof."""
import json
import re

from l05_observations import click_center, find_node


EXPECTED = {'initial-ready': [1, 1, 1, 1, 1, 1]}
for _round in range(4):
    EXPECTED['foreground-published-' + str(_round)] = [_round, _round * 10 + 1, _round * 2 + 1]
    if _round < 3:
        _cycle = _round + 1
        EXPECTED['background-entered-' + str(_cycle)] = [_cycle, 1, _cycle * 2 - 1]
        EXPECTED['page-drained-' + str(_cycle)] = [_cycle, 1]
        EXPECTED['background-published-' + str(_cycle)] = [_cycle, _round * 10 + 2, _cycle * 2, 100 + _cycle]
        EXPECTED['foreground-entered-' + str(_cycle)] = [_cycle, _cycle + 1]
        EXPECTED['page-reattached-' + str(_cycle)] = [_cycle, 1, 0]
EXPECTED['owner-closed'] = [1, 3, 4, 7, 1]

# Background is observed through the actual ability callback/logs. Each visible
# phase below requires a separate hierarchy capture after actual foregrounding.
UI_EXPECTED = {}
for _round in range(4):
    for _phase, _value, _count in (
            ('READY', 'EMPTY', 2 * _round),
            ('PUBLISHED', 'FOREGROUND-' + str(_round), 2 * _round + 1)):
        _name = _phase + '_' + str(_round)
        UI_EXPECTED[_name] = {
            'l05-bg-phase': _name, 'l05-bg-page-id': '1',
            'l05-bg-value': _value, 'l05-bg-ordinary': str(_count),
        }
UI_EXPECTED['FINISHED'] = {
    'l05-bg-phase': 'FINISHED', 'l05-bg-page-id': '1',
    'l05-bg-value': 'FOREGROUND-3', 'l05-bg-ordinary': '7',
}
UI_PHASES = tuple(UI_EXPECTED)

_PROTOCOL = re.compile(r'(?<!\S)(L05_BACKGROUND_[A-Z_]+)\s+(\S+)')
_TAG = re.compile(r'[A-Fa-f0-9]+/MadBL05Background:')
_PID = re.compile(r'[1-9][0-9]*')


def parse(raw, *, nonce, pid, complete=False):
    """Require exact ordered frames, PID/nonce binding and one final marker.

    Valid prefixes are incomplete while polling. Missing background, drain or
    publication observations cannot be supplied by later foreground/UI success.
    These ordinary observations do not establish native counters, queued late
    callbacks, recoverable close faults or whole-package certification.
    """
    errors, frames, lines = [], {}, []
    valid_nonce = isinstance(nonce, str) and bool(nonce) and not any(c.isspace() or ord(c) < 32 for c in nonce)
    valid_pid = isinstance(pid, str) and _PID.fullmatch(pid) is not None
    if not valid_nonce:
        errors.append('invalid exact nonce')
    if not valid_pid:
        errors.append('probe PID absent or non-unique')
    markers = 0
    ordered = tuple(EXPECTED)
    for line in raw.splitlines():
        match = _PROTOCOL.search(line)
        if not valid_nonce or match is None or match[2] != nonce:
            continue
        lines.append(line)
        parts = line.split(maxsplit=6)
        if (len(parts) != 7 or not valid_pid or parts[2] != pid
                or _PID.fullmatch(parts[3]) is None or _TAG.fullmatch(parts[5]) is None):
            errors.append('nonce/PID/tag binding mismatch')
            continue
        message = parts[6]
        marker = match[1]
        if not message.startswith(marker + ' ' + nonce):
            errors.append('protocol marker is not the exact log message')
            continue
        if markers:
            errors.append('observation after final completion')
        if marker == 'L05_BACKGROUND_COMPLETE':
            markers += 1
            if message != 'L05_BACKGROUND_COMPLETE ' + nonce:
                errors.append('completion marker is not exact')
            if markers != 1:
                errors.append('duplicate completion')
            if tuple(frames) != ordered:
                errors.append('completion before all ordered observations')
        elif marker == 'L05_BACKGROUND_FAILED':
            errors.append('target background assertion failed')
        elif marker == 'L05_BACKGROUND_CASE':
            prefix = marker + ' ' + nonce + ' '
            try:
                if not message.startswith(prefix):
                    raise ValueError('missing case payload')
                label, encoded = message[len(prefix):].split(' ', 1)
                value = json.loads(encoded)
                if label not in EXPECTED:
                    raise ValueError('unknown observation: ' + label)
                if label in frames:
                    raise ValueError('duplicate observation: ' + label)
                if len(frames) >= len(ordered) or label != ordered[len(frames)]:
                    errors.append('observation order differs: ' + label)
                if not isinstance(value, list) or any(type(item) is not int for item in value) or value != EXPECTED[label]:
                    errors.append('observation value differs: ' + label)
                frames[label] = value
            except (ValueError, TypeError) as error:
                errors.append('malformed observation: ' + str(error))
        else:
            errors.append('unknown background marker')
    finished = markers == 1 and tuple(frames) == ordered and not errors
    if complete and not finished:
        errors.append('final background evidence incomplete or invalid')
    return {
        'errors': errors, 'frames': frames, 'complete': finished, 'lines': lines,
        'pid': pid, 'nonce': nonce,
        'status': 'failed' if errors else 'passed' if finished else 'incomplete',
        'scope': 'three actual background/foreground cycles, same page and shared owner; UI hierarchy checked separately',
        'certifies_l05': False,
    }
