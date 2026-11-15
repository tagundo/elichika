#!/usr/bin/env python3
"""Continue the exact new-layout journal, using only five already-owned items."""
import concurrent.futures
from collections import deque
import json
from pathlib import Path
import sys
import threading
import time

import individual_uploader as u
import existing_owned_diagnostic as diagnostic
import layout_review as layout
import owned_layout as scope
from ia_s3_errors import S3_CODES

MAX_OUTSTANDING = 128
REFRESH_SECONDS = 60
REFRESH_ACKS = 96
VISIBILITY_SECONDS = 900
MAX_DEFERRALS = 5


class Deferred(Exception):
    """Recognized transient; staging stays durable and retry needs fresh metadata."""
    def __init__(self, seconds):
        self.seconds = seconds


class OwnedPublisher(u.Publisher):
    def __init__(self, args, inputs, auth, work, plan, public=None, s3=None):
        diagnostic.validate_complete_inputs(inputs)
        u.require(args.command == 'upload' and not args.allow_partial and args.max_new_files == 0 and
                  args.diagnostic_name is None and 1 <= args.workers <= 4 and args.prefix in (None, layout.PREFIX),
                  'Only the unchanged complete five-owned publication is authorized')
        identity = plan['new_identity_template']
        expected_old = dict(identity); expected_old.pop('publication_layout')
        u.require(diagnostic.old_identity(args, inputs, auth) == expected_old and
                  identity['publication_layout'] == scope.PUBLICATION_LAYOUT and
                  set(plan['layout']['placements']) == set(inputs.objects) and
                  set(plan['layout']['placements'].values()) == set(layout.ITEMS),
                  'Complete publication layout/account/source/proof identity differs')
        u.require((work.path / 'journal.json').is_file() and (work.path / 'journal.events.jsonl').is_file(),
                  'The successful exact new-layout journal must be restored; fresh adoption is forbidden')
        self.args, self.inputs, self.auth, self.work, self.plan = args, inputs, auth, work, plan
        self.prefix, self.session = layout.PREFIX, auth['session_nonce']
        self.public, self.s3 = public or scope.BoundedPublic(), s3 or u.S3(auth, max_connections=args.workers)
        self.progress, self.budget = u.Progress(), u.ByteBudget(args.stage_budget, args.workers)
        self.journal = u.Journal(work, identity)
        self.source_last, self.source_lock = 0, threading.Lock()
        self.counted = set()
        self.stop_admission = threading.Event()
        self.cooldown_until = 0
        self.state_lock = threading.Lock()
        self.owner_cache = {}
        self.validate_records()
        self.validate_retained_seed()

    def validate_records(self):
        for name, record in self.journal.value['objects'].items():
            obj = self.inputs.objects.get(name)
            u.require(obj is not None and record.get('item') == self.plan['layout']['placements'][name] and
                      record.get('path') == obj['path'] and record.get('size') == obj['size'] and
                      record.get('sha256') == obj['sha256'] and u.HEX[32].fullmatch(record.get('md5','')) and
                      record.get('status') in ('STAGED','PUT_ACKNOWLEDGED','REMOTE_METADATA_VERIFIED'),
                      'Restored new-layout object reference differs from the complete source')
        item, prefix = layout.ITEMS[0], layout.INDEX_PREFIX + '/'
        allowed = {prefix + 'catalog.json'} | {prefix + 'profiles/' + p + '.json' for p in u.PROFILES}
        for key, record in self.journal.value['index_objects'].items():
            u.require(key in allowed and record.get('item') == item and record.get('path') == key,
                      'Restored index object lies outside the exact owned namespace')

    def validate_retained_seed(self):
        records=self.records()
        for name,old in self.plan['layout']['retained_acknowledged'].items():
            current=records.get(name,{})
            u.require(current.get('status') in ('PUT_ACKNOWLEDGED','REMOTE_METADATA_VERIFIED') and
                      all(current.get(k)==old.get(k) for k in ('item','path','size','sha256','md5')),
                      'An original acknowledged reference was forgotten, demoted or moved')
        current=records.get(diagnostic.NAME,{})
        u.require(current.get('status') in ('PUT_ACKNOWLEDGED','REMOTE_METADATA_VERIFIED') and
                  current.get('item')==diagnostic.ITEM and current.get('path')=='packs/'+diagnostic.NAME and
                  current.get('size')==diagnostic.SIZE and current.get('sha256')==diagnostic.SHA256 and
                  current.get('md5')==diagnostic.MD5,
                  'The successful existing-only diagnostic ACK must remain in the new-layout journal')

    def headers(self, item, size_hint):
        u.require(item in layout.ITEMS, 'New item creation and foreign destinations are forbidden')
        return {}  # Existing items: no auto-make, metadata or size-hint headers.

    def files(self, item):
        u.require(item in layout.ITEMS, 'Only the five fixed existing items may be queried as destinations')
        remote = self.metadata(item)
        u.require(remote is not None, 'An owned destination is absent; item creation is forbidden')
        result = u.owned_metadata(remote, item, self.session, self.inputs.inventory_sha, self.auth['account'])
        with self.state_lock:
            self.owner_cache[item] = (time.monotonic(), result)
        return result

    def preflight(self):
        return {item: self.files(item) for item in layout.ITEMS}

    def records(self):
        with self.journal.lock:
            return dict(self.journal.value['objects'])

    def outstanding(self, active_names=()):
        records = self.records()
        # The same journal snapshot counts a completed ACK once, or reserves its
        # not-yet-ACKed active task once. There is no release-before-ACK gap.
        return sum(r['status'] == 'PUT_ACKNOWLEDGED' for r in records.values()) + sum(
            records.get(n,{}).get('status') not in ('PUT_ACKNOWLEDGED','REMOTE_METADATA_VERIFIED') for n in active_names)

    def reconcile(self, snapshots):
        records = self.records()
        for item, files in snapshots.items():
            for key in files:
                if key.startswith('packs/'):
                    name = key[6:]
                    u.require(name in records and records[name]['item'] == item and records[name]['path'] == key,
                              'A remote pack has no exact owned durable journal; adoption is forbidden')
        promoted = 0
        for name, record in records.items():
            file = snapshots[record['item']].get(record['path'])
            if file is None:
                # Ingestion lag never clears an ACK or makes it uploadable.
                continue
            u.require(u.remote_equal(file, record['size'], record['md5']), 'Public pack metadata conflicts with the staged original')
            if record['status'] != 'REMOTE_METADATA_VERIFIED':
                self.journal.record(name, {**record, 'status':'REMOTE_METADATA_VERIFIED'})
                promoted += 1
            if name not in self.counted:
                self.progress.add('verified_files',1); self.progress.add('verified_bytes',record['size']); self.counted.add(name)
        return promoted

    def put_retry(self, item, key, path, size, sha256, md5, headers):
        u.require(not headers and item in layout.ITEMS and not self.stop_admission.is_set(),
                  'Stopped admission or non-owned/metadata-bearing PUT refused')
        with self.state_lock:
            cached = self.owner_cache.get(item)
        # Long source staging cannot bypass a current ownership guard. Every
        # deferred retry also forces a fresh observation through the coordinator.
        files = cached[1] if cached and time.monotonic()-cached[0] < 60 else self.files(item)
        if key in files:
            u.require(u.remote_equal(files[key], size, md5), 'Existing file differs; overwrite is forbidden')
            return False
        u.require(not self.stop_admission.is_set(), 'Global admission was stopped before PUT')
        with self.state_lock: remaining=self.cooldown_until-time.monotonic()
        if remaining>0: raise Deferred(min(60,remaining))
        try:
            ok, delay = self.s3.put(item,key,path,size,sha256,md5,{},self.progress)
        except BaseException:
            self.stop_admission.set()
            raise
        if ok: return True
        report = getattr(self.s3,'last_response_summary',lambda:{})()
        status, code = report.get('http_status'), report.get('xml_code','UNKNOWN')
        safe = {'http_status':status if type(status) is int and 100 <= status <= 599 else None,
                'xml_code':code if isinstance(code,str) and code in S3_CODES else 'UNKNOWN',
                'spam_refusal':report.get('spam_refusal') is True}
        print(json.dumps({'s3_response':safe},sort_keys=True),flush=True)
        category = getattr(self.s3,'last_failure_category',lambda:'UNKNOWN')()
        transport = safe['http_status'] is None and category in {
            'TIMEOUT','TLS_ERROR','REMOTE_DISCONNECTED','CONNECTION_RESET','BROKEN_PIPE','HTTP_PROTOCOL_ERROR','NETWORK_IO_ERROR'}
        congestion = (safe['http_status'] in (429,500,502,503,504) and
                      safe['xml_code'] in ('SlowDown','ServiceUnavailable','InternalError','RequestTimeout'))
        if safe['spam_refusal'] or not (congestion or transport):
            self.stop_admission.set()
            raise u.Failure('S3 spam/refusal/unknown category stops publication; no blind retry')
        seconds = max(30, min(60, delay if isinstance(delay,(int,float)) else 0))
        with self.state_lock:
            self.cooldown_until = max(self.cooldown_until,time.monotonic()+seconds)
        raise Deferred(seconds)

    def data(self):
        self.check_source()
        snapshots = self.preflight()
        self.reconcile(snapshots)
        grouped = {item:[] for item in layout.ITEMS}
        for name in sorted(self.inputs.objects): grouped[self.plan['layout']['placements'][name]].append(name)
        ready = deque({'item':item,'names':names,'index':0,'deferrals':0,'refresh':False} for item,names in grouped.items())
        active = {}
        pending = {n for n,r in self.records().items() if r['status']=='PUT_ACKNOWLEDGED'}
        refresh_at, since_refresh = time.monotonic()+REFRESH_SECONDS, 0
        last_progress = time.monotonic()
        fatal = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as executor:
            try:
                while ready or active:
                    now = time.monotonic()
                    pressure = len(pending)+len(active) >= MAX_OUTSTANDING
                    refresh = now >= refresh_at or since_refresh >= REFRESH_ACKS or pressure
                    # Reconcile a stable drained journal. Metadata GETs never occupy
                    # a staging/PUT worker or admit new work during backpressure.
                    if refresh and not active:
                        snapshots = self.preflight()
                        if self.reconcile(snapshots): last_progress = time.monotonic()
                        pending = {n for n,r in self.records().items() if r['status']=='PUT_ACKNOWLEDGED'}
                        refresh_at, since_refresh = time.monotonic()+REFRESH_SECONDS, 0
                        if len(pending) >= MAX_OUTSTANDING:
                            u.require(time.monotonic()-last_progress < VISIBILITY_SECONDS,
                                      'Bounded visibility wait exhausted; ACKs preserved and catalog unpublished')
                            time.sleep(2); continue
                    with self.state_lock: cooling = time.monotonic() < self.cooldown_until
                    while ready and len(active) < self.args.workers and not refresh and not cooling and not self.stop_admission.is_set():
                        c = ready.popleft()
                        while c['index'] < len(c['names']) and self.journal.value['objects'].get(c['names'][c['index']],{}).get('status') in ('PUT_ACKNOWLEDGED','REMOTE_METADATA_VERIFIED'):
                            c['index'] += 1
                        if c['index'] == len(c['names']): continue
                        if len(pending)+len(active) >= MAX_OUTSTANDING:
                            ready.appendleft(c); break
                        name=c['names'][c['index']]
                        future=executor.submit(self.one,name,self.inputs.objects[name],c['item'],snapshots[c['item']],{},defer_invisible_ack=True)
                        active[future]=c
                        self.progress.tasks(len(active))
                    if active:
                        done,_=concurrent.futures.wait(active,timeout=1,return_when=concurrent.futures.FIRST_COMPLETED)
                        for future in done:
                            c=active.pop(future)
                            try:
                                future.result()
                                name=c['names'][c['index']]
                                if self.journal.value['objects'][name]['status']=='PUT_ACKNOWLEDGED': pending.add(name)
                                c['index']+=1; c['deferrals']=0; since_refresh+=1; last_progress=time.monotonic()
                            except Deferred:
                                c['deferrals']+=1; refresh_at=0
                                u.require(c['deferrals'] < MAX_DEFERRALS,'Recognized congestion retry bound reached; durable journal preserved')
                            ready.append(c)
                        self.progress.tasks(len(active))
                    elif ready:
                        # Global cooldown is bounded; no thread holds a staged
                        # file, connection or worker while waiting for Retry-After.
                        time.sleep(1)
            except BaseException as error:
                fatal=error; self.stop_admission.set()
                for future in active: future.cancel()
            finally:
                # Drain already-running calls so every observed ACK is journaled
                # before the safe artifact is captured. No further task admission.
                for future in active:
                    if not future.cancelled():
                        try: future.result()
                        except BaseException as error:
                            if fatal is None: fatal=error
                self.progress.tasks(0)
        if fatal is not None: raise fatal
        # ACKs alone never complete data coverage. Recheck all five current lists.
        deadline=time.monotonic()+VISIBILITY_SECONDS
        while True:
            snapshots=self.preflight(); self.reconcile(snapshots)
            records=self.records()
            if all(records.get(n,{}).get('status')=='REMOTE_METADATA_VERIFIED' and
                   u.remote_equal(snapshots[self.plan['layout']['placements'][n]].get(self.inputs.objects[n]['path'],{}),
                                  self.inputs.objects[n]['size'],records[n]['md5']) for n in self.inputs.objects):
                break
            u.require(time.monotonic()<deadline,'Final actual public MD5 verification timed out; catalog remains unpublished')
            time.sleep(10)
        self.journal.status('ALL_42830_REMOTE_MD5_VERIFIED')

    def put_index_document(self,item,key,path,size,sha256,md5,existing):
        # Index is only nine small documents. Recognized transient retries remain
        # bounded and refresh owned metadata before any ambiguous resend.
        for attempt in range(MAX_DEFERRALS):
            try: return super().put_index_document(item,key,path,size,sha256,md5,existing)
            except Deferred as error:
                u.require(attempt+1<MAX_DEFERRALS,'Index congestion bound reached; catalog remains unpublished')
                time.sleep(error.seconds); existing=self.files(item)

    def publish_index(self):
        diagnostic.validate_complete_inputs(self.inputs)
        u.require(not self.stop_admission.is_set(), 'Stopped admission forbids publication')
        available = sorted(self.inputs.objects)
        u.require(all(self.journal.value["objects"].get(n, {}).get("status") == "REMOTE_METADATA_VERIFIED" for n in available), "All data objects must be remote-verified before index publication")
        target_expected = getattr(self.inputs, "target_expected", self.inputs.expected)
        target_reconciled = getattr(self.inputs, "target_reconciled", False)
        requested_total = getattr(self.inputs, "requested_total", 42830)
        target_sha = getattr(self.inputs, "target_manifest_sha", None)
        supplement = getattr(self.inputs, "supplement", None)
        complete = self.inputs.complete_source and target_reconciled and set(available) == set(target_expected)
        status = "COMPLETE" if complete else "INCOMPLETE"
        target_status = ("COMPLETE" if complete else "INCOMPLETE") if target_reconciled else "TARGET_UNRECONCILED"
        dataset_scope = "authoritative_target" if target_reconciled else "official_source_snapshot"
        item = layout.ITEMS[0]
        existing = self.files(item)
        docs = []
        for profile in u.PROFILES:
            header, present = u.profile_header(profile, target_expected, self.inputs.objects, self.inputs.inventory_sha, dataset_scope, target_status)
            header.update(publication_layout=scope.PUBLICATION_LAYOUT, layout_plan_sha256=scope.PLAN_RAW_SHA)
            docs.append((layout.INDEX_PREFIX + "/profiles/" + profile + ".json", header, present))
        keys = []
        for key, header, names in docs:
            path, size, sha256, md5 = self.stage_document(header, names)
            try:
                self.put_index_document(item, key, path, size, sha256, md5, existing)
                keys.append(key)
                if existing is None:
                    self.verify_batch(item, [key], True)
                    existing = self.files(item)
                    u.require(existing is not None, "New index ownership marker not visible")
            finally:
                path.unlink(missing_ok=True)
        self.verify_batch(item, keys, True)
        for key in keys:
            self.verify_index_sha256(item, key)
        descriptors = []
        for key, header, _ in docs:
            record = self.journal.value["index_objects"][key]
            u.require(record["status"] == "REMOTE_SHA256_VERIFIED", "Profiles must be fully remote-SHA256-verified before catalog publication")
            descriptors.append({"profile": header["profile"], "url": "https://archive.org/download/" + item + "/" + key,
                                "sha256": record["sha256"], "md5": record["md5"], "bytes": record["size"],
                                **{k: header[k] for k in ("status", "scope", "target_status", "expected_objects", "available_objects", "declared_bytes", "verified_bytes")}})
        catalog = {"schema": 1, "document_type": "catalog", "status": status,
                   "inventory_sha256": self.inputs.inventory_sha, "catalog_sha256": getattr(self.inputs, "effective_catalog_sha", self.inputs.catalog_sha),
                   "source_proof_catalog_sha256": self.inputs.catalog_sha,
                   "metadata_sha256": self.inputs.metadata_sha, "source_item": u.SOURCE_ITEM,
                   "source_items": [u.SOURCE_ITEM, u.SUPPLEMENT_ITEM] if supplement else [u.SOURCE_ITEM],
                   "supplemental_metadata_sha256": supplement["metadata_sha256"] if supplement else None,
                   "supplemental_proof_sha256": supplement["proof_sha256"] if supplement else None,
                   "supplemental_provenance": supplement["provenance"] if supplement else None,
                   "scope": dataset_scope, "source_snapshot_status": "COMPLETE" if getattr(self.inputs, "complete_snapshot", self.inputs.complete_source) else "INCOMPLETE",
                   "source_snapshot_objects": len(getattr(self.inputs, "source_expected", self.inputs.expected)), "requested_total": requested_total,
                   "target_status": target_status, "target_manifest_sha256": target_sha,
                   "requested_count_difference": requested_total - len(self.inputs.expected) if not target_reconciled else 0,
                   "expected_objects": len(target_expected), "available_objects": len(available),
                   "declared_bytes": sum(o["size"] for o in target_expected.values()),
                   "verified_bytes": sum(self.inputs.objects[n]["size"] for n in available),
                   "missing_objects": len(self.inputs.audit.get("missing", [])), "conflicting_objects": len(self.inputs.audit.get("conflicts", [])),
                   "unavailable_objects": len(target_expected) - len(available),
                   "verification_method": u.VERIFY_METHOD, "source_snapshot_databases": self.inputs.catalog["databases"],
                   "target_provenance": getattr(self.inputs, "target_provenance", None), "profile_manifests": descriptors,
                   "qa_status": "PENDING", "publication_layout": scope.PUBLICATION_LAYOUT, "layout_plan_sha256": scope.PLAN_RAW_SHA,
                   "partition": {"buckets": 5, "formula": "Reviewed exact placements preserve existing references; otherwise full SHA256(ASCII name) integer modulo 5", "new_items_created": 0}}
        key = layout.INDEX_PREFIX + "/catalog.json"
        path, size, sha256, md5 = self.stage_document(catalog)
        try:
            self.put_index_document(item, key, path, size, sha256, md5, existing)
        finally:
            path.unlink(missing_ok=True)
        keys.append(key)
        self.verify_batch(item, [key], True)
        self.verify_index_sha256(item, key)
        self.journal.status(status)
        result = {**self.inputs.summary(self.prefix), "status": status, "remote_verified_objects": len(available),
                  "target_status": target_status, "scope": dataset_scope,
                  "remote_verified_bytes": sum(self.inputs.objects[n]["size"] for n in available), "index_documents_full_remote_sha256_verified": len(keys),
                  "index_url": "https://archive.org/download/" + item + "/" + layout.INDEX_PREFIX + "/catalog.json",
                  "qa_status": "PENDING", "publication_layout": scope.PUBLICATION_LAYOUT, "layout_plan_sha256": scope.PLAN_RAW_SHA,
                  "index_sha256": self.journal.value["index_objects"][key]["sha256"],
                  "index_bytes": self.journal.value["index_objects"][key]["size"]}
        u.atomic_json(self.work.path / "publication.json", result)
        print(json.dumps(result, sort_keys=True), flush=True)


def main(argv=None):
    args=u.parser().parse_args(argv)
    work=publisher=None
    try:
        u.require(args.command=='upload' and args.auth_file and args.work and args.max_new_files==0 and args.diagnostic_name is None,
                  'Explicit complete five-owned upload arguments are required')
        plan=scope.load_plan(Path(__file__).resolve().parent/'five-owned-layout.json.gz')
        inputs=u.Inputs(args); diagnostic.validate_complete_inputs(inputs)
        auth=u.read_auth(args.auth_file)
        work=u.Work(args.work); work.clean_stale()
        publisher=OwnedPublisher(args,inputs,auth,work,plan)
        publisher.journal.status('FIVE_OWNED_CONTINUATION')
        publisher.progress.start()
        publisher.data(); publisher.publish_index()
        return 0
    except (u.Failure,ValueError,KeyError,TypeError,OSError) as error:
        print('FAILED: '+(str(error) if isinstance(error,u.Failure) else type(error).__name__),file=sys.stderr,flush=True)
        return 1
    finally:
        if publisher is not None:
            publisher.progress.stop(); publisher.journal.close(); publisher.s3.close()
        if work is not None: work.close()


if __name__=='__main__':
    raise SystemExit(main())
