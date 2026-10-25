"""Negative checks for semantic observations, independent of producer code."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c07_completion_observations import predicates

class CompletionAssertions(unittest.TestCase):
    def test_getter_error_and_setter_positive_control_are_required(self):
        f = {'getter-report': [16,1,1,2,1,0,2], 'getter-before-close': [0]*178, 'getter-after-close': [0]*178}
        self.assertEqual(predicates('getters-observed', f), [])
        f['getter-report'][4] = 0
        self.assertTrue(predicates('getters-observed', f))
    def test_closing_getter_cannot_allocate(self):
        f = {'getter-report': [16,1,1,2,1,0,2], 'getter-before-close': [0]*178, 'getter-after-close': [0]*178}
        f['getter-after-close'][33] = 1
        self.assertTrue(predicates('getters-observed', f))
    def test_terminal_race_accepts_both_real_winners_but_no_duplicate(self):
        for winner, counts in ((1,[1,1,0]), (3,[3,0,1])):
            f = {'race-terminal':[1,winner,0,0,0,0,0,0,0,0], 'race-settlements':counts}
            self.assertEqual(predicates('cancel-terminal-race',f), [])
            f['race-settlements'] = [winner,1,1]
            self.assertTrue(predicates('cancel-terminal-race',f))
    def test_rejected_observer_must_request_distinct_close(self):
        f = {'distinct-before-close':[1,0,0]+[0]*7, 'distinct-after-denial':[1,3]+[0]*8, 'distinct-close-budget':[0]*178}
        f['distinct-close-budget'][11] = f['distinct-close-budget'][19] = 32
        self.assertEqual(predicates('distinct-operation-denied',f), [])
        f['distinct-after-denial'][1] = 0
        self.assertTrue(predicates('distinct-operation-denied',f))
    def test_request_only_must_exceed_capacity_and_release_refs(self):
        f = {'request-only-counts':[16,1], 'request-only-after':[0]*178, 'request-only-facade':[0]*15}
        self.assertEqual(predicates('request-only-observed',f), [])
        f['request-only-after'][29] = 1
        self.assertTrue(predicates('request-only-observed',f))
    def test_entered_listener_must_survive_stop_and_then_retire(self):
        f = {label:[0]*178 for label in ('listener-entered','listener-stopped-entered','listener-stopped','listener-all-closed')}
        f.update({'listener-entered-facade':[0]*15,'listener-stopped-facade':[0]*15,'listener-values':[1,2,1,2],'listener-failure-values':[1,4,3,4]})
        for label in ('listener-entered','listener-stopped-entered'):
            f[label][5],f[label][9]=2,1
        f['listener-entered-facade'][3]=2
        f['listener-stopped'][5]=f['listener-stopped'][29]=f['listener-stopped-facade'][3]=1
        self.assertEqual(predicates('listener-stop-throw',f), [])
        f['listener-stopped-entered'][9]=0
        self.assertTrue(predicates('listener-stop-throw',f))
