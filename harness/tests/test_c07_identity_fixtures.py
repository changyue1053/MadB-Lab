"""Mutated public fixture receipts and artificial ELF bytes; host-only admission tests."""
from pathlib import Path
import hashlib,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from candidate import CandidateError
from c07_identity_fixtures import admit_identity_fixtures, EXPECTED, HEADER, FACADE


def ref(path,name=None):
    data=path.read_bytes();return {"path":name or str(path),"sha256":"sha256:"+hashlib.sha256(data).hexdigest(),"size":len(data)}
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def setup(root):
    normal=root/"normal";normal.mkdir();components=["a"*64,"b"*64,"c"*64];expected="madb-arkts/1:"+":".join(components)
    header="".join('inline constexpr const char* '+name+' = "'+value+'";\n' for name,value in
        zip(("GatewayAbi","GatewayProfile","GatewayBuild","GatewayIdentity","GatewayRouteIdentity"),components+[expected,"c/"+expected]))
    (normal/HEADER).parent.mkdir(parents=True);(normal/HEADER).write_text(header)
    (normal/FACADE).parent.mkdir(parents=True);(normal/FACADE).write_text('const EXPECTED_IDENTITY: string = "'+expected+'";')
    source={"path":"source.c","sha256":"sha256:"+"d"*64,"size":1}
    write(normal/"madb.lock",{"inputs":[source]})
    inventory=[ref(normal/name,name) for name in (HEADER,FACADE,"madb.lock")]
    selector={"profile_id":"c07-c-arkts-aarch64-ohos23-test"}
    candidate={"root":normal,"route":"c","module":"madbc07sdkctest","identity":{"expected_identity":expected},
        "manifest":{"generation_id":"generation","selector":selector,"files":inventory,"dependencies":[],"build_evidence":[]}}
    base=root/"fixtures";base.mkdir();references=[]
    for kind,(constant,error,event,index) in EXPECTED.items():
        folder=base/kind;folder.mkdir();parts=list(components);parts[index]="f"*64;wrong="madb-arkts/1:"+":".join(parts)
        edits=[{"constant":constant,"before":components[index],"after":parts[index]},
            {"constant":"GatewayIdentity","before":expected,"after":wrong},
            {"constant":"GatewayRouteIdentity","before":"c/"+expected,"after":"c/"+wrong}]
        changed=header
        for e in edits:changed=changed.replace(e["constant"]+' = "'+e["before"]+'";',e["constant"]+' = "'+e["after"]+'";')
        edited=folder/"header.hpp";edited.write_text(changed)
        elf=bytearray(64);elf[:6]=b"\x7fELF\x02\x01";elf[18:20]=(183).to_bytes(2,"little")
        lib=folder/"libmadbc07sdkctest.so";lib.write_bytes(bytes(elf)+wrong.encode()+b"\x00c/"+wrong.encode()+b"\x00")
        logs=[]
        for phase in ("compile","link"):
            log=folder/(phase+".json");write(log,[]);logs.append({"phase":phase,"log":ref(log),"outputs":[]})
        logs[1]["outputs"]=[ref(lib,"native/libmadbc07sdkctest.so")]
        original=[source,ref(normal/HEADER,HEADER),ref(normal/FACADE,FACADE)]
        fixture=[source,ref(edited,HEADER),ref(normal/FACADE,FACADE)]
        receipt={"case":kind,"candidate":False,"build_status":"compiled-and-linked","generation_id":"generation","selector":selector,
            "native_module":lib.name,"changed_files":[HEADER],"unchanged_facade":ref(normal/FACADE,FACADE),
            "original_inputs":original,"fixture_inputs":fixture,"native_constant_edits":edits,"library":ref(lib),"phases":logs}
        dest=folder/"receipt.json";write(dest,receipt);references.append(ref(dest))
    collection=base/"fixtures.json";write(collection,{"candidate":False,"fixtures":references})
    return candidate,collection


def repin(collection):
    d=json.loads(collection.read_text());d["fixtures"]=[ref(Path(r["path"])) for r in d["fixtures"]];write(collection,d)


class IdentityFixtureTests(unittest.TestCase):
    def test_exact_public_transform_and_native_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,p=setup(Path(tmp));fixtures,used=admit_identity_fixtures(p,ref(p)["sha256"],c)
            self.assertEqual(set(fixtures),set(EXPECTED));self.assertEqual(len(used),13)
            self.assertEqual(fixtures["wrong-abi"]["error"],"AbiMismatch")

    def test_rehashed_receipts_cannot_change_candidate_or_admit_other_edits(self):
        mutations=[lambda d:d.update(generation_id="other"),lambda d:d["selector"].update(profile_id="ordinary"),
            lambda d:d["unchanged_facade"].update(sha256="sha256:"+"0"*64),
            lambda d:d["original_inputs"][0].update(sha256="sha256:"+"0"*64),
            lambda d:d["changed_files"].append("source.c"),
            lambda d:d["native_constant_edits"][1].update(after="madb-arkts/1:"+":".join(["0"*64]*3)),
            lambda d:d["fixture_inputs"][0].update(size=2)]
        for mutate in mutations:
            with self.subTest(mutate=mutate),tempfile.TemporaryDirectory() as tmp:
                c,p=setup(Path(tmp));r=p.parent/"wrong-abi/receipt.json";d=json.loads(r.read_text());mutate(d);write(r,d);repin(p)
                with self.assertRaises(CandidateError):admit_identity_fixtures(p,ref(p)["sha256"],c)

    def test_rehashed_wrong_route_extra_identity_or_wrong_arch_is_rejected(self):
        for mutation in (lambda b:b.replace(b"c/madb-",b"rust/madb-"),lambda b:b+b"madb-arkts/1:"+b"0"*64+b":"+b"1"*64+b":"+b"2"*64+b"\x00",lambda b:b[:18]+b"\x3e\x00"+b[20:]):
            with tempfile.TemporaryDirectory() as tmp:
                c,p=setup(Path(tmp));r=p.parent/"wrong-abi/receipt.json";d=json.loads(r.read_text());lib=Path(d["library"]["path"]);lib.write_bytes(mutation(lib.read_bytes()));d["library"]=ref(lib);d["phases"][1]["outputs"]=[ref(lib,"native/"+lib.name)];write(r,d);repin(p)
                with self.assertRaises(CandidateError):admit_identity_fixtures(p,ref(p)["sha256"],c)

    def test_pin_duplicate_or_escaping_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,p=setup(Path(tmp))
            with self.assertRaises(CandidateError):admit_identity_fixtures(p,"sha256:"+"0"*64,c)
            d=json.loads(p.read_text());d["fixtures"][2]=d["fixtures"][0];write(p,d)
            with self.assertRaises(CandidateError):admit_identity_fixtures(p,ref(p)["sha256"],c)

if __name__=="__main__":unittest.main()
