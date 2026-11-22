"""Materialize synthetic public-memory wiring; no candidate or backend runs."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from calculations.platform_demo_fixtures import manifest as fixture_manifest
from experiments.lab.e01_v2_manifest import ExperimentManifest
from experiments.lab.e01_v2_design import Memory,Lesson,canonical
from experiments.lab.e01_v2_public_memory import PublicEventStore,RecentSequence


def run():
    # Explicit new interface fixture; no historical catalog is reconstructed.
    manifest=fixture_manifest()
    store=PublicEventStore(manifest,phase='prepare');task=manifest.prepare[0]
    store.begin(task)
    store.model_request('fixture-request','SCRIPTED FIXTURE: public source projection; no request sent.')
    store.model_response('fixture-response','SCRIPTED FIXTURE: no candidate generated and no test executed.')
    window=store.close(task);packet=store.extraction(window,window.event_ids)
    # These are hand-authored structural fixtures, not a generated/admitted M0.
    initial=Memory(tuple(Lesson(f'fixture-{i}',f'Synthetic note {i}; no capability claim.',task,'prepare') for i in range(4)))
    state=RecentSequence('U',initial,manifest.online)
    reads=[]
    for i,task_id in enumerate(manifest.online):
        read=state.begin(task_id);reads.append(json.loads(read.payload()))
        assert state.current(task_id) is read
        state.finish(task_id)
        state.publish(Lesson(f'fixture-u{i}',f'Synthetic online note {i}; no observed outcome.',task_id,'online'),validated=True)
    frozen=state.freeze_transfer(manifest.transfer)
    transfers=[]
    for task_id in manifest.transfer:
        transfers.append(json.loads(frozen.begin(task_id).payload()));frozen.finish(task_id)
    return {'identity':'synthetic structural demonstration, not real M0 or a model/candidate run',
        'api_calls':0,'candidate_processes':0,'real_m0_constructed':False,'fixture_origin':'platform_demo_fixtures.py; new interface-only data, not historical JSON task catalog',
        'extraction_request':json.loads(packet.body),'provenance':json.loads(packet.provenance),
        'source_archive':json.loads(store.archive()),'online_reads':reads,
        'final_storage_items':len(state.stored_memory().items),
        'transfer_reads':transfers,'admission_events':state.admission_events,
        'semantic_admission':False,'runtime_isolation_verified':False,
        'limitations':['hand-authored notes and caller-supplied validation flags are test fixtures',
                      'no admission receipt bound to Lesson; no real provider or durable sequence cursor',
                      'typed public observations do not prove arbitrary text free of hidden information']}


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False,indent=2))
