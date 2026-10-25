from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""Oracle checks use hand-authored observations and adversarial mutations only."""
import copy
import unittest
from c07_kotlin_memory_observations import NAMES, parse_memory_csv, predicates


def csv(values):
    return ','.join(str(x) for x in values)


def memory(*values):
    assert len(values) == 21
    return csv([70603, *values])


def empty():
    return memory(*([0] * 21))


def control(**values):
    f = ['0'] * 31
    f[0] = '1'; f[4] = f[5] = f[8] = '1'; f[6] = '-1'
    for key, value in values.items():
        f[int(key)] = str(value)
    return ','.join(f)


def native(**values):
    f = [0] * 110; f[0] = 70501
    for key, value in values.items():
        f[int(key)] = value
    return f


def retained():
    full = memory(4096,4096,4096,0, 4096,4096,4096,0,4,0, 0,0,0,0,0, 0,2050,8200,8200,4,4)
    scratch = memory(4096,4096,4096,0, 4096,5120,5120,1024,5,1, 0,0,0,0,0, 0,2050,12300,12300,6,6)
    denied = memory(4096,4096,4096,0, 4096,5120,5120,1024,5,1, 0,0,0,0,0, 0,2050,12304,12304,7,7)
    drained = memory(0,4096,4096,4096, 0,5120,5120,5120,5,5, 0,0,0,0,0, 0,2050,12304,12304,7,7)
    return {'memory-baseline':empty(), 'memory-work-held-control':control(**{'1':1,'3':1}),
            'memory-retained-native':native(**{'12':1,'13':0,'24':4,'27':4096,'39':1}),
            'memory-retained-full':full,'memory-scratch-returned':scratch,
            'memory-retained-denied':denied,'memory-drained':drained,'memory-final':drained}


def state():
    held = memory(1024,1024,1024,0, 1024,1024,1024,0,1,0, 0,1024,1024,1024,0, 0,2050,2050,2050,1,1)
    replaced = memory(1024,2048,2048,1024, 1024,2048,2048,1024,2,1, 0,1024,2048,2048,0, 0,2050,4100,4100,2,2)
    staged = memory(2048,2048,3072,1024, 2048,2048,3072,1024,3,1, 1024,1024,3072,2048,0, 0,2050,6150,6150,3,3)
    denied = memory(2048,2048,3072,1024, 2048,2048,3072,1024,3,1, 1024,1024,3072,2048,0, 0,2050,6154,6154,4,4)
    abandoned = memory(1024,2048,3072,2048, 1024,2048,3072,2048,3,2, 0,1024,3072,2048,1024, 0,2050,6154,6154,4,4)
    commit_held = memory(2048,2048,4096,2048, 2048,2048,4096,2048,4,2, 1024,1024,4096,2048,1024, 0,2050,8204,8204,5,5)
    committed = memory(1024,2048,4096,3072, 1024,2048,4096,3072,4,3, 0,1024,4096,3072,1024, 0,2050,8204,8204,5,5)
    drained = memory(0,2048,4096,4096, 0,2048,4096,4096,4,4, 0,1024,4096,3072,1024, 0,2050,10254,10254,6,6)
    n = native(**{'29':1,'31':0,'27':1024})
    return {'memory-baseline':empty(),'memory-delivery-held-control':control(**{'7':2,'9':1}),
            'memory-state-held':held,'memory-state-held-native':n,
            'memory-state-replaced':replaced,'memory-state-replaced-native':n.copy(),
            'memory-staging-held':staged,'memory-staging-held-control':control(**{'12':1,'13':1,'14':1024}),
            'memory-staging-denied':denied,'memory-staging-abandoned':abandoned,
            'memory-staging-commit-held':commit_held,'memory-staging-committed':committed,
            'memory-release-sync':[0],'memory-state-trace':[4],
            'memory-drained':drained,'memory-final':drained}


def set_memory(frames, label, index, value):
    parts = frames[label].split(','); parts[index] = str(value); frames[label] = ','.join(parts)


class MemoryOracleTests(unittest.TestCase):
    def test_two_independent_positive_observations(self):
        self.assertEqual(predicates(NAMES[0], retained()), [])
        self.assertEqual(predicates(NAMES[1], state()), [])

    def test_counts_cannot_replace_bytes(self):
        f = retained(); set_memory(f,'memory-retained-full',1,4)
        self.assertTrue(predicates(NAMES[0],f))

    def test_peak_only_cannot_fake_real_scratch(self):
        f = retained(); f['memory-scratch-returned'] = f['memory-retained-full']
        set_memory(f,'memory-scratch-returned',6,5120)
        self.assertTrue(predicates(NAMES[0],f))

    def test_native_free_without_matching_returned_bytes_fails(self):
        f = retained(); set_memory(f,'memory-scratch-returned',8,1023)
        self.assertTrue(predicates(NAMES[0],f))

    def test_real_work_hold_required(self):
        f = retained(); f['memory-work-held-control'] = control(**{'3':1})
        self.assertTrue(predicates(NAMES[0],f))

    def test_utf16_scope_is_not_native_utf8_size(self):
        f = retained(); set_memory(f,'memory-scratch-returned',17,1024)
        self.assertTrue(predicates(NAMES[0],f))

    def test_utf16_allocation_leak_fails_final_even_if_models_freed(self):
        f = retained(); set_memory(f,'memory-final',19,12302); set_memory(f,'memory-final',16,2)
        self.assertTrue(predicates(NAMES[0],f))

    def test_preentry_delivery_must_really_be_taken(self):
        f = state(); f['memory-delivery-held-control'] = control(**{'7':1})
        self.assertTrue(predicates(NAMES[1],f))

    def test_two_state_tickets_are_not_coalescing(self):
        f = state(); f['memory-state-replaced-native'][29] = 2
        self.assertTrue(predicates(NAMES[1],f))

    def test_staging_cannot_drop_old_state_charge(self):
        f = state(); set_memory(f,'memory-staging-held',1,1024)
        self.assertTrue(predicates(NAMES[1],f))

    def test_commit_and_abandon_are_distinct_roles(self):
        f = state(); set_memory(f,'memory-staging-committed',14,2048); set_memory(f,'memory-staging-committed',15,2048)
        self.assertTrue(predicates(NAMES[1],f))

    def test_abandoned_copy_never_delivered(self):
        f = state(); f['memory-state-trace'] = [3,4]
        self.assertTrue(predicates(NAMES[1],f))

    def test_post_ack_read_cannot_reset_history(self):
        f = state(); f['memory-final'] = empty()
        self.assertTrue(predicates(NAMES[1],f))

    def test_drain_and_final_cannot_both_reset_history(self):
        f = retained(); f['memory-drained'] = empty(); f['memory-final'] = empty()
        self.assertTrue(predicates(NAMES[0],f))

    def test_missing_post_ack_read_fails(self):
        f = retained(); del f['memory-final']
        self.assertTrue(predicates(NAMES[0],f))

    def test_unknown_noncanonical_or_coerced_memory_is_not_zero(self):
        for raw in ('unavailable', [0]*22, '70603,'+','.join(['0']*20+['18446744073709551615']), '70603,00,'+','.join(['0']*20)):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError): parse_memory_csv(raw)

    def test_uint64_text_is_never_float_coerced(self):
        f = [0]*22; f[0]=70603; f[7]=9007199254740993
        self.assertEqual(parse_memory_csv(csv(f))[7],9007199254740993)

    def test_unknown_scenario_fails(self):
        self.assertTrue(predicates('other',{}))


if __name__ == '__main__':
    unittest.main()
