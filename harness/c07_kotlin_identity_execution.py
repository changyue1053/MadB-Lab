"""Kotlin wrong-library sessions use public diagnostics and one actual DSO swap."""
import json,sys
from c07_contract import SOURCE
from c07_execution import Session,write_json,ref
from c07_identity_execution import IdentitySession
from c07_kotlin_identity_observations import parse

class KotlinIdentitySession(IdentitySession):
    def prepare(self):
        Session.prepare(self)
        target=self.root/'entry/src/main/ets'
        (target/'pages/Index.ets').write_text((SOURCE/'KotlinIdentityPage.ets.in').read_text().replace('@MADB_PUBLIC_MODULE@',json.dumps(self.candidate['module'])))
        (target/'IdentityConfig.ets').write_text('export const IDENTITY_CASE: string = '+json.dumps(self.scenario)+';\nexport const IDENTITY_ERROR: string = '+json.dumps(self.fixture['error'])+';\n')
        self.apply_fixture()
        # Inspect the actual selected pair. A normal candidate's previous binder
        # receipt is not copied over a deliberately different ELF artifact.
        from c07_kotlin_execution import napi_inventory_command
        libs=self.root/'entry/oh_modules'/self.candidate['module']/'libs/arm64-v8a'
        output=self.args.output/'identity-napi-inventory'
        self.run('identity-napi-inventory',napi_inventory_command(sys.executable,
            self.candidate['root']/'generated/contract/test/napi-observer-frame.json',
            libs/('lib'+self.candidate['module']+'.so'),libs/'libmadb_kotlin_owned_runtime.so',
            self.sdk/'openharmony/native/llvm/bin',output),timeout=120)
        write_json(self.args.output/'identity-napi-binding.json',{'files':[ref(p,self.args.output) for p in sorted(output.rglob('*')) if p.is_file()],
            'scope':'actual deliberately selected two-ELF observer implementation; not a normal candidate identity or runtime observation'})

    def parse_observation(self,raw,pid):
        return parse(raw,nonce=self.nonce,pid=pid,case=self.scenario,route='kotlin')
