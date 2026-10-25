"""Independent Kotlin transport/control-identity negative controls."""
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from c07_kotlin_observations import NATIVE_FIELDS,CONTROL_FIELDS,ADMISSION_FIELDS,parse_control_csv,parse_kotlin,validate_kotlin_contracts
from test_c07_kotlin_admission import closed_frames


def contracts():
    return {"admission-frame.json":{"length":13,"fields":[{"index":i,"name":v} for i,v in enumerate(ADMISSION_FIELDS)]},"kotlin-frame-layout.json":{"format":70501,"length":110,"fields":[{"index":i,"name":v} for i,v in enumerate(NATIVE_FIELDS)]},
        "kotlin-controls-layout.json":{"frame":{"fields":[{"index":i,"name":v} for i,v in enumerate(CONTROL_FIELDS)]}}}

def control():
    values=["0"]*31;values[0]="1";values[6]="-1";return values

def log(frames):
    lines=["PROBE_STARTED nonce","PROBE_PAGE_READY nonce","PROBE_FINISHED nonce","KOTLIN_BEGIN nonce kotlin-admission"]
    lines += ["KOTLIN_FRAME nonce "+label+" "+json.dumps(value) for label,value in frames.items()]
    lines += ["KOTLIN_COMPLETE nonce kotlin-admission"]
    return "\n".join("10-25 12:00:00.000 123 456 I Probe: "+line for line in lines)


class KotlinTransportTests(unittest.TestCase):
    def parse(self,frames=None,**changes):
        values=dict(raw=log(closed_frames() if frames is None else frames),nonce="nonce",pid="123",case="kotlin-admission",contracts=contracts());values.update(changes);return parse_kotlin(**values)
    def test_exact_admission_transport(self):
        self.assertEqual(self.parse()["status"],"passed")
    def test_no_c_layout_coercion(self):
        f=closed_frames();f["epoch1-closed"]=[1]*178
        self.assertEqual(self.parse(f)["status"],"failed")
        self.assertTrue(validate_kotlin_contracts({"kotlin-frame-layout.json":{"format":1,"length":178,"fields":[]}}))
    def test_decimal_identity_is_never_rounded(self):
        f=control();f[4]="9007199254740993";f[5]="18446744073709551615"
        actual=parse_control_csv(",".join(f));self.assertEqual(actual[4],f[4]);self.assertEqual(actual[5],f[5]);self.assertIsInstance(actual[0],int)
    def test_noncanonical_or_overflow_control_values_fail(self):
        for index,value in ((4,"18446744073709551616"),(4,"01"),(5,"-1"),(9,"9007199254740993"),(7,"4"),(6,"7"),(3,"3"),(0,"2")):
            f=control();f[index]=value
            with self.subTest(index=index,value=value),self.assertRaises(ValueError):parse_control_csv(",".join(f))
        with self.assertRaises(ValueError):parse_control_csv([0]*31)
    def test_required_observation_and_current_pid(self):
        f=closed_frames();del f["epoch2-local-id1"]
        self.assertEqual(self.parse(f)["status"],"failed");self.assertEqual(self.parse(pid="124")["status"],"failed")
    def test_duplicate_unknown_and_failure_cannot_pass(self):
        raw=log(closed_frames());extra="\n10-25 12:00:00.000 123 456 I Probe: "
        for tail in ("KOTLIN_FRAME nonce admission-complete [1]","KOTLIN_FRAME nonce invented [1]","PROBE_FAILED nonce assertion"):
            self.assertEqual(self.parse(raw=raw+extra+tail)["status"],"failed")
    def test_missing_end_or_prior_nonce_never_pass(self):
        self.assertEqual(self.parse(raw=log(closed_frames()).replace("KOTLIN_COMPLETE nonce kotlin-admission",""))["status"],"incomplete")
        self.assertEqual(self.parse(raw=log(closed_frames()).replace("nonce","nonce-old"))["status"],"incomplete")

if __name__=="__main__":unittest.main()
