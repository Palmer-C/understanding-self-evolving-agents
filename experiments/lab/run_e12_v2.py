"""E12 v2 engineering pilot. Default offline preflight; execution requires
--execute, a matching --approved-manifest, prior user authorization, and an
OS-isolated candidate executor.
A matching manifest checks consistency; it is not itself permission to spend.
"""
from __future__ import annotations
from dataclasses import asdict
import argparse,hashlib,json,os
from pathlib import Path
import sys,time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
TASKS_ROOT=ROOT/'experiments/tasks/v1'
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from experiments.lab.budget import Budget,BudgetExceeded
from experiments.lab.e05_v2 import source_files,digest
from experiments.lab.e11_resources_v2 import JournalBackend,SequenceLimits,atomic_json,utcnow
from experiments.lab.run_e11_v2 import E11Sandbox,VerificationUnavailable,LESSON_PROMPT,memory_prompt
from experiments.lab.protocol_agent_v3 import ProtocolAgentV3,SYSTEM_PROMPT
from experiments.lab.tasks import load_task_dir
from experiments.lab.sandbox import ExecutionUnavailable, require_isolated_execution
from experiments.lab.trace import new_run_id
from experiments.lab.e12_design_v2 import (Item,MemorySnapshot,construct_arms,measure_change,
    describe_pair,describe_recovery,restore_new_snapshot,rollback_requested,resource_totals)

VERSION='e12-v2-20260930'
ARM_ORDER=('control_no_update','append_1','append_3','rewrite_3','corrupt')
SOURCE_IDS=('offbyone-01','offbyone-02','mutabledefault-01','mutabledefault-02')
EVALUATION_IDS=('offbyone-05','offbyone-06','mutabledefault-05','mutabledefault-06')
REWRITE_PROMPT=('重写下面这一条来源经验，保留事实、适用范围和不确定性，不引入新事实。'
                '只输出一段1至120字符的纯文本，措辞须与原文不同。')
RESOURCE_KEYS=('generate_calls_reserved','transport_dispatches','known_prompt_tokens','known_completion_tokens')


def validate_design(sources,evaluation):
    if len(sources)!=4 or len(evaluation)!=4:raise ValueError('pilot requires four source and four evaluation tasks')
    ids=[t.task_id for t in sources+evaluation]
    if len(ids)!=len(set(ids)):raise ValueError('source and evaluation tasks must be unique and disjoint')
    from experiments.lab.run_e11_v2 import validate_tasks
    validate_tasks(sources+evaluation,4)
    if any(t.split not in ('train','select-valid') for t in sources):raise ValueError('source split mismatch')
    if any(t.split!='regression' for t in evaluation):raise ValueError('fixed regression evaluation required')


def delta_ledger(before,after):
    return {('calls' if k=='generate_calls_reserved' else k):after[k]-before[k] for k in RESOURCE_KEYS}


def valid_candidate(text,existing=()):
    if not isinstance(text,str):raise ValueError('candidate must be text')
    text=text.strip()
    if not text or len(text)>120 or '\n' in text or '\r' in text or text in existing:
        raise ValueError('candidate rejected; preserve original, do not regenerate')
    return text


def episode(task,memory,journal,out_dir,episode_id):
    journal._check(new_call=True)
    journal.set_context('task',episode_id)
    sandbox=E11Sandbox.create_temp(prefix='e12-v2')
    sandbox.protected=set(task.protected)
    sandbox.mutable_files={name for name in source_files(task,type('EmptyTrace',(),{'steps':[]})())
        if Path(name).name not in task.protected and not Path(name).name.endswith('_test.py')}
    agent=ProtocolAgentV3(journal,SYSTEM_PROMPT+memory_prompt([x.text for x in memory.items]),name=VERSION)
    try:
        trace=agent.run_episode(task,budget=Budget(),sandbox=sandbox,out_dir=out_dir)
    finally:sandbox.cleanup()
    if (journal.directory/'budget-stop.json').exists():raise BudgetExceeded('shared pilot budget stopped')
    if type(trace.verdict) is not bool:raise VerificationUnavailable('missing explicit verdict')
    return trace


def evaluate(tasks,memory,journal,directory,phase,progress):
    directory.mkdir(parents=True,exist_ok=False)
    memory.save_new(directory/'input-memory.json')
    results={}
    for i,task in enumerate(tasks):
        episode_id=f'{phase}-r0-{i:02d}-{task.task_id}'
        progress({'phase':phase,'episode_id':episode_id,'completed_task_ids':list(results)})
        trace=episode(task,memory,journal,directory/'episodes'/episode_id,episode_id)
        results[task.task_id]=trace.verdict
        atomic_json(directory/'in-progress.json',{'completed_verdicts':results,'status':'incomplete'})
    atomic_json(directory/'complete.json',{'verdicts':results,'memory_sha256':memory.sha256(),'phase':phase})
    return results


def run_pilot(sources,evaluation,backend,out_dir,*,limits=None,max_retries=4,retry_backoff=3.,design_manifest=None):
    """No automatic resume or output deletion; all failures persist."""
    validate_design(sources,evaluation)
    if backend.name!='scripted' and design_manifest is None:
        raise ValueError('non-scripted run requires a frozen manifest and prior authorization')
    if backend.name != 'scripted':
        require_isolated_execution()
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    limits=limits or SequenceLimits(calls=357,http_attempts=1785,
        prompt_tokens=10_000_000,completion_tokens=1_000_000,wall_seconds=21600)
    atomic_json(out_dir/'config.json',{'version':VERSION,'started_at':utcnow(),
        'status':'running','design_manifest':design_manifest,'arm_order':list(ARM_ORDER),
        'sources':[{'id':t.task_id,'sha256':digest(vars(t))} for t in sources],
        'evaluation':[{'id':t.task_id,'sha256':digest(vars(t))} for t in evaluation],
        'limits':asdict(limits),'max_retries':max_retries,'backend_name':backend.name,
        'backend_identity':{k:getattr(backend,k,None) for k in ('model','base_url','temperature','timeout')}})
    journal=JournalBackend(backend,out_dir/'calls',limits,max_retries=max_retries,retry_backoff=retry_backoff)
    state={'phase':'preparation','completed_arms':[]}
    def progress(current):
        state['current']=current
        atomic_json(out_dir/'in-progress.json',{**state,'ledger':journal.snapshot()})
    try:
        preparation_start=journal.snapshot()
        items=[]
        for i,task in enumerate(sources):
            episode_id=f'prepare-r0-{i:02d}-{task.task_id}'
            progress({'phase':'preparation','episode_id':episode_id})
            # Sources run independently with empty memory; shared pool is constructed once.
            trace=episode(task,MemorySnapshot(()),journal,out_dir/'preparation'/episode_id/'episode',episode_id)
            payload={'task_id':task.task_id,'statement':task.statement,
                     'mutable_source':source_files(task,trace),'verdict':trace.verdict}
            candidate_dir=out_dir/'preparation'/episode_id
            atomic_json(candidate_dir/'lesson-source.json',payload)
            journal.set_context('lesson',episode_id)
            reply=journal.generate([{'role':'system','content':LESSON_PROMPT},
                                    {'role':'user','content':json.dumps(payload,ensure_ascii=False)}])
            atomic_json(candidate_dir/'candidate.json',{'raw_text':reply.text,'admission':'pending_format_only'})
            try:
                candidate=valid_candidate(reply.text,[x.text for x in items])
            except ValueError:
                atomic_json(candidate_dir/'publication.json',{'status':'rejected_format_or_duplicate','retry_or_replacement':False})
                raise
            item=Item(f'candidate-{i}',candidate,task.task_id,'model candidate; format-only admission')
            items.append(item)
            atomic_json(candidate_dir/'publication.json',{'item':asdict(item),'status':'admitted_format_only'})
        baseline=MemorySnapshot((items[0],));pool=tuple(items[1:])
        progress({'phase':'preparation-rewrite'})
        journal.set_context('lesson','prepare-rewrite-r0')
        reply=journal.generate([{'role':'system','content':REWRITE_PROMPT},
                                {'role':'user','content':json.dumps(asdict(items[0]),ensure_ascii=False)}])
        atomic_json(out_dir/'preparation/rewrite-candidate.json',{'raw_text':reply.text})
        rewritten=Item(items[0].item_id,valid_candidate(reply.text,[x.text for x in items]),
                       items[0].source_task_id,'model rewrite; format-only admission')
        arms,injection=construct_arms(baseline,pool,rewritten)
        snapshots=out_dir/'snapshots';snapshots.mkdir()
        baseline.save_new(snapshots/'M0.json')
        MemorySnapshot(pool).save_new(snapshots/'candidate-pool.json')
        for name,memory in arms.items():memory.save_new(snapshots/f'{name}.json')
        atomic_json(snapshots/'injection.json',injection)
        prep_ledger=delta_ledger(preparation_start,journal.snapshot())
        atomic_json(out_dir/'preparation/ledger.json',prep_ledger)

        state['phase']='baseline'
        base_start=journal.snapshot()
        before=evaluate(evaluation,baseline,journal,out_dir/'baseline','baseline',progress)
        baseline_ledger=delta_ledger(base_start,journal.snapshot())
        results={};exclusive_ledgers={'baseline_evaluation':baseline_ledger}
        control=None
        for arm in ARM_ORDER:
            state['phase']=arm
            arm_start=journal.snapshot()
            memory=arms[arm]
            directory=out_dir/'arms'/arm
            after=evaluate(evaluation,memory,journal,directory/'evaluation',arm,progress)
            if arm=='control_no_update':control=after
            if control is None:raise RuntimeError('control must be complete before arm comparison')
            metrics=describe_pair(before,control,after)
            result={'arm':arm,'before':before,'control':control,'after':after,
                    'metrics':metrics,'change':measure_change(baseline,memory),
                    'rollback_requested':False if arm=='control_no_update' else rollback_requested(metrics['D_raw']),
                    'recovery':None}
            if arm!='control_no_update':
                # Restore every update arm, even if the business trigger did not fire.
                status=restore_new_snapshot(baseline,directory/'restored-M0.json')
                restored_memory=MemorySnapshot.load(directory/'restored-M0.json')
                restored=evaluate(evaluation,restored_memory,journal,directory/'restoration',arm+'-restore',progress)
                result['recovery']={'operation':status,'verdicts':restored,
                    'description':describe_recovery(before,control,restored,file_restored=status['file_restored']),
                    'reason':'preplanned for every update arm; not selected by observed degradation'}
            result['exclusive_ledger']=delta_ledger(arm_start,journal.snapshot())
            exclusive_ledgers[arm]=result['exclusive_ledger']
            atomic_json(directory/'complete.json',result)
            results[arm]=result;state['completed_arms'].append(arm)
            progress({'phase':arm,'status':'complete'})
        totals=resource_totals(prep_ledger,exclusive_ledgers)
        global_ledger=journal.snapshot()
        for key,value in totals.items():
            actual=global_ledger['generate_calls_reserved' if key=='calls' else key]
            if actual!=value:raise RuntimeError('exclusive ledger does not reconcile')
        summary={'version':VERSION,'status':'complete','p6_status':'open',
            'evidence_kind':'offline_harness_only' if backend.name=='scripted' else 'engineering_pilot',
            'shared_preparation':prep_ledger,'baseline_evaluation':baseline_ledger,
            'arms':results,'exclusive_resource_totals':totals,'ledger':global_ledger,
            'restoration_scope':'memory files plus fixed task re-evaluation; no external effects restored',
            'elapsed_seconds':time.perf_counter()-started,'ci95':None}
        atomic_json(out_dir/'summary.json',summary)
        progress({'phase':'finished','status':'complete'})
        return summary
    except BaseException as exc:
        atomic_json(out_dir/'interruption.json',{'at':utcnow(),'exception_type':type(exc).__name__,
            'state':state,'ledger':journal.snapshot(),
            'policy':'preserve incomplete records/cost; no imputation, automatic resume or replacement sampling'})
        raise


def selected_tasks():
    tasks={p.name:load_task_dir(p) for p in TASKS_ROOT.glob('*/*') if (p/'test.json').is_file()}
    sources=[tasks[i] for i in SOURCE_IDS];evaluation=[tasks[i] for i in EVALUATION_IDS]
    validate_design(sources,evaluation)
    return sources,evaluation


def preflight():
    sources,evaluation=selected_tasks()
    names=['run_e12_v2.py','e12_design_v2.py','run_e11_v2.py','e11_resources_v2.py',
           'e11_timing_v2.py','e11_analysis_v2.py','trigger_signals.py','e01_arms.py',
           'static_agent.py','protocol_agent_v3.py','action_protocol_v3.py','backends.py',
           'budget.py','sandbox.py','tasks.py','trace.py','e05_v2.py','e05_arms.py','taskset_spec.py']
    hashes={name:hashlib.sha256((ROOT/'experiments/lab'/name).read_bytes()).hexdigest() for name in names}
    hashes['protocol']=hashlib.sha256((ROOT/'experiments/protocols/E12-v2.md').read_bytes()).hexdigest()
    base_url=os.environ.get('AGENT_LAB_BASE_URL','').rstrip('/')
    url=urlsplit(base_url)
    if base_url and (url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment):
        raise ValueError('backend must be HTTPS without embedded credentials or query parameters')
    return {'version':VERSION,'purpose':'single fixed-pool engineering pilot; no automatic P6 judgment',
        'source_sha256':hashes,'backend_identity':{'model':os.environ.get('AGENT_LAB_MODEL'),'base_url':base_url,'timeout':120.},
        'sources':[{'id':t.task_id,'split':t.split,'sha256':digest(vars(t))} for t in sources],
        'evaluation':[{'id':t.task_id,'split':t.split,'sha256':digest(vars(t))} for t in evaluation],
        'primary_episodes':44,'construction_and_rewrite_calls':5,
        'max_generate_calls':357,'max_transport_dispatches':1785,
        'arm_order':list(ARM_ORDER),'repeats':1,'temperature':.7,'max_retries':4,
        'episode_budget':Budget().as_dict(),
        'pilot_limits':asdict(SequenceLimits(calls=357,http_attempts=1785,prompt_tokens=10_000_000,
                                           completion_tokens=1_000_000,wall_seconds=21600)),
        'rollback_business_threshold':.10,'restore_all_update_arms':True,'initial_memory_items':1,
        'candidate_pool_items':3,'no_monetary_hard_cap':True,
        'limitations':['Single chosen task-pool cluster; no population confidence interval.',
            'Fixed arm order and single prior control do not eliminate time effects.',
            'Append amount is confounded with candidate content; rewrite is a separate factor.',
            'Constructed false memory is not a sample of natural model errors.',
            'Memory file restoration does not establish behavior equivalence or undo external effects.',
            'Tests readable; tool write restrictions are not OS process isolation.'],
        'count_derivation':'4 source + 4 baseline + 5 arms*4 evaluation + 4 arms*4 recovery = 44 episodes; 44*8+5=357 calls'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--approved-manifest',type=Path)
    parser.add_argument('--save-preflight',type=Path)
    args=parser.parse_args(argv);design=preflight()
    if args.execute:
        if not args.approved_manifest or json.loads(args.approved_manifest.read_text(encoding='utf-8')) != design:
            raise ValueError('matching frozen preflight required before paid execution')
        try:
            require_isolated_execution()
        except ExecutionUnavailable as exc:
            parser.error(str(exc))
    if args.save_preflight:
        if args.save_preflight.exists():raise ValueError('preflight destination exists')
        atomic_json(args.save_preflight,design)
    print(json.dumps(design,ensure_ascii=False,indent=2),flush=True)
    if not args.execute:return 0
    identity=design['backend_identity']
    if not identity['model'] or not identity['base_url']:raise ValueError('explicit backend identity required')
    from experiments.lab.backends import build_backend
    backend=build_backend('openai',model=identity['model'],base_url=identity['base_url'],
                           timeout=identity['timeout'],temperature=.7,max_retries=0)
    sources,evaluation=selected_tasks()
    out=ROOT/'experiments/runs'/new_run_id('E12v2')
    result=run_pilot(sources,evaluation,backend,out,design_manifest=design)
    atomic_json(ROOT/'experiments/results'/f'{out.name}.json',result)
    return 0


if __name__=='__main__':raise SystemExit(main())
