"""Host negative controls for candidate inputs, watchdogs and scenario isolation."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidate import CandidateError
from c07_controlled_execution import ControlledSession, companion_contracts
from c07_execution import ExecutionError
from test_c07_companion import contracts

class ControlledExecutionTests(unittest.TestCase):
    def candidate(self, root):
        values=contracts();files=[]
        for name,value in values.items():
            name='generated/contract/frame-layout.json' if name=='runtime-frame-layout.json' else 'generated/contract/test/'+name
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value));files.append({'path':name})
        return {'root':root,'manifest':{'files':files,'dependencies':[],'build_evidence':[]}}

    def test_contracts_must_be_explicit_candidate_inputs(self):
        with tempfile.TemporaryDirectory() as name:
            c=self.candidate(Path(name));companion_contracts(c)
            c['manifest']['files'].pop()
            with self.assertRaisesRegex(CandidateError,'explicit candidate'):
                companion_contracts(c)

    def test_unknown_or_older_layout_rejected_before_device(self):
        with tempfile.TemporaryDirectory() as name:
            c=self.candidate(Path(name));p=c['root']/'generated/contract/test/test-frame-layout.json';d=json.loads(p.read_text());d['total_length']=156;p.write_text(json.dumps(d))
            with self.assertRaisesRegex(CandidateError,'layout differs'):
                companion_contracts(c)

    def bare_session(self, root):
        s=object.__new__(ControlledSession);s.args=SimpleNamespace(output=root,route='c');s.nonce='nonce';s.scenario='worker-env-exit';s.contracts=contracts();s.hap=root/'test.hap'
        return s

    def test_late_complete_cannot_pass_after_total_deadline(self):
        with tempfile.TemporaryDirectory() as name:
            s=self.bare_session(Path(name));now=[0.0];timeouts=[]
            def hdc(label,*args,**kwargs):
                if label=='probe-pid':
                    timeouts.append(kwargs['timeout']);now[0]+=30;return {'stdout':'123'}
                if label=='probe-hilog':
                    timeouts.append(kwargs['timeout']);now[0]+=30;return {'stdout':'late-complete'}
                return {'stdout':''}
            s.hdc=hdc
            with patch('c07_controlled_execution.time.monotonic',side_effect=lambda:now[0]),patch('c07_controlled_execution.parse_controlled') as parse:
                with self.assertRaisesRegex(ExecutionError,'watchdog'):
                    s.execute()
                parse.assert_not_called()
            self.assertEqual(timeouts,[20,20])

    def test_remaining_time_bounds_each_poll(self):
        with tempfile.TemporaryDirectory() as name:
            s=self.bare_session(Path(name));now=[0.0];timeouts=[]
            def hdc(label,*args,**kwargs):
                if label=='probe-pid':
                    now[0]+=47;return {'stdout':'123'}
                if label=='probe-hilog':
                    timeouts.append(kwargs['timeout']);return {'stdout':'raw'}
                return {'stdout':''}
            s.hdc=hdc
            with patch('c07_controlled_execution.time.monotonic',side_effect=lambda:now[0]),patch('c07_controlled_execution.parse_controlled',return_value={'status':'failed','problems':['real consumer failure']}):
                self.assertEqual(s.execute()['status'],'failed')
            self.assertEqual(timeouts,[3])

if __name__=='__main__':unittest.main()
