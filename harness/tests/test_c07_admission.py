"""Host negative controls, never substitute for actual platform admission."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from c07_admission_observations import predicates, validate_contracts
from c07_companion_observations import _predicates
from test_c07_companion import contracts, native, physical


def frames():
    before=[1]+[0]*15
    opened=[1,1,1,0,0,0,1,1,1,1,1,0,1,0,1,0]
    result={"bootstrap-before":before,"bootstrap-open":opened,
        "bootstrap-final":[1,2,2,0,0,0,2,2,2,2,2,2,2,2,2,2],
        "delivery-before-assert":[1,0,1,0,0,1,0,0], "delivery-held":[1,0,1,0,0,1,0,0],
        "core-before-assert":native(**{"7":1}),"state-replaced":native(**{"7":1}),
        "callback-count-before-assert":[0],"state-values":[2],
        "delivery-invoked":[1,0,0,0,1,1,1,0],"stop-delivery-held":[1,0,1,0,0,2,1,0],
        "stop-release-return":[1,0,1,0,1,2,1,0],"stop-preentry":[1,0],
        "after-engine-close":native(**{str(i):1 for i in (16,17,48,49,50,51,69,70)}),
        "handle-baseline":native(**{"50":2,"51":1,"69":1,"70":1}),
        "handle-rejections":[1]*5}
    result["handle-after"]=deepcopy(result["handle-baseline"])
    return result


class AdmissionTests(unittest.TestCase):
    def test_actual_lease_and_two_generation_events(self):
        self.assertEqual(predicates("delivery-and-handle-admission",frames()),[])
        self.assertEqual(validate_contracts(contracts()),[])

    def test_bootstrap_must_count_actual_events_without_wrong_rejections(self):
        for label,index in (("bootstrap-open",6),("bootstrap-open",3),("bootstrap-final",13)):
            f=frames();f[label][index]+=1
            self.assertTrue(predicates("delivery-and-handle-admission",f))

    def test_pending_or_entered_is_not_taken_preentry_lease(self):
        for label,index,value in (("delivery-held",2,0),("delivery-held",3,1),("state-replaced",7,2),("state-replaced",9,1)):
            f=frames();f[label][index]=value
            self.assertTrue(predicates("delivery-and-handle-admission",f))

    def test_stop_cannot_invoke_listener_or_skip_engine_join(self):
        for label,index,value in (("stop-preentry",1,1),("after-engine-close",17,0),("after-engine-close",18,1)):
            f=frames();f[label][index]=value
            self.assertTrue(predicates("delivery-and-handle-admission",f))

    def test_handle_rejection_cannot_admit_provider_or_core_work(self):
        for index in (*range(4,15),33,36):
            f=frames();f["handle-after"][index]+=1
            self.assertTrue(predicates("delivery-and-handle-admission",f))

    def test_changed_or_absent_contract_rejected(self):
        self.assertTrue(validate_contracts({}))
        c=contracts();c["ports-layout.json"]["delivery"]["fields"]["2"]="FakeHeld"
        self.assertTrue(validate_contracts(c))

    def test_one_generation_final_receipt_cannot_satisfy_two(self):
        f=frames();f.update({"physical-closed":physical(),"facade-closed":[1,0,0,0,0,0,0,0,1,1,0,0,0,0,0]})
        self.assertTrue(_predicates("delivery-and-handle-admission",f))
        f["physical-closed"][65:71]=[2]*6
        self.assertEqual(_predicates("delivery-and-handle-admission",f),[])

if __name__=="__main__": unittest.main()
