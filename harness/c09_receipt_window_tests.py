"""Adversarial receipt-window oracle checks; synthetic frames are not target evidence."""
import copy
import json
import unittest

from c09_receipt_window_observations import SCENARIOS, labels, parse_observation


def native(receipt):
    f = [0] * 178
    for index, value in {0: 1, 1: 3, 16: 1, 17: 1, 30: 1, 32: receipt, 54: 1, 55: 2,
                         62: 10, 63: 11, 64: 12, 156: 1, 157: 1}.items():
        f[index] = value
    for index in (33, 38, 40, 42, 44, 46, 48, 50, 52):
        f[index] = f[index + 1] = 1
    for index in range(65, 71):
        f[index] = 1
    for index in range(71, 77):
        f[index] = index - 70
    return f


def kotlin(receipt, generation=1):
    f = [0] * 110
    f[0] = 70501; f[1] = 4; f[2] = receipt; f[7] = 1; f[72] = 3
    for first, second in ((9, 10), (12, 13), (14, 15), (20, 21), (33, 34), (45, 46), (48, 49),
                          (53, 54), (54, 55), (56, 57), (60, 61), (78, 79), (81, 82), (84, 85),
                          (97, 98), (100, 101), (102, 103), (108, 109)):
        f[first] = f[second] = 1
    f[12] = f[13] = generation
    return f


def frames(route, scenario):
    result = {}
    for label, kind in labels(route, scenario).items():
        receipt = int(label in ('receipt-consumed-native', 'new-runtime-closed'))
        if kind == 'native': result[label] = native(receipt)
        elif kind == 'kotlin': result[label] = kotlin(receipt, 2 if label == 'new-runtime-closed' else 1)
        elif kind == 'facade':
            f = [0] * 15; f[0] = 1; f[8] = 1
            if label == 'receipt-window-js': f[5] = f[7] = 1
            elif label in ('receipt-unconsumed-js', 'failure-late-js'): f[10] = 1
            else: f[9] = 1
            result[label] = f
        elif kind == 'settling':
            f = [0] * 9; f[8] = int(label == 'receipt-window-js'); result[label] = f
        elif kind == 'admission':
            f = [0] * 13; f[5] = 1; f[6] = 5; f[7] = 1; f[10] = 1
            if label == 'receipt-consumed-admission': f[6] = 0; f[11] = 1
            if label == 'new-runtime-admission': f[6] = 0; f[7] = 2; f[11] = 1
            result[label] = f
        elif kind == 'text':
            if 'reopen' in label: value = 'AlreadyInitialized' if route == 'kotlin' else 'RuntimeAlreadyOpen'
            elif label in ('registration-late', 'receipt-window-reregister-rejected'): value = 'Closing'
            elif label == 'registration-closed': value = 'Closed'
            elif label == 'close-rejected' and scenario == 'callback-throws': value = 'InjectedReceiptProbe'
            elif label == 'close-rejected' and scenario == 'callback-code-getter': value = 'InjectedReceiptGetter'
            elif label == 'close-rejected' and scenario in ('callback-throw-undefined', 'callback-throw-proxy'): value = 'CallbackFailure'
            else: value = 'InvalidArgument'
            result[label] = value
        else:
            result[label] = {'receipt-window-reentry': [0, 0, 1], 'receipt-window-probe-returned': [1],
                             'callback-fault-entered': [1], 'original-close-outcome': [1, 0, 1] if scenario == 'normal' else [0, 1, 1],
                             'new-runtime-result': [42], 'failure-repeat-close': [1, 1, 0],
                             'failure-late-outcome': [0, 1, 1],
                             'callback-property-reads': [0, 0, int(scenario == 'callback-throw-proxy')]}[label]
    return result


def log(values):
    def entry(message): return '10-26 12:00:00.000 123 123 I A00000/MadBC07Probe: ' + message
    rows = [entry(marker + ' receipt-test') for marker in ('PROBE_STARTED', 'PROBE_PAGE_READY', 'PROBE_FINISHED')]
    rows += [entry('C09_RECEIPT_FRAME receipt-test ' + key + ' ' + json.dumps(value)) for key, value in values.items()]
    rows += [entry('C09_RECEIPT_COMPLETE receipt-test')]
    return '\n'.join(rows)


class ReceiptOracleTests(unittest.TestCase):
    def parse(self, values, route='c', scenario='normal'):
        return parse_observation(log(values), nonce='receipt-test', pid='123', route=route, scenario=scenario)

    def test_all_routes_and_modes_have_explicit_positive_oracles(self):
        for route in ('c', 'cpp', 'rust', 'kotlin'):
            for scenario in SCENARIOS:
                with self.subTest(route=route, scenario=scenario):
                    result = self.parse(frames(route, scenario), route, scenario)
                    self.assertEqual(result['problems'], [])
                    self.assertEqual(result['status'], 'passed')
                    self.assertEqual(result['normal_close'], 'passed' if scenario == 'normal' else 'not_proved')

    def test_receipt_consumed_or_physical_owner_live_at_window_rejected(self):
        for route, indices in (('c', (32, 14, 20, 25, 35)), ('kotlin', (2, 26, 39, 47, 99))):
            for index in indices:
                values = frames(route, 'normal'); values['receipt-window-native'][index] = 1
                with self.subTest(route=route, index=index): self.assertEqual(self.parse(values, route)['status'], 'failed')

    def test_unpaired_allocations_and_unjoined_worker_rejected(self):
        for route, index in (('c', 34), ('c', 17), ('c', 69), ('kotlin', 13), ('kotlin', 109)):
            values = frames(route, 'normal'); values['receipt-window-native'][index] = 0
            with self.subTest(route=route, index=index): self.assertEqual(self.parse(values, route)['status'], 'failed')

    def test_window_must_be_inside_original_close_tick(self):
        for route, index in (('c', 7), ('c', 5), ('kotlin', 8)):
            values = frames(route, 'normal'); values['receipt-window-js'][index] = 0
            self.assertEqual(self.parse(values, route)['status'], 'failed')

    def test_typed_rejection_codes_are_not_cross_route_aliases(self):
        for route in ('c', 'kotlin'):
            values = frames(route, 'normal'); values['receipt-window-reopen-rejected'] = 'AlreadyInitialized' if route == 'c' else 'RuntimeAlreadyOpen'
            self.assertEqual(self.parse(values, route)['status'], 'failed')
        values = frames('c', 'normal'); values['registration-late'] = 'Closed'
        self.assertEqual(self.parse(values)['status'], 'failed')

    def test_failure_never_supplies_successful_close_or_consumed_receipt(self):
        for scenario in SCENARIOS[1:]:
            for label, value in (('original-close-outcome', [1, 0, 1]), ('failure-repeat-close', [1, 1, 1])):
                values = frames('c', scenario); values[label] = value
                self.assertEqual(self.parse(values, scenario=scenario)['status'], 'failed')
            values = frames('c', scenario); values['receipt-unconsumed-native'][32] = 1
            self.assertEqual(self.parse(values, scenario=scenario)['status'], 'failed')

    def test_getter_reads_proxy_traps_and_late_timers_are_precise(self):
        for scenario in SCENARIOS[1:]:
            for field in (0, 1):
                values = frames('c', scenario); values['callback-property-reads'][field] = 1
                self.assertEqual(self.parse(values, scenario=scenario)['status'], 'failed')
            values = frames('c', scenario); values['failure-late-js'][6] = 1
            self.assertEqual(self.parse(values, scenario=scenario)['status'], 'failed')
            values = frames('c', scenario); values['failure-late-outcome'][2] = 2
            self.assertEqual(self.parse(values, scenario=scenario)['status'], 'failed')
        for count in (0, 2):
            values = frames('c', 'callback-throw-proxy'); values['callback-property-reads'][2] = count
            self.assertEqual(self.parse(values, scenario='callback-throw-proxy')['status'], 'failed')

    def test_kotlin_slot_and_epoch_must_survive_until_receipt(self):
        for label, index in (('receipt-window-admission', 6), ('receipt-window-admission', 7), ('new-runtime-admission', 7)):
            values = frames('kotlin', 'normal'); values[label][index] = 0
            self.assertEqual(self.parse(values, 'kotlin')['status'], 'failed')

    def test_missing_duplicated_reordered_and_malformed_evidence_rejected(self):
        values = frames('c', 'normal')
        for label in values:
            changed = copy.deepcopy(values); del changed[label]
            self.assertEqual(self.parse(changed)['status'], 'failed')
        rows = log(values).splitlines()
        for malformed in ('[true]', 'null', '{'):
            changed = rows.copy(); changed[3] = changed[3].split('first-runtime-open ')[0] + 'first-runtime-open ' + malformed
            result = parse_observation('\n'.join(changed), nonce='receipt-test', pid='123', route='c', scenario='normal')
            self.assertEqual(result['status'], 'failed')
        for raw in (log(values) + '\n' + rows[3], log(values).replace(' 123 123 ', ' 999 123 ', 1),
                    '\n'.join(rows[:3] + [rows[4], rows[3]] + rows[5:])):
            self.assertEqual(parse_observation(raw, nonce='receipt-test', pid='123', route='c', scenario='normal')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
