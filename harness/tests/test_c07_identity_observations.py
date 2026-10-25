"""Negative bootstrap oracles with host log doubles, not target evidence."""
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from c07_identity_observations import parse_identity
from test_c07_companion import contracts,physical


def log(case,frames):
    lines=["PROBE_STARTED nonce","PROBE_PAGE_READY nonce","PROBE_FINISHED nonce","IDENTITY_BEGIN nonce "+case]
    lines += ["IDENTITY_FRAME nonce "+label+" "+json.dumps(value) for label,value in frames.items()]
    lines += ["IDENTITY_COMPLETE nonce "+case]
    return "\n".join("10-25 12:00:00.000 123 456 I Probe: "+line for line in lines)


class IdentityObservationTests(unittest.TestCase):
    def parse(self,case,frames,**changes):
        values=dict(raw=log(case,frames),nonce="nonce",pid="123",case=case,route="c",contracts=contracts());values.update(changes);return parse_identity(**values)
    def frames(self,event=3):
        before=[1]+[0]*15;after=list(before);after[1]=after[event]=1
        return {"before":before,"after":after,"rejected":[event]}
    def test_three_distinct_rejection_events_without_native_creation(self):
        for case,event in (("identity-wrong-abi",3),("identity-wrong-profile",4),("identity-wrong-build",5)):
            self.assertEqual(self.parse(case,self.frames(event))["status"],"passed")
    def test_loader_failure_or_zero_counter_missing_attempt_never_passes(self):
        f=self.frames();f["after"][1]=0;self.assertEqual(self.parse("identity-wrong-abi",f)["status"],"failed")
        self.assertEqual(self.parse("identity-wrong-abi",self.frames(),raw="module load failed")["status"],"incomplete")
    def test_any_resource_creation_before_identity_gate_rejected(self):
        for i in range(6,16):
            f=self.frames();f["after"][i]=1
            self.assertEqual(self.parse("identity-wrong-abi",f)["status"],"failed")
    def test_wrong_event_bad_transport_and_wrong_pid_fail(self):
        self.assertEqual(self.parse("identity-wrong-abi",self.frames(4))["status"],"failed")
        self.assertEqual(self.parse("identity-wrong-abi",self.frames(),pid="124")["status"],"failed")
        f=self.frames();f["after"][1]=True;self.assertEqual(self.parse("identity-wrong-abi",f)["status"],"failed")
    def test_positive_requires_real_created_and_finalized_owners(self):
        f={"before":[1]+[0]*15,"after":[1,1,1,0,0,0,1,1,1,1,1,1,1,1,1,1],"closed":physical()}
        self.assertEqual(self.parse("identity-positive",f)["status"],"passed")
        f["closed"][45]=0;self.assertEqual(self.parse("identity-positive",f)["status"],"failed")

if __name__=="__main__":unittest.main()
