"""Trace one scripted lesson from public events to a publication receipt."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from calculations.platform_demo_fixtures import manifest as fixture_manifest
from experiments.lab.e01_v2_manifest import ExperimentManifest
from experiments.lab.e01_v2_design import Memory,Lesson
from experiments.lab.e01_v2_public_memory import PublicEventStore,RecentSequence
from experiments.lab.e01_v2_admission_receipts import AdmissionLedger

def run():
    # Explicit new interface fixture; no historical catalog is reconstructed.
    manifest=fixture_manifest()
    initial=Memory((Lesson('fixture-m0','SCRIPTED FIXTURE; no real prepared memory.',manifest.prepare[0],'prepare'),))
    sequence=RecentSequence('U',initial,manifest.online);task=manifest.online[0]
    sequence.begin(task)
    store=PublicEventStore(manifest,phase='online');store.begin(task)
    store.model_request('public-request','SCRIPTED FIXTURE: public task prompt; no backend call.')
    store.model_response('public-response','SCRIPTED FIXTURE: no task attempt or candidate execution.')
    window=store.close(task);sequence.finish(task)
    ledger=AdmissionLedger(store);key,_=ledger.request(window,window.event_ids)
    reply='SCRIPTED FIXTURE\n先核对公开接口的输入与输出约定。\nEND'
    start=reply.index('先');end=reply.index('\nEND')
    ledger.response(key,response_id='extract-response',text=reply,origin='scripted_fixture')
    lesson=ledger.candidate(key,item_id='fixture-online',start=start,end=end,source_event_ids=('public-request','public-response'))
    ledger.review(key,review_id='fixture-review',accepted=True,reviewer_kind='scripted_fixture',
        reviewer_id='demo',rationale='Demonstrate record linkage only; no factual or usefulness judgment.')
    assert ledger.publish(key,sequence)
    archive=json.loads(ledger.archive());row=archive['rows'][0]
    assert row['candidate']['lesson']['text']==reply[start:end]==lesson.text
    assert sequence.stored_memory().items[-1]==lesson
    return {'identity':'scripted provenance-binding demonstration, not real model memory or semantic review',
        'api_calls':0,'candidate_processes':0,'real_m0_constructed':False,'fixture_origin':'platform_demo_fixtures.py; new interface-only data, not historical JSON task catalog',
        'source_events':json.loads(store.archive()),'admission_archive':archive,
        'published_memory_sha256':sequence.stored_memory().sha256(),'stored_items':len(sequence.stored_memory().items),
        'limits':['trusted-host in-memory component; lower-level direct publish API still exists',
                  'no durable resume, live-provider binding, real M0 merge, or OS isolation',
                  'explicit reviewer category is a declared label, not identity authentication']}
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False,indent=2))
