
import collections, hashlib, importlib.metadata, json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
from requests_cache.serializers import pickle_serializer
from requests_cache.cache_keys import create_key
from kg_microbe.utils import mediadive_bulk_download as production

W = Path("/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe-rebuild-20261105")
E = W / "data/rebuild-evidence/20261105"
R = E / "mediadive-retry-1734"
A = R / "attempts/retry-1"
OLD = E / "mediadive/attempts/sequence-1/full"
RAW = W / "data/raw/mediadive"
BASE = "https://mediadive.dsmz.de/rest/"
CACHE = "mediadive_bulk_cache.sqlite"
JNAMES = ("media_detailed.json", "media_strains.json", "solutions.json", "compounds.json")
HELPER_SHA = "c4ef41f2aabb847404249f59dfc4be39f2fa4f58ba7a03af4dc8a05bf8908a9c"
MANIFEST_SHA = "d63d0a6be750bc6f1f436aeb82e22d04c2d457fb0a3dac670d1f5b44f9990368"
UNKNOWN = {"status":404, "count":0, "error":"DataNotFound", "msg":"Medium does not exist or composition was not calculated"}
tracked, checks, details = {}, {}, {}
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""): h.update(block)
    return h.hexdigest()
def identity(path):
    st=path.stat()
    return {"sha256":sha(path),"bytes":st.st_size,"mtime_ns":st.st_mtime_ns,"inode":st.st_ino}
def track(path):
    path=Path(path)
    if path not in tracked: tracked[path]=identity(path)
    return path
def strict(body):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: raise ValueError("duplicate JSON key "+k)
            d[k]=v
        return d
    def constant(value): raise ValueError("nonstandard JSON constant "+value)
    return json.loads(body,object_pairs_hook=pairs,parse_constant=constant)
def load(path):
    return strict(track(path).read_bytes())
def check(name,passed,detail=None):
    checks[name]=bool(passed)
    if detail is not None: details[name]=detail
def same_record(path,record):
    if not path.is_file() or path.is_symlink(): return False
    value=identity(track(path))
    return path.stat().st_nlink==1 and all(value[k]==record[k] for k in ("sha256","bytes"))
def valid_strains(payload):
    return (isinstance(payload,dict) and set(payload)=={"status","count","data"}
      and type(payload["status"]) is int and payload["status"]==200
      and type(payload["count"]) is int and isinstance(payload["data"],list)
      and payload["count"]==len(payload["data"])
      and all(isinstance(item,dict) and type(item.get("id")) is int and item["id"]>=0 for item in payload["data"]))
def unknown(payload):
    return (isinstance(payload,dict) and type(payload.get("status")) is int
       and type(payload.get("count")) is int and payload==UNKNOWN)
def cache_rows(path,payloads=False,raw=False):
    path=track(path)
    for suffix in ("-wal","-shm","-journal"):
        side=path.with_name(path.name+suffix)
        if side.exists():
            track(side)
            assert raw and suffix!="-journal", "Unexpected cache sidecar"
            assert suffix!="-wal" or side.stat().st_size==0, "Unconsumed WAL"
    db=sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1",uri=True)
    try:
        assert db.execute("PRAGMA quick_check").fetchone()==("ok",)
        assert db.execute("SELECT count(*) FROM redirects").fetchone()==(0,)
        result={}
        for key,blob in db.execute("SELECT key,value FROM responses"):
            response=pickle_serializer.loads(blob)
            url=response.url
            assert url not in result
            payload=strict(response.content)
            assert response.status_code==200
            assert response.request.url==url and response.request.method=="GET"
            assert key==create_key(response.request,serializer=pickle_serializer)
            assert response.headers.get("Content-Type","").split(";",1)[0].strip().lower()=="application/json"
            if "/medium-strains/" in url:
                assert valid_strains(payload), "Invalid cached strain envelope"
                kind="valid_empty" if not payload["data"] else "nonempty_strains"
            else:
                assert url.startswith(BASE+"medium/") and isinstance(payload,dict) and isinstance(payload.get("data"),dict)
                assert str(payload["data"]["medium"]["id"])==url.rsplit("/",1)[-1]
                kind="medium_detail"
            record={"cache_key":key,"body_sha256":hashlib.sha256(response.content).hexdigest(),
                "body_bytes":len(response.content),"serialized_value_sha256":hashlib.sha256(blob).hexdigest(),"kind":kind}
            if payloads: record["payload"]=payload
            result[url]=record
        return result
    finally: db.close()

assert (A/"receipt.json").is_file(), "Await completed final receipt"
final=load(A/"receipt.json")
started=load(A/"started.json")
stage=load(E/"stages/mediadive-retry-1734-live-r1/result.json")
track(E/"stages/mediadive-retry-1734-live-r1/process.log")
check("stage_exit2_is_expected_coverage_block",stage["exit_code"]==2 and stage["error"]=="SystemExit(2)" and final["status"]=="blocked")
check("stage_import_origins_unchanged_and_current",stage["origins_before"]==stage["origins_after"]
 and all(sha(track(Path(record["file"])))==record["sha256"] for record in stage["origins_after"].values()))
assert final["status"] in {"blocked","passed","failed"}, "Receipt not final"
catalogue=load(W/"data/raw/mediadive.json")["data"]
ids=[str(item["id"]) for item in catalogue]
expected={BASE+endpoint+key for endpoint in ("medium/","medium-strains/") for key in ids}
check("literal_catalogue_unique_3344_and_expected_6688",len(ids)==len(set(ids))==3344 and len(expected)==6688)
check("catalogue_identity",sha(W/"data/raw/mediadive.json")==final["identity"]["catalogue_sha256"])
check("final_identity_matches_started",final["identity"]==started["identity"])
runtime=final["identity"]
code_paths={"retry_helper_sha256":W/"scripts/adhoc/kgm_mediadive_retry_20261105.py",
 "helper_sha256":W/"scripts/adhoc/kgm_mediadive_refresh_20261105.py",
 "production_sha256":W/"kg_microbe/utils/mediadive_bulk_download.py",
 "launcher_sha256":Path(runtime["launcher"])}
for key,path in code_paths.items(): check("runtime_"+key,sha(track(path))==runtime[key])
check("reviewed_retry_helper_identity",runtime["retry_helper_sha256"]==HELPER_SHA)
check("python_runtime",sys.executable==runtime["python"] and sys.version==runtime["python_version"])
check("requests_dependency_versions",all(importlib.metadata.version(k)==v for k,v in runtime["dependencies"].items()))
check("native_retry_settings",runtime["settings"]=={"max_workers":5,"retry_count":3,"retry_delay":2.0})

manifest=load(R/"preservation/manifest.json")
check("preservation_manifest_pinned",sha(R/"preservation/manifest.json")==MANIFEST_SHA)
preserved=[]
for record in manifest["original_files"]:
    original=W/record["path"]
    item={"path":record["path"],"expected":{k:record[k] for k in ("sha256","bytes")}}
    if original.parent==RAW:
        kept=R/"preservation/raw-mediadive"/original.name
        item["preserved_copy_matches"]=same_record(kept,record)
        item["mutable_production_output"]=original.name in {"media_strains.json",CACHE,CACHE+"-wal",CACHE+"-shm"}
        if not item["mutable_production_output"]:
            item["current_original_matches"]=same_record(original,record)
    else:
        item["current_original_matches"]=same_record(original,record)
        if original.parent==OLD:
            item["preserved_copy_matches"]=same_record(R/"preservation"/original.name,record)
    preserved.append(item)
protected=[{"path":record["path"],"matches":same_record(W/record["path"],record)}
 for record in manifest["protected_ontology_and_review_artifacts"]]
check("all_original_and_preserved_manifest_records_match",all(
 all(v for k,v in row.items() if k.endswith("_matches")) for row in preserved))
check("all_protected_ontology_and_review_artifacts_match",all(row["matches"] for row in protected))
oldreceipt=load(OLD/"receipt.json")
check("prior_receipt_pinned",sha(OLD/"receipt.json")==manifest["prior_full_receipt_sha256"]
  =="d792f4def31b55e3e2aca041e4c1d45ef0f86e2b20427e7be78e84d168ffa840")
check("prior_receipt_and_artifact_hashes",oldreceipt["status"]=="failed"
 and all(sha(track(OLD/"artifacts"/name))==digest for name,digest in oldreceipt["artifacts"].items())
 and sha(track(OLD/"http-attempts.jsonl"))==oldreceipt["http_attempts_sha256"])
oldhistory=collections.defaultdict(list)
for line in track(OLD/"http-attempts.jsonl").read_text().splitlines():
    event=strict(line); oldhistory[event["request_url"]].append(event)
oldaccepted={url:events[-1] for url,events in oldhistory.items() if events[-1].get("valid")}
unresolved=expected-set(oldaccepted)
check("prior_exact_coverage",set(oldhistory)==expected and len(oldaccepted)==6056 and len(unresolved)==632)
check("prior_failed_have_no_earlier_success",all(not any(e.get("valid") for e in oldhistory[u]) for u in unresolved))
prior_partition={u:("transport_"+oldhistory[u][-1]["transport_error"] if oldhistory[u][-1].get("transport_error")
 else "http_"+str(oldhistory[u][-1]["status"])) for u in unresolved}
check("prior_failed_partition_601_404_31_connection",dict(collections.Counter(prior_partition.values()))==
 {"http_404":601,"transport_ConnectionError":31})
oldcache=cache_rows(OLD/"artifacts"/CACHE)
baseline_inventory=load(R/"baseline-review/successful-responses.json")
check("prior_independent_success_inventory_pinned",sha(R/"baseline-review/successful-responses.json")=="32fd51c7a39780744f127f6f8eef180d9b2602c66d7fa3d36b3b063a7624a611")
check("baseline_cache_matches_prior_ledger",set(oldcache)==set(oldaccepted)
 and all(oldcache[u]["body_sha256"]==e["body_sha256"] for u,e in oldaccepted.items()))
check("baseline_cache_matches_saved_independent_inventory",set(oldcache)==set(baseline_inventory)
 and all(oldcache[u]["serialized_value_sha256"]==r["persisted_blob_sha256"]
 and oldcache[u]["cache_key"]==r["cache_key"] and oldcache[u]["body_sha256"]==r["body_sha256"]
 for u,r in baseline_inventory.items()))

effective=set(oldaccepted)
new_last={}
history_review={}
phase_review={}
phase_sets={}
all_body_flags=True
all_attempt_rules=True
all_phase_identity=True
for phase_name in ("canary","batch"):
    folder=A/phase_name
    if not folder.exists(): continue
    phase=load(folder/"receipt.json")
    chosen=load(folder/"selected-media.json")["data"]
    selected={BASE+"medium-strains/"+str(item["id"]) for item in chosen}
    phase_sets[phase_name]=selected
    events_by_url=collections.defaultdict(list)
    ledger=folder/"http-attempts.jsonl"
    if ledger.exists():
        for line in track(ledger).read_text().splitlines():
            event=strict(line); events_by_url[event["request_url"]].append(event)
    all_attempt_rules &= set(events_by_url)<=selected
    classifications={}
    for url in selected:
        events=events_by_url.get(url,[])
        all_attempt_rules &= len(events)<=3 and [e["attempt"] for e in events]==list(range(1,len(events)+1))
        successes=[]
        for event in events:
            kind="transport_error" if "transport_error" in event else "unresolved_http_or_payload"
            valid=False
            documented=False
            if "body_path" in event:
                body_path=folder/event["body_path"]
                assert body_path.resolve().is_relative_to(folder.resolve())
                body=track(body_path).read_bytes()
                all_body_flags &= hashlib.sha256(body).hexdigest()==event["body_sha256"] and len(body)==event["body_bytes"]
                try: payload=strict(body)
                except (ValueError,UnicodeError): payload=None
                headers={k.lower():v for k,v in event.get("response_headers",{}).items()}
                valid=(event.get("status")==200 and event.get("response_url")==url
                   and event.get("prepared_request_url")==url and event.get("request_method")=="GET"
                   and headers.get("content-type","").split(";",1)[0].strip().lower()=="application/json"
                   and valid_strains(payload))
                documented=(event.get("status")==404 and event.get("response_url")==url and unknown(payload))
                kind=("valid_empty" if not payload["data"] else "recovered") if valid else (
                   "unknown_404" if documented else "unresolved_http_or_payload")
                all_body_flags &= bool(event.get("documented_unknown",False))==documented
                if valid:
                    all_body_flags &= event.get("payload_kind")==("empty_strains" if kind=="valid_empty" else "strains")
            else:
                all_body_flags &= "transport_error" in event
            all_body_flags &= event.get("valid") is valid and not event.get("from_cache",False)
            if valid: successes.append(event)
            event_class=kind
        all_attempt_rules &= len(successes)<=1 and (not successes or successes[-1] is events[-1])
        kind=event_class if events else "not_attempted"
        classifications[url]=kind
        if events: new_last[url]=events[-1]
        history_review[url]={"medium_id":url.rsplit("/",1)[-1],"phase":phase_name,
          "prior_final_partition":prior_partition.get(url),"new_final_outcome":kind,"attempt_count":len(events),
          "attempt_statuses":[e.get("transport_error",e.get("status")) for e in events],
          "attempt_body_hashes":[e.get("body_sha256") for e in events]}
    fresh={u for u,kind in classifications.items() if kind in {"recovered","valid_empty"}}
    if phase["status"]=="completed": effective.update(fresh)
    all_phase_identity &= phase["outcomes"]==classifications and phase["outcome_counts"]==dict(collections.Counter(classifications.values()))
    all_phase_identity &= set(phase["fresh_valid_endpoints"])==fresh
    all_phase_identity &= phase.get("association_admission") is False
    if phase.get("http_attempts_sha256"): all_phase_identity &= sha(ledger)==phase["http_attempts_sha256"]
    for name,digest in phase["snapshot_artifacts"].items():
        all_phase_identity &= sha(track(folder/"artifacts"/name))==digest
    all_phase_identity &= same_record(folder/"receipt.json",final[phase_name+"_receipt"])
    phase_review[phase_name]={"status":phase["status"],"selected":len(selected),"observed":len(events_by_url),
      "transport_attempts":sum(len(v) for v in events_by_url.values()),"outcome_counts":dict(collections.Counter(classifications.values())),
      "fresh_valid_endpoints":len(fresh)}
check("new_raw_body_metadata_and_flags_recomputed",all_body_flags)
check("new_transport_scope_and_attempt_budgets",all_attempt_rules)
check("phase_receipts_match_independent_reconstruction",all_phase_identity)
check("exact_canary_literal_target",phase_sets.get("canary")=={BASE+"medium-strains/1366"})
canary_outcome=history_review.get(BASE+"medium-strains/1366",{}).get("new_final_outcome")
canary_verified=phase_review.get("canary",{}).get("status")=="completed" and canary_outcome in {"unknown_404","recovered","valid_empty"}
check("batch_canary_gate_and_exact_remaining_scope",
 ("batch" in phase_sets)==canary_verified and (not canary_verified or phase_sets["batch"]==unresolved-phase_sets["canary"]))
check("new_observations_cover_only_original_unresolved",set(new_last)<=unresolved)
current=cache_rows(RAW/CACHE,payloads=True,raw=True)
retained=cache_rows(A/"after"/CACHE,payloads=True)
fields=("body_sha256","serialized_value_sha256","cache_key","body_bytes","kind")
check("all_6056_baseline_cache_blobs_and_keys_unchanged",set(oldcache)<=set(current)
 and all(all(current[u][k]==oldcache[u][k] for k in fields) for u in oldcache))
check("raw_and_retained_cache_exact_effective_accepted_union",set(current)==set(retained)==effective)
check("raw_and_retained_cache_response_identity",all(all(current[u][k]==retained[u][k] for k in fields) for u in set(current)&set(retained)))
check("fresh_cache_matches_actual_http_bodies",all(current[u]["body_sha256"]==new_last[u]["body_sha256"]
 for u in effective-set(oldaccepted)))
combined=load(A/"combined-coverage.json")
check("combined_coverage_receipt_identity",same_record(A/"combined-coverage.json",final["combined_coverage"]))
check("combined_accepted_exact_recomputed_coverage",set(combined["accepted"])==effective
 and all(all(combined["accepted"][u][k]==current[u][k] for k in ("body_sha256","serialized_value_sha256","cache_key"))
 for u in effective))
remaining=expected-effective
check("remaining_unresolved_exact",set(combined["remaining_unresolved_urls"])==set(final["remaining_unresolved_urls"])==remaining)
check("final_counts",final["combined_valid_endpoints"]==len(effective)
 and final["recovered_endpoints"]==len(effective)-6056 and final["baseline_valid_endpoints"]==6056)
partition={
 "accepted_medium_details":sorted(u for u in effective if "/medium-strains/" not in u),
 "accepted_nonempty_strains":sorted(u for u in effective if current[u]["kind"]=="nonempty_strains"),
 "accepted_valid_empty_strains":sorted(u for u in effective if current[u]["kind"]=="valid_empty"),
}
for outcome in ("unknown_404","transport_error","unresolved_http_or_payload","not_attempted"):
    partition["unresolved_"+outcome]=sorted(u for u in remaining
       if history_review.get(u,{}).get("new_final_outcome","not_attempted")==outcome)
flattened=[u for values in partition.values() for u in values]
check("exact_disjoint_6688_endpoint_partition",len(flattened)==len(set(flattened))==6688 and set(flattened)==expected)
check("association_admission_matches_complete_coverage",final["association_admission"] is (not remaining)
 and final["status"]==("blocked" if remaining else "passed"))

def outputs_match(folder,rows):
    objects={name:load(folder/name) for name in JNAMES}
    expected_details={key:rows[BASE+"medium/"+key]["payload"]["data"] for key in ids}
    expected_strains={u.rsplit("/",1)[-1]:r["payload"]["data"] for u,r in rows.items()
       if r["kind"]=="nonempty_strains"}
    return {
      "details_order_exact":list(objects["media_detailed.json"])==ids,
      "details_exact":objects["media_detailed.json"]==expected_details,
      "strains_exact_nonempty_responses":objects["media_strains.json"]==expected_strains,
      "solutions_exact_production_extraction":objects["solutions.json"]==production.extract_solutions_from_media(expected_details),
      "compounds_exact_ordered_production_extraction":objects["compounds.json"]==production.extract_compounds_from_media(expected_details)}
preserved_baseline_strains=load(R/"preservation/raw-mediadive/media_strains.json")
current_strains=load(RAW/"media_strains.json")
check("all_prior_strain_json_values_preserved",all(key in current_strains and current_strains[key]==value
 for key,value in preserved_baseline_strains.items()))
for label,folder,rows in (("raw",RAW,current),("retained",A/"after",retained)):
    for name,passed in outputs_match(folder,rows).items(): check(label+"_"+name,passed)
check("all_four_raw_json_bytes_equal_pre_retry",all(sha(RAW/name)==sha(OLD/"artifacts"/name) for name in JNAMES))
check("final_raw_json_bytes_equal_retained",all(sha(RAW/name)==sha(A/"after"/name) for name in JNAMES))
check("after_snapshot_hashes_match_receipt",all(sha(track(A/"after"/name))==digest for name,digest in final["after_artifacts"].items()))
before_hashes={name:sha(track(A/"before"/name)) for name in (*JNAMES,CACHE,"mediadive_download.log")}
check("before_snapshot_json_and_log_equal_original",all(before_hashes[name]==sha(track(OLD/"artifacts"/name))
 for name in (*JNAMES,"mediadive_download.log")))
for key,values in partition.items(): assert len(values)==len(set(values))
matrix=collections.Counter((row["prior_final_partition"],row["new_final_outcome"]) for row in history_review.values())
track(Path(__file__))
check("all_audit_inputs_bytes_mtime_inode_unchanged",all(identity(path)==record for path,record in tracked.items()))
report={
 "audit_type":"independent_read_only_post_run_coverage_and_preservation",
 "created_at":datetime.now(timezone.utc).isoformat(),
 "status":"passed" if all(checks.values()) else "failed",
 "runtime_defect_observed":not all(checks.values()) or final["status"]=="failed",
 "source_association_admission":final["association_admission"],
 "expected_process_exit":2 if final["status"]=="blocked" else (0 if final["status"]=="passed" else 1),
 "interpretation":"Expected incomplete-coverage block; unknown errors and transport outcomes are not empty associations." if final["status"]=="blocked" else final["status"],
 "receipt":{"path":str(A/"receipt.json"),**identity(A/"receipt.json")},
 "reviewed_helper_sha256":HELPER_SHA,
 "counts":{"catalogue":len(ids),"expected_endpoints":len(expected),"baseline_valid":len(oldcache),
   "combined_valid":len(effective),"new_valid":len(effective)-len(oldcache),"remaining_unresolved":len(remaining),
   "original_manifest_records":len(preserved),"protected_ontology_and_review_artifacts":len(protected),
   "audit_input_files":len(tracked)},
 "endpoint_partition_counts":{k:len(v) for k,v in partition.items()},
 "phase_review":phase_review,
 "actual_process":{"exit_code":stage["exit_code"],"error":stage["error"],"elapsed_seconds":stage["elapsed_seconds"]},
 "attempt_status_counts":dict(collections.Counter(str(status) for row in history_review.values() for status in row["attempt_statuses"])),
 "prior_to_retry_final_outcome_counts":[{"prior":a,"retry":b,"count":count} for (a,b),count in sorted(matrix.items())],
 "checks":checks,"check_details":details,
 "limitations":["No network, tests, transformations, Git operations, or changes to original evidence/raw data.",
    "The audit verifies the retained response coverage and preservation; it does not convert unknowns into biological absence.",
    "Interrupted-generation recovery remains the separate #1754 follow-up."]}
destination=R/"post-run-independent-review"
assert set(destination.iterdir())=={destination/"audit-driver.py"}, "Exclusive audit directory already contains reports"
outputs={"audit.json":report,"endpoint-partitions.json":partition,"retry-history-review.json":history_review,
 "preservation-review.json":{"original_records":preserved,"protected_records":protected},
 "input-identities.json":{str(path):record for path,record in tracked.items()},
 "cache-response-identities.json":{u:{k:v for k,v in r.items() if k!="payload"} for u,r in current.items()}}
for name,value in outputs.items():
    with (destination/name).open("x") as stream: json.dump(value,stream,indent=2,sort_keys=True);stream.write("\n")
readme=("Independent read-only audit: "+report["status"]+".\n\n"
 +"Expected endpoints: "+str(len(expected))+"; accepted: "+str(len(effective))+"; unresolved: "+str(len(remaining))+".\n"
 +"All "+str(len(oldcache))+" prior successful response blobs and cache keys were compared against the preserved original cache.\n"
 +"Source association admission remains "+str(final["association_admission"]).lower()+". Final helper status: "+final["status"]+".\n"
 +"The final source status is separate from this audit's verification result. Unknown 404s are never counted as valid-empty associations.\n"
 +"See audit.json for every check, endpoint-partitions.json for exact coverage, and preservation-review.json for original/protected identities.\n")
with (destination/"README.md").open("x") as stream: stream.write(readme)
manifest_out={path.name:{"sha256":sha(path),"bytes":path.stat().st_size} for path in sorted(destination.iterdir()) if path.is_file()}
with (destination/"audit-manifest.json").open("x") as stream:json.dump(manifest_out,stream,indent=2,sort_keys=True);stream.write("\n")
print(json.dumps({"report":str(destination/"audit.json"),"status":report["status"],"counts":report["counts"],
 "partitions":report["endpoint_partition_counts"],"failed_checks":[k for k,v in checks.items() if not v],
 "expected_process_exit":report["expected_process_exit"]},indent=2))
