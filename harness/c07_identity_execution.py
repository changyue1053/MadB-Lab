"""Execute isolated normal and invalid-library public consumers, without changing HAR."""
import json
import re
import time
from c07_controlled_execution import ControlledSession
from c07_contract import SOURCE
from c07_execution import write_json, ExecutionError
from c07_identity_observations import parse_identity


class IdentitySession(ControlledSession):
    def __init__(self,args,candidate,scenario,contracts,fixture=None):
        derived=dict(candidate);derived["native_members"]=dict(candidate["native_members"])
        super().__init__(args,derived,scenario,contracts)
        self.fixture=fixture

    def prepare(self):
        super().prepare()
        target=self.root/"entry/src/main/ets"
        (target/"pages/Index.ets").write_text((SOURCE/"IdentityPage.ets.in").read_text().replace("@MADB_PUBLIC_MODULE@",json.dumps(self.candidate["module"])))
        error=self.fixture["error"] if self.fixture else "positive"
        event=self.fixture["event"] if self.fixture else 0
        (target/"IdentityConfig.ets").write_text("export const IDENTITY_CASE: string = "+json.dumps(self.scenario)+";\n"+
            "export const IDENTITY_ERROR: string = "+json.dumps(error)+";\n"+
            "export const IDENTITY_EVENT: number = "+str(event)+";\n")
        if self.fixture:
            member=self.fixture["replaced_member"]
            installed=self.root/"entry/oh_modules"/self.candidate["module"]/member.removeprefix("package/")
            if installed.read_bytes()!=self.candidate["native_members"][member]:raise ExecutionError("normal installed library changed before deliberate replacement")
            installed.write_bytes(self.fixture["library"])
            inspected=self.run("identity-fixture-readelf",[self.sdk/"openharmony/native/llvm/bin/llvm-readelf","--dynamic",installed])
            normal=json.loads((self.args.output/"native-inspection.json").read_text())
            needed=sorted(re.findall(r"\(NEEDED\).*?\[([^]]+)\]",inspected["stdout"]))
            sonames=re.findall(r"\(SONAME\).*?\[([^]]+)\]",inspected["stdout"])
            if needed!=normal["needed"][installed.name] or sonames!=[installed.name]:
                raise ExecutionError("identity fixture changes actual dependency closure or SONAME")
            # The sole native exception is explicit; Session.build still compares every HAP native member.
            self.candidate["native_members"][member]=self.fixture["library"]
            for name,data in self.candidate["har_members"].items():
                if name==member or name.endswith("/"):continue
                path=self.root/"entry/oh_modules"/self.candidate["module"]/name.removeprefix("package/")
                if path.read_bytes()!=data:raise ExecutionError("normal HAR consumer file changed during fixture replacement: "+name)
            write_json(self.args.output/"fixture-derivation.json",{
                "candidate_digest":self.candidate["manifest"]["candidate_digest"],"normal_har_unchanged":True,
                "expected_identity_unchanged":self.candidate["identity"]["expected_identity"],
                "replaced_member":member,"receipt":self.fixture["receipt_ref"],"library":self.fixture["library_ref"],
                "wrong_identity":self.fixture["wrong_identity"],"scope":"deliberately invalid test input, never a candidate"})

    def parse_observation(self,raw,pid):
        return parse_identity(raw,nonce=self.nonce,pid=pid,case=self.scenario,route=self.args.route,contracts=self.contracts)
