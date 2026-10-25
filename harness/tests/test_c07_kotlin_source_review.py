import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""Host counterexamples for finite review and recorded-chain checks, no target claims."""
import copy
import json
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from c07_kotlin_source_review import verify_kotlin_source_review, verify_kotlin_profile_pair

from candidate import CandidateError, file_digest
from c07_kotlin_source_review import _review_sources, _ksp, _gradle, _native_compile, _linked


def ref(path, raw=b"known"):
    return dict(path=path, sha256=file_digest(raw), size=len(raw))


def sources():
    patch = ref("reviewed/patch.diff")
    author = ref("reviewed/OwnedModel.kt")
    generated = ref("kotlin/GeneratedRecordCodec.kt", b"reviewed codec")
    candidate = dict(companion=False, profile={"id": "c07-kotlin"}, provenance={"producer_revision": "final"}, toolchain={"kotlin": {"test_support": False}})
    declaration = dict(test_support=False, source_inputs=[author, patch], frontend_policy={"finite": True}, generated=[generated])
    review = dict(schema="madb-lab.c07-kotlin-source-review/1", status="reviewed", producer_revision="final", source_files=[author, patch],
                  variants={"ordinary": dict(source_inputs=[author["path"], patch["path"]], frontend_policy=declaration["frontend_policy"], generated_files=[generated])},
                  runtime_derivation=dict(patch=patch["path"], patch_sha256=patch["sha256"][7:], base_files=[]))
    return candidate, review, declaration, {"inputs": copy.deepcopy(declaration["source_inputs"])}


def compiler():
    tools = [{"id": "c07-kotlin-" + n, "sha256": file_digest(n.encode())} for n in ("cpf_clang", "cpf_ar", "cpf_java", "gradle_cli")]
    tools.append({"id": "c07-node", "sha256": file_digest(b"node")})
    candidate = {"toolchain": {"tools": tools}}
    return candidate, {t["id"]: t["sha256"] for t in tools}


def native_rows(test=False):
    candidate, tools = compiler()
    rows = []
    for group, names, source, include in (
        ("helper", "array arraybuffer cb_info clazz exception function knapi module object property reference type".split(), "inputs/runtime/src/nativeInterop/cinterop/cpp/src", "inputs/runtime/src/nativeInterop/cinterop/cpp/include"),
        ("support", ["executor", "lifecycle", "main_gate"] + (["provider_observer"] if test else []), "native-support", "native-support")):
        objects = []
        for name in names:
            obj = "/project/native/obj/" + group + "-" + name
            objects.append(obj + ".o")
            args = ["/clang"] + (["-DMADB_KN_TEST_SUPPORT=1"] if test and group == "support" else []) + ["--target=aarch64-linux-ohos", "--sysroot=/sysroot", "-std=c++17", "-fPIC", "-O2", "-DOHOS_PLATFORM", "-D__OHOS_API__=23",
                    "-I/project/inputs/formal-api/include", "-I/project/" + include, "-MMD", "-MF", obj + ".d", "-c", "/project/" + source + "/" + name + ".cpp", "-o", obj + ".o"]
            rows.append(dict(tool="cpf_clang", tool_sha256=tools["c07-kotlin-cpf_clang"], exit_code=0, environment={}, arguments=args))
        archive = "libnapi_bridge.a" if group == "helper" else "libmadb_kn_executor.a"
        rows.append(dict(tool="cpf_ar", tool_sha256=tools["c07-kotlin-cpf_ar"], exit_code=0, environment={}, arguments=["/ar", "rcs", "/project/native/lib/" + archive, *objects]))
    for name, source in [("bootstrap", "native-bootstrap/bootstrap.cpp")] + ([("observer", "native-observer/bootstrap_observer.cpp")] if test else []):
        args = ["/clang"] + (["-DMADB_KN_TEST_SUPPORT=1"] if test else []) + ["--target=aarch64-linux-ohos", "--sysroot=/sysroot", "-std=c++17", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-D__OHOS_API__=23",
                "-I/project/inputs/formal-api/include", "-I/project/native-support", "-I/project/native-bootstrap", "-I/project/native-observer", "-MMD", "-MF", "/project/native/bootstrap/" + name + ".d", "-c", "/project/" + source, "-o", "/project/native/bootstrap/" + name + ".o"]
        rows.append(dict(tool="cpf_clang", tool_sha256=tools["c07-kotlin-cpf_clang"], exit_code=0, environment={}, arguments=args))
    return candidate, rows


class FiniteSourceReview(unittest.TestCase):
    def test_approved_finite_alignment_is_only_static(self):
        value = _review_sources(*sources())
        self.assertEqual(value["status"], "bound")
        self.assertIs(value["independent_patch_replay"], False)

    def test_pending_wrong_revision_or_cfg_cannot_pass(self):
        for mutation in (lambda c,r,d,l:r.update(status="pending-independent-review"),
                         lambda c,r,d,l:c["provenance"].update(producer_revision="other"),
                         lambda c,r,d,l:d.update(test_support=True)):
            args = sources();mutation(*args)
            with self.assertRaises(CandidateError):_review_sources(*args)

    def test_rehash_unknown_owner_or_patch_receipts_cannot_pass(self):
        for index in (0,1):
            args = sources();candidate, review, decl, lock = args
            decl["source_inputs"][index] = ref(decl["source_inputs"][index]["path"], b"substituted")
            lock["inputs"] = copy.deepcopy(decl["source_inputs"])
            with self.assertRaisesRegex(CandidateError, "unknown or changed"):_review_sources(*args)

    def test_added_or_missing_source_and_duplicate_are_rejected(self):
        for mutation in (lambda d:d["source_inputs"].append(ref("reviewed/Other.kt")), lambda d:d["source_inputs"].pop(), lambda d:d["source_inputs"].append(d["source_inputs"][0])):
            args=sources();mutation(args[2]);args[3]["inputs"]=copy.deepcopy(args[2]["source_inputs"])
            with self.assertRaises(CandidateError):_review_sources(*args)

    def test_rehashed_unreviewed_ksp_generated_code_is_rejected(self):
        args=sources();args[2]["generated"]=[ref("kotlin/GeneratedRecordCodec.kt",b"replacement")]
        with self.assertRaisesRegex(CandidateError,"KSP output differs"):_review_sources(*args)


class NativeRecordedChain(unittest.TestCase):
    def test_ordinary_and_test_have_distinct_reviewed_units(self):
        for test,count in ((False,16),(True,18)):
            candidate,rows=native_rows(test)
            self.assertEqual(_native_compile(rows,"/project",test,candidate),count)

    def test_flags_environment_or_native_tool_drift_are_rejected(self):
        for mutation in (lambda r:r[0]["arguments"].insert(1,"-DFREE_IS_NOOP"),
                         lambda r:r[0]["environment"].update(CPLUS_INCLUDE_PATH="/foreign"),
                         lambda r:r[0].update(tool_sha256=file_digest(b"foreign")),
                         lambda r:r[0].update(exit_code=1)):
            candidate,rows=native_rows();mutation(rows)
            with self.assertRaises(CandidateError):_native_compile(rows,"/project",False,candidate)

    def test_unknown_compile_unit_or_wrong_archive_member_are_rejected(self):
        for mutation in (lambda r:r.append(copy.deepcopy(r[0])), lambda r:r[12]["arguments"].pop()):
            candidate,rows=native_rows();mutation(rows)
            with self.assertRaises(CandidateError):_native_compile(rows,"/project",False,candidate)

    def test_test_support_macro_is_required_on_support_and_forbidden_on_helpers(self):
        for support in (True,False):
            candidate,rows=native_rows(True)
            row=next(r for r in rows if r["tool"]=="cpf_clang" and ("/native-support/executor.cpp" if support else "/cpp/src/array.cpp") in " ".join(r["arguments"]))
            if support:row["arguments"].remove("-DMADB_KN_TEST_SUPPORT=1")
            else:row["arguments"].insert(1,"-DMADB_KN_TEST_SUPPORT=1")
            with self.assertRaises(CandidateError):_native_compile(rows,"/project",True,candidate)

    def test_test_observer_units_cannot_be_relabelled_ordinary(self):
        candidate,rows=native_rows(True)
        with self.assertRaises(CandidateError):_native_compile(rows,"/project",False,candidate)


class ActualKspRecords(unittest.TestCase):
    def test_matching_ksp_text_facts_and_source_are_required(self):
        facts={"functions":[{"source":{"path":"reviewed/OwnedExports.kt"}}]};schema={"record":"Snapshot"}
        values={"frontend-facts.json":json.dumps(facts),"record-schema.json":json.dumps(schema),"record-export.d.ts":"export function run(): void;"}
        declaration=dict(authority="actual CPF Kotlin KSP1 and akinterop 1.1.0; managed single-record profile",typed_api_inferred=False,
                         facts=facts,record_schema=schema,declaration=values["record-export.d.ts"],source_inputs=[ref("reviewed/OwnedExports.kt")],
                         generated=[dict(ref("resources/"+n,v.encode()),text=v) for n,v in values.items()])
        documents={"generated/contract/kotlin-ksp-facts.json":facts,"generated/contract/kotlin-record-schema.json":schema}
        _ksp(declaration,documents.__getitem__)
        declaration["generated"][0]["text"]+=" "
        with self.assertRaisesRegex(CandidateError,"text/hash"):_ksp(declaration,documents.__getitem__)

    def test_gradle_task_and_tool_are_actual_and_bounded(self):
        candidate,tools=compiler();descriptor={"actual":"ksp"};declaration=dict(descriptor=descriptor,tools={n:{"sha256":tools["c07-kotlin-"+n]} for n in ("cpf_java","gradle_cli")})
        rows=[dict(tool="gradle",exit_code=0,java_sha256=tools["c07-kotlin-cpf_java"],cli_sha256=tools["c07-kotlin-gradle_cli"],
                   arguments=["/java","-Xmx64m","-Xms64m","-Dorg.gradle.appname=gradle","-javaagent:/gradle/lib/agents/gradle-instrumentation-agent-8.14.6.jar","-jar","/gradle-cli","-p","/project","--no-daemon","--console=plain","--offline",":probe:kspKotlinOhosArm64"]),
              dict(tool="node",exit_code=0,tool_sha256=tools["c07-node"],arguments=["/node","/inputs/adapters/generators/arkts/read_kotlin_exports.cjs","/typescript.js"],stdout=json.dumps(descriptor))]
        self.assertEqual(_gradle(rows,":probe:kspKotlinOhosArm64",declaration,candidate),"/project")
        for mutate in (lambda r:r[0]["arguments"].append(":other:compile"),lambda r:r[0].update(java_sha256=file_digest(b"foreign")),lambda r:r[1].update(stdout='{}')):
            bad=copy.deepcopy(rows);mutate(bad)
            with self.assertRaises(CandidateError):_gradle(bad,":probe:kspKotlinOhosArm64",declaration,candidate)


class LinkAndHarRecords(unittest.TestCase):
    def fixture(self):
        candidate, tools = compiler()
        candidate.update(module="kn", companion=False, identity={"id":"same"})
        names=["native/libkn.so","native/libmadb_kotlin_owned_runtime.so","native/libc++_shared.so"]
        data={n:b"\x7fELF"+n.encode() for n in names}
        inventory={n:ref(n,b) for n,b in data.items()}
        candidate["native_members"]={"package/libs/arm64-v8a/"+n.split("/")[-1]:b for n,b in data.items()}
        objects={n:ref(n) for n in ["objects/libnapi_bridge.a","objects/libmadb_kn_executor.a","objects/kotlin-bootstrap.o"]}
        after=["-shared","--soname=libmadb_kotlin_owned_runtime.so", "/project/tmp/konan_temp123/libmadb_kotlin_owned_runtime.so.o",
               "/project/runtime/build/classes/kotlin/ohosArm64/main/cinterop/runtime-cinterop-interop/default/targets/ohos_arm64/included/libnapi_bridge.a",
               "/project/probe/build/classes/kotlin/ohosArm64/main/cinterop/probe-cinterop-executor/default/targets/ohos_arm64/included/libmadb_kn_executor.a"]
        startup="/project/konan/dependencies/sysroot-ohos-aarch64-6.0.2.640-04/usr/lib/aarch64-linux-ohos/Scrt1.o"
        linked=dict(identity=candidate["identity"],outputs=list(inventory.values()),linker_correction=[dict(before=[startup,*after],after=after,removed=[startup])])
        record=dict(linker_arguments=[a.replace("/project","{project}").replace("konan_temp123","konan_temp{temporary}") for a in after],bootstrap_wrap_flags=[],loader_symbols={"libkn.so":["RegisterOwnedRuntime"],"libmadb_kotlin_owned_runtime.so":["madb_kn_owned_initialize"]})
        args=["/clang","--target=aarch64-linux-ohos","--sysroot=/sysroot","-shared","/project/native/bootstrap/bootstrap.o","-L/llvm/lib/aarch64-linux-ohos","-lace_napi.z","-ldl","-Wl,--no-undefined","-Wl,-soname,libkn.so","-o","/project/artifacts/libkn.so"]
        links=[dict(tool="cpf_clang",tool_sha256=tools["c07-kotlin-cpf_clang"],exit_code=0,environment={},arguments=args)]
        symbols={"libraries":[dict(path=n,soname=n,sha256=inventory["native/"+n]["sha256"],required_loader_symbols=e,exports=e) for n,e in record["loader_symbols"].items()]}
        return candidate,{"link":{"outputs":list(inventory.values())}},objects,links,linked,symbols,"/project",data.__getitem__,inventory,record

    def test_recorded_link_and_exact_native_har_bytes(self):
        self.assertEqual(_linked(*self.fixture())["status"],"bound")

    def test_object_archive_linker_or_startup_substitution_fails(self):
        for change in (lambda a:a[4]["linker_correction"][0]["after"].append("-lforeign"),
                       lambda a:a[2].pop("objects/libmadb_kn_executor.a"),
                       lambda a:a[4]["linker_correction"][0]["removed"].clear(),
                       lambda a:a[3][0]["arguments"].insert(1,"-Wl,--wrap=free")):
            args=self.fixture();change(args)
            with self.assertRaises(CandidateError):_linked(*args)

    def test_rehashed_native_receipt_cannot_change_har_bytes(self):
        args=self.fixture();args[0]["native_members"]["package/libs/arm64-v8a/libkn.so"]=b"foreign"
        with self.assertRaisesRegex(CandidateError,"ELF/candidate/HAR"):_linked(*args)

    def test_ordinary_elf_must_not_export_test_thread_probe(self):
        args=self.fixture();args[5]["libraries"][1]["exports"].append("madb_kn_owned_thread_probe")
        with self.assertRaisesRegex(CandidateError,"ordinary ELF"):_linked(*args)

    def test_missing_real_owner_loader_symbol_is_rejected(self):
        args=self.fixture();args[5]["libraries"][1]["exports"]=[]
        with self.assertRaisesRegex(CandidateError,"owner/loader"):_linked(*args)


class CandidateReceiptClosure(unittest.TestCase):
    def fixture(self, root):
        candidate,stages,objects,links,linked,symbols,project,read,inventory,record=LinkAndHarRecords().fixture()
        _,rows=native_rows()
        c,review,decl,lock=sources()
        candidate.update(c)
        native_candidate,tools=compiler();candidate["toolchain"].update(native_candidate["toolchain"])
        candidate.update(route="kotlin",root=root,manifest={},provenance={"producer_revision":"final","input_digest":"inputs"})
        facts={"functions":[{"source":{"path":"reviewed/OwnedModel.kt"}}]};schema={"record":"Snapshot"}
        content={"frontend-facts.json":json.dumps(facts),"record-schema.json":json.dumps(schema),"record-export.d.ts":"export function run(): void;"}
        generated=[dict(ref("resources/"+n,t.encode()),text=t) for n,t in content.items()]
        decl.update(authority="actual CPF Kotlin KSP1 and akinterop 1.1.0; managed single-record profile",typed_api_inferred=False,facts=facts,record_schema=schema,
                    declaration=content["record-export.d.ts"],generated=generated,descriptor={"ksp":"actual"},tools={n:{"sha256":tools["c07-kotlin-"+n]} for n in ("cpf_java","gradle_cli")},closure={"maven":"maven","trees":{}})
        candidate["toolchain"]["kotlin"].update(dependency_lock="maven",trees={})
        review["variants"]["ordinary"].update(record,generated_files=[{k:g[k] for k in ("path","sha256","size")} for g in generated])
        review.update(limits=["fixture is not runtime evidence"],review_notes=[],test_runtime_derivation={})
        def frontend(task):
            return [dict(tool="gradle",exit_code=0,java_sha256=tools["c07-kotlin-cpf_java"],cli_sha256=tools["c07-kotlin-gradle_cli"],arguments=["/java","-Xmx64m","-Xms64m","-Dorg.gradle.appname=gradle","-javaagent:/gradle/lib/agents/gradle-instrumentation-agent-8.14.6.jar","-jar","/gradle-cli","-p","/project","--no-daemon","--console=plain","--offline",task]),
                    dict(tool="node",exit_code=0,tool_sha256=tools["c07-node"],arguments=["/node","/inputs/adapters/generators/arkts/read_kotlin_exports.cjs","/typescript.js"],stdout=json.dumps(decl["descriptor"]))]
        docs={"declarations.json":{"kotlin":decl},"madb.lock":lock,"generated/contract/kotlin-ksp-facts.json":facts,"generated/contract/kotlin-record-schema.json":schema,
              "logs/compile-commands.json":rows+frontend(":probe:kspKotlinOhosArm64"),"logs/link-commands.json":links+frontend(":probe:linkReleaseSharedOhosArm64"),
              "kotlin-link.json":linked,"kotlin-symbols.json":symbols,"kotlin-compile.json":{"identity":candidate["identity"],"kotlin":decl}}
        def save(name,value):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(value).encode();p.write_bytes(raw);return ref(name,raw)
        refs={n:save(n,d) for n,d in docs.items()}
        for name in inventory:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(read(name));refs[name]=ref(name,read(name))
        evidence=[]
        for i,phase in enumerate(("compile","link")):
            outputs=list(objects.values())+[refs["kotlin-compile.json"]] if phase=="compile" else list(inventory.values())+[refs["kotlin-link.json"],refs["kotlin-symbols.json"]]
            stage=dict(schema="madb.build-evidence/1",phase=phase,status="passed",exit_code=0,generation_id="generation",profile_digest="profile",input_digest="inputs",logs=[refs["logs/"+phase+"-commands.json"]],outputs=outputs)
            name="evidence/task-%04d.json"%i;refs[name]=save(name,stage);evidence.append(refs[name])
        candidate["manifest"].update(files=list(refs.values()),dependencies=[],build_evidence=evidence,generation_id="generation",candidate_digest="candidate",selector={"profile_digest":"profile"})
        review_path=root/"review.json";review_path.write_text(json.dumps(review));return candidate,review_path

    def test_complete_static_binding_does_not_claim_live_threads(self):
        with tempfile.TemporaryDirectory() as d:
            candidate,review=self.fixture(Path(d))
            with patch("c07_kotlin_source_review.REVIEW",review):result=verify_kotlin_source_review(candidate)
            self.assertEqual(result["status"],"bound",result)
            self.assertEqual(result["thread_witness"]["status"],"not-assessed")
            self.assertEqual(result["thread_witness"]["scope"],"static-only")
            self.assertFalse(result["independent_patch_replay"])

    def test_existing_compile_reference_without_public_bytes_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            candidate,review=self.fixture(Path(d))
            candidate["manifest"]["files"]=[r for r in candidate["manifest"]["files"] if r["path"]!="kotlin-compile.json"]
            with patch("c07_kotlin_source_review.REVIEW",review):result=verify_kotlin_source_review(candidate)
            self.assertEqual(result["status"],"blocked")
            self.assertIn("unpublished candidate evidence: kotlin-compile.json",result["reason"])

    def test_foreign_generation_cannot_pass_rehashed_receipts(self):
        with tempfile.TemporaryDirectory() as d:
            candidate,review=self.fixture(Path(d));candidate["manifest"]["generation_id"]="foreign"
            with patch("c07_kotlin_source_review.REVIEW",review):result=verify_kotlin_source_review(candidate)
            self.assertEqual(result["status"],"blocked")
            self.assertIn("foreign/unsuccessful Build receipt",result["reason"])

    def test_profile_pair_requires_exact_roles_and_same_revision(self):
        with tempfile.TemporaryDirectory() as d:
            candidate,review=self.fixture(Path(d));other=copy.deepcopy(candidate)
            for change in (lambda c:c.update(companion=False),lambda c:c["provenance"].update(producer_revision="other"),lambda c:c["profile"].update(id="unrelated-test")):
                other=copy.deepcopy(candidate);other.update(companion=True);other["profile"]["id"]+="-test";change(other)
                self.assertEqual(verify_kotlin_profile_pair(candidate,other)["status"],"blocked")


if __name__ == "__main__":
    unittest.main()
