"""Independent L05 router replacement observations; host parsing is not device proof."""
import json
import re

from l05_observations import click_center, find_node


EXPECTED = {
    'page-created-1': [1],
    'page-attached-1': [1, 0],
    'page-published-1': [1, 11, 1],
    'page-destroyed-1': [1],
    'page-drained-1': [1],
    'after-destroy-published-1': [1, 12, 2, 101],
    'page-created-2': [2],
    'page-attached-2': [2, 0],
    'page-published-2': [2, 21, 3],
    'page-destroyed-2': [2],
    'page-drained-2': [2],
    'after-destroy-published-2': [2, 22, 4, 102],
    'page-created-3': [3],
    'page-attached-3': [3, 0],
    'page-published-3': [3, 31, 5],
    'page-destroyed-3': [3],
    'page-drained-3': [3],
    'after-destroy-published-3': [3, 32, 6, 103],
    'owner-closed': [3, 3, 6, 1],
}

# Each phase requires a separate actual hierarchy capture. Away has no old page
# UI; its ordinary subscriber count proves continued delivery after page drain.
UI_EXPECTED = {}
for _page in (1, 2, 3):
    for _phase, _value in (('PAGE_READY', 'EMPTY'), ('PAGE_PUBLISHED', 'PAGE-' + str(_page))):
        _name = _phase + '_' + str(_page)
        UI_EXPECTED[_name] = {'l05-life-phase': _name, 'l05-life-page-id': str(_page),
                              'l05-life-value': _value}
    for _phase, _count in (('AWAY_READY', 2 * _page - 1), ('AWAY_PUBLISHED', 2 * _page)):
        _name = _phase + '_' + str(_page)
        UI_EXPECTED[_name] = {'l05-life-phase': _name, 'l05-life-page-id': str(_page),
                              'l05-life-ordinary': str(_count)}
UI_EXPECTED['FINISHED'] = {'l05-life-phase': 'FINISHED', 'l05-life-page-id': '3', 'l05-life-ordinary': '6'}
UI_PHASES = tuple(UI_EXPECTED)

_PROTOCOL = re.compile(r'(?<!\S)(L05_LIFECYCLE_[A-Z_]+)\s+(\S+)')
_TAG = re.compile(r'[A-Fa-f0-9]+/MadBL05Lifecycle:')
_PID = re.compile(r'[1-9][0-9]*')


def parse(raw, *, nonce, pid, complete=False):
    """Accept only the ordered exact frame set followed by one final marker.

    Valid prefixes remain incomplete while the runner polls. A premature marker,
    target failure or invalid frame fails immediately, even without complete=True.
    Other nonces cannot supply evidence. No result proves queued late callbacks,
    background handling or native resource counters absent from this ordinary SDK.
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
        if marker == 'L05_LIFECYCLE_COMPLETE':
            markers += 1
            if message != 'L05_LIFECYCLE_COMPLETE ' + nonce:
                errors.append('completion marker is not exact')
            if markers != 1:
                errors.append('duplicate completion')
            if tuple(frames) != ordered:
                errors.append('completion before all ordered observations')
        elif marker == 'L05_LIFECYCLE_FAILED':
            errors.append('target lifecycle assertion failed')
        elif marker == 'L05_LIFECYCLE_CASE':
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
            errors.append('unknown lifecycle marker')
    finished = markers == 1 and tuple(frames) == ordered and not errors
    if complete and not finished:
        errors.append('final lifecycle evidence incomplete or invalid')
    return {'errors': errors, 'frames': frames, 'complete': finished, 'lines': lines,
            'pid': pid, 'nonce': nonce, 'status': 'failed' if errors else 'passed' if finished else 'incomplete',
            'scope': 'three actual page replacements and post-drain publication; UI hierarchy checked separately',
            'certifies_l05': False}
