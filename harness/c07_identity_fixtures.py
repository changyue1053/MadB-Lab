"""Admit explicitly supplied, deliberately invalid native fixtures from public output.

The normal candidate stays unchanged. These receipts bind a narrow constant edit
and actual library bytes; they never certify arbitrary native machine-code semantics.
"""
from pathlib import Path
import re
from candidate import CandidateError, file_digest, read_json
from c07_candidate import identity_values

EXPECTED = {"wrong-abi": ("GatewayAbi", "AbiMismatch", 3, 0),
            "wrong-profile": ("GatewayProfile", "ProfileMismatch", 4, 1),
            "wrong-build": ("GatewayBuild", "ArtifactMismatch", 5, 2)}
HEADER = "generated/native/identity.generated.hpp"
FACADE = "generated/facade/Boundary.ets"


def require(ok, reason):
    if not ok:
        raise CandidateError("ArtifactMismatch", "identity fixture: " + reason)


def fields(row):
    require(isinstance(row, dict) and set(("path", "sha256", "size")).issubset(row), "invalid file reference")
    require(isinstance(row["path"], str) and isinstance(row["sha256"], str) and
            re.fullmatch(r"sha256:[0-9a-f]{64}", row["sha256"]) and type(row["size"]) is int and row["size"] >= 0,
            "invalid digest or byte size")
    return {key: row[key] for key in ("path", "sha256", "size")}


def rows(items):
    require(isinstance(items, list), "input inventory is not an array")
    found = {}
    for item in items:
        value = fields(item)
        require(value["path"] not in found, "duplicate input path")
        found[value["path"]] = value
    return found


def admit_identity_fixtures(collection_path, collection_sha256, candidate):
    path = Path(collection_path).resolve()
    require(file_digest(path.read_bytes()) == collection_sha256, "collection pin differs")
    root = path.parent
    used = [{"path":str(path),"sha256":collection_sha256,"size":path.stat().st_size}]
    def external(ref):
        value = fields(ref); target = Path(value["path"]).resolve()
        require(target.is_relative_to(root), "fixture output escapes explicit collection directory")
        data = target.read_bytes()
        require(file_digest(data) == value["sha256"] and len(data) == value["size"], "changed fixture output: " + str(target))
        used.append(value)
        return data
    collection = read_json(path)
    require(collection.get("candidate") is False and len(collection.get("fixtures", [])) == 3, "not the exact three negative inputs")
    manifest = candidate["manifest"]
    inventory = {item["path"]: fields(item) for section in ("files","dependencies","build_evidence") for item in manifest[section]}
    require(HEADER in inventory and FACADE in inventory and "madb.lock" in inventory, "normal public contract is incomplete")
    lock = read_json(candidate["root"] / "madb.lock")
    pinned = rows(lock["inputs"])
    for name in (HEADER,FACADE):
        data=(candidate["root"]/name).read_bytes()
        require(file_digest(data)==inventory[name]["sha256"] and len(data)==inventory[name]["size"], "normal candidate changed")
    expected = candidate["identity"]["expected_identity"]
    components = expected.split(":")[1:]
    require(len(components)==3, "unsupported normal identity")
    admitted = {}
    for reference in collection["fixtures"]:
        external(reference); receipt = read_json(Path(reference["path"]))
        kind = receipt.get("case")
        require(kind in EXPECTED and kind not in admitted, "unknown or duplicate negative case")
        constant,error,event,component = EXPECTED[kind]
        require(receipt.get("candidate") is False and receipt.get("build_status")=="compiled-and-linked" and
                receipt.get("generation_id")==manifest["generation_id"] and receipt.get("selector")==manifest["selector"],
                "fixture is not derived from this candidate generation/profile")
        require(receipt.get("native_module")=="lib"+candidate["module"]+".so" and
                receipt.get("changed_files")==[HEADER] and fields(receipt["unchanged_facade"])==inventory[FACADE],
                "facade/module or permitted edited file differs")
        original, changed = rows(receipt["original_inputs"]), rows(receipt["fixture_inputs"])
        require(set(original)==set(changed) and all(original.get(k)==v for k,v in pinned.items()), "normal locked source inputs differ")
        require(all(original.get(k)==v for k,v in inventory.items() if k in original), "normal published input differs")
        require([k for k in original if original[k]!=changed[k]]==[HEADER], "more than the generated identity header changed")
        edits = receipt.get("native_constant_edits", [])
        require(isinstance(edits,list) and len(edits)==3 and len({e.get("constant") for e in edits})==3, "constant edits are not exact")
        edits={e["constant"]:e for e in edits}
        require(set(edits)=={constant,"GatewayIdentity","GatewayRouteIdentity"}, "unexpected edited native constant")
        selected=edits[constant]
        require(selected.get("before")==components[component] and isinstance(selected.get("after"),str) and
                re.fullmatch(r"[0-9a-f]{64}",selected["after"]) and selected["after"]!=selected["before"], "logical identity mismatch is not isolated")
        parts=list(components);parts[component]=selected["after"];wrong="madb-arkts/1:"+":".join(parts)
        route=candidate["route"]
        for name,old,new in (("GatewayIdentity",expected,wrong),("GatewayRouteIdentity",route+"/"+expected,route+"/"+wrong)):
            require(edits[name].get("before")==old and edits[name].get("after")==new, "composite native constant edit differs")
        header=(candidate["root"]/HEADER).read_text()
        for name,edit in edits.items():
            pattern = r'(\b'+name+r'\s*=\s*")'+re.escape(edit["before"])+r'("\s*;)'
            header,count=re.subn(pattern,lambda m:m.group(1)+edit["after"]+m.group(2),header)
            require(count==1, "generated native declaration is missing or ambiguous")
        encoded=header.encode()
        require(file_digest(encoded)==changed[HEADER]["sha256"] and len(encoded)==changed[HEADER]["size"], "edited header receipt differs from exact permitted transformation")
        library=external(receipt["library"])
        require(library[:6]==b"\x7fELF\x02\x01" and int.from_bytes(library[18:20],"little")==183, "negative is not a loadable ABI-compatible AArch64 ELF")
        require(identity_values(library,binary=True,allow_parser_prefix=True)=={wrong.encode()}, "actual negative DSO identity is absent/ambiguous/different")
        route_ids=set(re.findall(rb"(?:c|cpp|rust)/madb-arkts/1:[0-9a-f]{64}:[0-9a-f]{64}:[0-9a-f]{64}(?=\x00)",library))
        require(route_ids=={(route+"/"+wrong).encode()}, "actual negative route identity differs")
        phases=receipt.get("phases",[])
        require([p.get("phase") for p in phases]==["compile","link"], "missing actual compile/link receipts")
        for phase in phases:
            external(phase["log"])
        output=rows(phases[1]["outputs"])
        linked=output.get("native/lib"+candidate["module"]+".so")
        require(linked is not None and linked["sha256"]==receipt["library"]["sha256"] and linked["size"]==len(library), "linked output differs from supplied DSO")
        admitted[kind]={"kind":kind,"error":error,"event":event,"library":library,"library_ref":fields(receipt["library"]),
            "receipt_ref":fields(reference),"wrong_identity":wrong,"expected_identity":expected,
            "replaced_member":"package/libs/arm64-v8a/lib"+candidate["module"]+".so"}
    require(set(admitted)==set(EXPECTED), "missing negative fixture")
    return admitted,used
