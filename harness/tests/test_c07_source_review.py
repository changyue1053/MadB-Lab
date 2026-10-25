"""Independent small receipt fixtures: rehashed lies must not acquire review."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import file_digest
import c07_source_review as subject


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.review_path = self.root / 'review.json'
        self.patch = patch.object(subject, 'REVIEW', self.review_path); self.patch.start(); self.addCleanup(self.patch.stop)
        self.docs = {}; self.files = {}; self.inventory = {}
        self.candidate = {'route': 'c', 'companion': True, 'module': 'module', 'profile': {'id': 'c07-c-arkts-aarch64-ohos23-test'},
                          'provenance': {'producer_revision': 'reviewed-revision'},
                          'identity': {k: 'sha256:' + c * 64 for k, c in [('abi_digest','a'),('profile_digest','b'),('build_id','c')]}}
        self.candidate['identity']['expected_identity'] = 'madb-arkts/1:' + ':'.join(c * 64 for c in 'abc')
        def ref(name): return {'path': name, 'sha256': file_digest(name.encode()), 'size': len(name)}
        self.original = 'sdk/c/arkts-provider/src/provider.c'
        self.provider = 'derived/native/provider/provider.c'
        self.protocol = 'derived/native/runtime/protocol.cpp'
        originals = [self.original, 'sdk/arkts/native-runtime/src/protocol.cpp', 'sdk/arkts/test-support/native/memory-provider-c.patch', 'sdk/arkts/test-support/native/memory-provider-c-baseline.json', 'sdk/arkts/native-runtime/include/provider_abi.h']
        derived = [self.provider, self.protocol]
        self.locked = {n: ref(n) for n in originals + derived}
        self.record = {'route':'c','variant':'test','original_inputs':originals,'derived_inputs':derived,'generated_inputs':[],
                       'references':[self.locked[n] for n in derived], 'methods': [],
                       'units':[{'name':n,'source':s,'language':lang,'required_dependencies':[s]} for n,s,lang in [('protocol',self.protocol,'cpp'),('provider',self.provider,'c')]],
                       'derivations':[{'original': self.original, 'patch':originals[2], 'baseline':originals[3], 'result':self.provider,
                                       'base_sha256':self.locked[self.original]['sha256'], 'result_sha256':self.locked[self.provider]['sha256']}]}
        self.review = {'status':'reviewed', 'producer_revision':'reviewed-revision', 'source_files':[self.locked[n] for n in originals], 'records':[self.record], 'review_notes':'finite fixture only', 'replay_scope':'No original source bytes; no independent replay.'}
        self.docs['generated/contract/composition.json'] = {'route':'c','variant':'test','original_inputs':[self.locked[n] for n in originals], 'derived_inputs':[self.locked[n] for n in derived]}
        self.review = deepcopy(self.review)
        self.rows=[]
        self.objects={}
        for unit in self.record['units']:
            n,s,lang=unit['name'],unit['source'],unit['language']; work='/node/work/'; inputs='/node/inputs/'
            args=['clang' if lang=='c' else 'clang++','--target=aarch64-linux-ohos23.0.0','--sysroot=/sdk/sysroot','-O2','-fPIC','-fvisibility=hidden','-g','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-Werror=date-time','-ffile-prefix-map=/node/inputs=/madb/inputs','-ffile-prefix-map=/node/work=/madb/work','-fdebug-compilation-dir=/madb/work','-std='+('c17' if lang=='c' else 'c++17')]
            if lang=='cpp':args+=['-fvisibility-inlines-hidden']
            for p in ['derived/native/include','sdk/arkts/native-runtime/include','generated/native']:args+=['-I',inputs+p]
            args+=['-MD','-MT','madb-object','-MF',work+'logs/'+n+'.d','-c',inputs+s,'-o',work+'objects/'+n+'.o']
            self.rows += [{'tool':'clang' if lang=='c' else 'clangxx','arguments':args},{'kind':'actual-compiler-dependencies','unit':n,'dependencies':[dict(self.locked[s],origin='frozen-input')]}]
            self.objects['objects/'+n+'.o']=ref('objects/'+n+'.o')
        self.links=[{'arguments':['clang++','-shared',*[ '/link/inputs/'+n for n in self.objects]]}]
        i=self.candidate['identity']; constants={'GatewayAbi':i['abi_digest'][7:],'GatewayProfile':i['profile_digest'][7:],'GatewayBuild':i['build_id'][7:],'GatewayIdentity':i['expected_identity'],'GatewayRouteIdentity':'c/'+i['expected_identity'],'GatewayModuleName':'module'}
        self.files['generated/native/identity.generated.hpp']=('#pragma once\n#include "provider_abi.h"\n#include "memory_hook.h"\nnamespace gateway {\n'+''.join('inline constexpr const char* '+k+'='+json.dumps(v)+';\n' for k,v in constants.items())+'inline constexpr auto GatewayProviderCreate = ::mp_c_create;\ninline constexpr auto GatewayProviderMemoryBind = ::mp_c_test_memory_bind;\n}\n').encode()

    def verify(self):
        self.review_path.write_text(json.dumps(self.review))
        return subject.verify_source_review(self.candidate, {'inputs':list(self.locked.values())},self.rows,self.links,self.objects,self.inventory,self.files.__getitem__,self.docs.__getitem__,lambda command,tool: None)

    def blocked(self):
        result=self.verify();self.assertEqual(result['status'],'blocked',result)
        return result['reason']

    def test_reviewed_original_derived_actual_compile_object_link_closure(self):
        result=self.verify(); self.assertEqual(result['status'],'bound',result)
        self.assertFalse(result['independent_patch_replay']);self.assertEqual(len(result['units']),2)
        self.assertEqual(result['derivations'][0]['original'],self.original)

    def test_archive_member_arguments_are_not_mistaken_for_compiler_outputs(self):
        self.rows.append({'tool':'ar','arguments':['ar','crsD','/node/work/objects/lib.a','/node/work/objects/provider.o','/node/work/objects/protocol.o']})
        self.assertEqual(self.verify()['status'],'bound')

    def test_pending_or_other_revision_does_not_acquire_review(self):
        self.review['status']='pending-independent-review';self.blocked()
        self.review['status']='reviewed';self.candidate['provenance']['producer_revision']='other';self.blocked()

    def test_rehashed_original_patch_or_derived_receipt_cannot_change_review(self):
        for name in [self.original,self.record['derivations'][0]['patch'],self.provider]:
            with self.subTest(name=name):
                before=deepcopy(self.locked[name]);self.locked[name]['sha256']='sha256:'+'f'*64
                self.assertIn('changed frozen source',self.blocked());self.locked[name]=before

    def test_compilation_must_use_derived_source_not_ordinary_copy(self):
        args=self.rows[2]['arguments'];args[args.index('-c')+1]='/node/inputs/'+self.original
        self.assertIn('actual source/output',self.blocked())

    def test_actual_dependency_cannot_be_relabelled_or_omitted(self):
        deps=self.rows[3]['dependencies'];deps[0]['sha256']='sha256:'+'f'*64
        self.assertIn('dependency differs',self.blocked());deps.clear()
        self.assertIn('required dependency',self.blocked())

    def test_unknown_compiler_include_or_macro_cannot_change_semantics(self):
        self.rows[2]['arguments'].insert(1,'-Dfree=ignored')
        self.assertIn('compiler flags',self.blocked())

    def test_unknown_dependency_despite_matching_lock_is_blocked(self):
        unknown={'path':'sdk/extra.h','sha256':'sha256:'+'f'*64,'size':1};self.locked[unknown['path']]=unknown
        self.rows[3]['dependencies'].append(dict(unknown,origin='frozen-input'))
        self.assertIn('unreviewed compiler dependency',self.blocked())

    def test_missing_core_object_duplicate_unit_or_wrong_link_is_blocked(self):
        before=deepcopy(self.objects);del self.objects['objects/protocol.o'];self.blocked();self.objects=before
        self.rows.append(deepcopy(self.rows[2]));self.blocked();self.rows.pop()
        self.links[0]['arguments'].pop();self.blocked()

    def test_injected_factory_header_content_is_blocked(self):
        self.files['generated/native/identity.generated.hpp']+=b'void unreviewed() {}\n'
        self.assertIn('factory header',self.blocked())

    def test_composition_cannot_discard_original_or_substitute_patch(self):
        self.docs['generated/contract/composition.json']['original_inputs'].pop(0)
        self.assertIn('composition closure',self.blocked())


class RustSourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.authors=['sdk/rust/arkts-bridge/'+n for n in ['Cargo.toml','Cargo.lock','build.rs','frontend-features.json','src/lib.rs']]
        self.authors+=['sdk/rust/arkts-provider/src/lib.rs']
        self.locked={n:{'path':n,'sha256':file_digest(n.encode()),'size':len(n)} for n in self.authors}
        self.record={'original_inputs':self.authors,'variant':'test','methods':[['sample',1]],'units':[{'name':'runtime-ffi'}]}
        self.digest='sha256:'+'b'*64
        self.candidate={'toolchain':{'rust':{'test_support':True},'tools':[{'id':'c07-rustc','sha256':self.digest}]}}
        self.upstream=[{'path':'fixed-upstream.rs','sha256':self.digest,'size':1}]
        macro={'descriptor':{'exports':[{'name':'sample','arity':1,'rawReturn':'unknown','parameters':[{'rawType':'unknown'}]}]}}
        frontend={'upstream_sources':deepcopy(self.upstream),'expanded_rust':'borrowed synchronous raw callback'}
        self.declaration={'inputs':list(self.locked.values()),'test_support':True,'typed_api_inferred':False,'macro':macro,'frontend_evidence':frontend,'tools':{'rustc':{'sha256':self.digest}},'resolved_packages':[{'name':'madb-arkts-bridge','features':['default','test-support']},{'name':'napi-ohos','features':['napi1','napi2','napi3']},{'name':'napi-sys-ohos','features':['napi'+str(n) for n in range(1,9)]}]}
        self.docs={'declarations.json':{'rust':self.declaration},'rust-link.json':{'actual_macro':deepcopy(macro),'source_archive_sha256':self.digest},'rust-symbols.json':{'frontend':{'macro':deepcopy(frontend)}}}
        self.rows=[{'tool':'ar','arguments':['ar','crsD','/build/work/objects/libmadb_arkts_gateway.a','/build/work/objects/runtime-ffi.o']},{'tool':'cargo','arguments':['cargo','check','--features','test-support'],'environment':{'MADB_BUILD_PHASE':'metadata'}}]
        self.links=[{'tool':'ohrs','arguments':['ohrs','build','--features','test-support'],'explicit_environment':{'MADB_BUILD_PHASE':'native','CARGO_RUSTFLAGS':'-Clink-arg=--target=aarch64-linux-ohos23.0.0\x1f-Clink-arg=-Wl,--build-id=sha1\x1f--remap-path-prefix=/project=/madb/rust'}}]
        self.objects={'objects/libmadb_arkts_gateway.a':{'sha256':self.digest}}

    def verify(self):
        return subject._rust(self.record,self.candidate,self.locked,self.rows,self.links,self.objects,self.docs.__getitem__,lambda c,t:None,self.upstream)

    def test_frontend_cfg_macro_and_source_are_separate_receipts(self):
        self.assertEqual(self.verify()['macro_exports'],1)
        self.assertIn('no Rust source depfile',self.verify()['scope'])

    def test_missing_test_feature_or_macro_substitution_rejected(self):
        from candidate import CandidateError
        self.rows[1]['arguments']=['cargo','check']
        with self.assertRaises(CandidateError):self.verify()
        self.rows[1]['arguments']=['cargo','check','--features','test-support']
        self.docs['rust-link.json']['actual_macro']['descriptor']['exports'][0]['name']='substituted'
        with self.assertRaises(CandidateError):self.verify()

    def test_rust_source_or_upstream_or_archive_mismatch_rejected(self):
        from candidate import CandidateError
        original=deepcopy(self.docs)
        self.declaration['inputs'][0]=dict(self.declaration['inputs'][0],sha256='sha256:'+'f'*64)
        with self.assertRaises(CandidateError):self.verify()
        self.docs=deepcopy(original);self.docs['rust-symbols.json']['frontend']['macro']['upstream_sources'][0]['sha256']='sha256:'+'f'*64
        with self.assertRaises(CandidateError):self.verify()
        self.docs=deepcopy(original);self.objects['objects/libmadb_arkts_gateway.a']['sha256']='sha256:'+'f'*64
        with self.assertRaises(CandidateError):self.verify()

    def test_unreviewed_rust_cfg_environment_is_rejected(self):
        from candidate import CandidateError
        self.links[0]['explicit_environment']['CARGO_RUSTFLAGS']+='\x1f--cfg=other'
        with self.assertRaises(CandidateError):self.verify()


if __name__ == '__main__':
    unittest.main()
