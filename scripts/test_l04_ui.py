"""Synthetic rejection controls for the L04 target-log oracle; no UI execution."""
import copy
import json
import unittest
from verify_l04_ui import inspect_frames


def fixture():
    rows = []
    def add(event, index, *, active, created, drained, ordinary, destroyed, released, page=False, value=-1, closed=0):
        row = {'event': event, 'nonce': 'fixed-run', 'pid': 117, 'mainThread': True,
               'counts': {'active': active, 'created': created, 'drained': drained, 'sourceClosed': closed},
               'ordinaryValue': ordinary, 'destroyed': destroyed, 'released': released}
        if page:
            row.update(pageID=f'00000000-0000-0000-0000-{index:012d}', framework='swiftui' if index <= 3 else 'uikit',
                       pageValue=value, status='stopped' if event == 'page-drained' else 'observing')
        rows.append(row)
    add('owner-started', 0, active=1, created=1, drained=0, ordinary=-1, destroyed=0, released=0)
    for i in range(1, 7):
        old = -1 if i == 1 else 2 * i - 2
        add('page-created', i, active=1, created=i, drained=i-1, ordinary=old, destroyed=i-1, released=i-1, page=True)
        for event in ('page-started', 'page-refreshed', 'duplicate-rejected', 'page-value', 'page-disappeared'):
            value = 2 * i - 1 if event in ('page-value', 'page-disappeared') else -1
            add(event, i, active=2, created=i+1, drained=i-1, ordinary=value if value != -1 else old,
                destroyed=i-1, released=i-1, page=True, value=value)
        for event in ('page-drained', 'controller-destroyed', 'model-release-observed'):
            add(event, i, active=1, created=i+1, drained=i, ordinary=2*i-1,
                destroyed=i, released=i if event == 'model-release-observed' else i-1, page=True, value=2*i-1)
        add('after-page-value', i, active=1, created=i+1, drained=i, ordinary=2*i, destroyed=i, released=i)
    add('owner-closed', 6, active=0, created=7, drained=7, ordinary=12, destroyed=6, released=6, closed=1)
    return rows


class UIOracleTests(unittest.TestCase):
    def check(self, rows, nonce='fixed-run'):
        return inspect_frames('\n'.join(json.dumps(r) for r in rows), nonce)

    def test_exact_independent_lifecycle_sequence(self):
        self.assertEqual(self.check(fixture())['fresh_pages'], 6)

    def test_missing_duplicate_unknown_frames_rejected(self):
        for change in ('missing', 'duplicate', 'unknown'):
            rows = fixture()
            if change == 'missing': rows.pop(4)
            elif change == 'duplicate': rows.insert(4, copy.deepcopy(rows[4]))
            else: rows[4]['event'] = 'fabricated'
            with self.subTest(change=change), self.assertRaises(ValueError): self.check(rows)

    def test_wrong_nonce_pid_and_thread_rejected(self):
        for field, value in [('nonce', 'other'), ('pid', 118), ('mainThread', False)]:
            rows = fixture(); rows[8][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.check(rows)

    def test_duplicate_registration_shared_close_and_wrong_value_rejected(self):
        for change in ('registration', 'shared-close', 'value'):
            rows = fixture()
            if change == 'registration': rows[4]['counts']['created'] += 1
            elif change == 'shared-close': rows[7]['counts']['sourceClosed'] = 1
            else: rows[5]['pageValue'] = 2
            with self.subTest(change=change), self.assertRaises(ValueError): self.check(rows)

    def test_reused_identity_and_release_before_drain_rejected(self):
        rows = fixture()
        for row in rows[11:20]: row['pageID'] = rows[1]['pageID']
        with self.assertRaises(ValueError): self.check(rows)
        rows = fixture(); rows[7], rows[9] = rows[9], rows[7]
        with self.assertRaises(ValueError): self.check(rows)

    def test_missing_final_cleanup_rejected(self):
        rows = fixture(); rows[-1]['counts']['active'] = 1
        with self.assertRaises(ValueError): self.check(rows)


if __name__ == '__main__':
    unittest.main()
