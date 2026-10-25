from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
from c07_identity_execution import IdentitySession
from c07_ordinary_identity_execution import OrdinaryIdentitySession
from c07_execution import Session,ExecutionError

class IdentitySubstitutionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.output=Path(self.temp.name)
  self.child=object.__new__(IdentitySession);self.child.root=self.output/'consumer';self.child.args=SimpleNamespace(output=self.output);self.child.sdk=self.output/'sdk'
  self.member='package/libs/arm64-v8a/libm.so'
  self.child.candidate={'module':'m','manifest':{'candidate_digest':'digest'},'identity':{'expected_identity':'expected'},'native_members':{self.member:b'normal'},'har_members':{self.member:b'normal','package/Index.d.ets':b'public'}}
  self.child.fixture={'replaced_member':self.member,'library':b'negative','receipt_ref':{},'library_ref':{},'wrong_identity':'wrong'}
  for name,data in self.child.candidate['har_members'].items():
   p=self.child.root/'entry/oh_modules/m'/name.removeprefix('package/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  (self.output/'native-inspection.json').write_text(json.dumps({'needed':{'libm.so':['libc.so']}}))
  self.dynamic='(NEEDED) [libc.so]\n(SONAME) [libm.so]\n'
  self.child.run=lambda *a,**k:{'stdout':self.dynamic}
 def test_only_one_library_changes(self):
  self.child.apply_fixture();self.assertEqual(self.child.candidate['native_members'][self.member],b'negative')
  self.assertEqual((self.child.root/'entry/oh_modules/m/Index.d.ets').read_bytes(),b'public')
  self.assertTrue((self.output/'fixture-derivation.json').is_file())
 def test_changed_public_member_or_dependency_is_rejected(self):
  (self.child.root/'entry/oh_modules/m/Index.d.ets').write_bytes(b'changed')
  with self.assertRaises(ExecutionError):self.child.apply_fixture()
 def test_original_bytes_required_before_substitution(self):
  (self.child.root/'entry/oh_modules/m/libs/arm64-v8a/libm.so').write_bytes(b'other')
  with self.assertRaises(ExecutionError):self.child.apply_fixture()
 def test_wrong_soname_or_extra_dependency_rejected(self):
  for output in ['(NEEDED) [libc.so]\n(SONAME) [other.so]', '(NEEDED) [libc.so]\n(NEEDED) [new.so]\n(SONAME) [libm.so]']:
   self.dynamic=output
   (self.child.root/'entry/oh_modules/m/libs/arm64-v8a/libm.so').write_bytes(b'normal')
   with self.assertRaises(ExecutionError):self.child.apply_fixture()
 def test_ordinary_prepare_uses_only_normal_source_set(self):
  child=object.__new__(OrdinaryIdentitySession);child.root=self.output/'ordinary';child.candidate={'module':'m'};child.scenario='ordinary-identity-wrong-abi';child.fixture={'error':'AbiMismatch'}
  (child.root/'entry/src/main/ets/pages').mkdir(parents=True)
  with patch.object(Session,'prepare') as ordinary,patch.object(IdentitySession,'apply_fixture') as substitution:
   child.prepare();ordinary.assert_called_once();substitution.assert_called_once()
  source=(child.root/'entry/src/main/ets/pages/Index.ets').read_text()
  self.assertNotIn('testBootstrapTotals',source);self.assertIn('openRuntime',source)
if __name__=='__main__':unittest.main()
