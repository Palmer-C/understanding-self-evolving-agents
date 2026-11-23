"""E05 v2 exploratory runner. Offline preflight is available.

Live execution requires an OS-isolated candidate executor.

New IDs and per-sequence checkpoints prevent mixing with the legacy E05 pilot.
See experiments/protocols/E05-v2.md for exact endpoints and limitations.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.lab.e05_v2 import VERSION, admit, digest, eligible_sequences, observed_costs, source_files
from experiments.lab.e05_arms import ARMS, RevisionBudget
from experiments.lab.run_e05 import load_all_tasks, load_entries, git_head, run_episode_isolated
from experiments.lab.e01_arms import memory_block
from experiments.lab.static_agent import StaticAgent, SYSTEM_PROMPT
from experiments.lab.trace import new_run_id
from experiments.lab.budget import Budget
from experiments.lab.sandbox import ExecutionUnavailable, require_isolated_execution


def atomic_json(path, data):
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def ledger():
    return dict(episodes=0, repair_episodes=0, calls=0, build_calls=0, reuse_calls=0,
                repair_calls=0, prompt_tokens=0, completion_tokens=0, wall_seconds=0.0,
                admitted=0, rejected=0, revision_used=0, revision_denied=0,
                retrieved=0, contract_checks=0)


def absorb(led, trace, bucket):
    led['repair_episodes' if bucket=='repair' else 'episodes'] += 1
    for key in ('calls','prompt_tokens','completion_tokens','wall_seconds'):
        led[key] += trace.usage.get(key,0)
    led[bucket+'_calls'] += trace.usage.get('calls',0)


def run_sequence(arm, k, tasks, backend, seed, out_dir, entries, u=1):
    if getattr(backend, 'name', None) == 'openai-chat':
        require_isolated_execution()
    out_dir.mkdir(parents=True, exist_ok=True)
    rb = RevisionBudget(u=u)  # One budget per family x grid x repeat sequence.
    led, verdicts, events, skill = ledger(), {}, [], None
    for j, task in enumerate(tasks[:k+1]):
        bucket = 'build' if j==0 else 'reuse'
        block = ''
        if j and arm!='replan' and skill is not None:
            block = memory_block([skill.render()], header='Reference code passed its origin task only; adapt and test it for this task:')
            led['retrieved'] += 1
        agent = StaticAgent(backend=backend,system_prompt=SYSTEM_PROMPT+block,name=f'{VERSION}:{arm}:{bucket}')
        attempt_dir = out_dir / f'{j:02d}-{task.task_id}'
        trace = run_episode_isolated(agent,task,seed+13*j,attempt_dir)
        absorb(led,trace,bucket)
        verdicts[task.task_id] = bool(trace.verdict)  # Never replace first verdict with repair success.
        event = {'task_id':task.task_id,'split':task.split,'role':bucket,
                 'first_verdict':bool(trace.verdict),'retrieved':bool(block),
                 'trace':str(attempt_dir.relative_to(out_dir)/'trace.json')}
        if j==0 and arm!='replan':
            led['contract_checks'] += 1
            skill, reason = admit(task,trace,entries.get(task.task_id,''))
            led['admitted' if skill else 'rejected'] += 1
            event['origin_admission'] = reason
        if j>0 and arm=='dynamic_skill' and not trace.verdict:
            if rb.spend():
                # An explicit extra repair attempt, accounted for separately.
                repaired_task = replace(task,files={**task.files,**source_files(task,trace)})
                repair_agent = StaticAgent(backend=backend,system_prompt=SYSTEM_PROMPT+block+
                                          '\nThe previous candidate failed verification. Repair and test it.',
                                          name=f'{VERSION}:{arm}:repair')
                repaired = run_episode_isolated(repair_agent,repaired_task,seed+13*j+1,attempt_dir/'repair')
                absorb(led,repaired,'repair')
                led['contract_checks'] += 1
                candidate, reason = admit(repaired_task,repaired,entries.get(task.task_id,''))
                led['admitted' if candidate else 'rejected'] += 1
                if candidate is not None:
                    skill = candidate
                event.update(repair_verdict=bool(repaired.verdict),revision_admission=reason)
            else:
                event['revision_denied'] = True
        events.append(event)
        atomic_json(out_dir/'in-progress.json',{'events':events,'ledger':led,
                    'revision_used':rb.used,'revision_denied':rb.over_budget,
                    'skill':skill.as_dict() if skill else None,
                    'status':'incomplete_sequence_do_not_merge'})
    led['revision_used'],led['revision_denied']=rb.used,rb.over_budget
    return {'arm':arm,'k':k,'family':tasks[0].family,'seed':seed,
            'verdicts':verdicts,'events':events,'ledger':led,
            'final_skill':skill.as_dict() if skill else None}


def summarize(config, completed):
    totals = {}
    for result in completed.values():
        key=f"{result['arm']}|k{result['k']}"
        led=totals.setdefault(key,ledger())
        for metric,value in result['ledger'].items():
            led[metric] += value
    return {'config':config,'completed_sequences':len(completed),'ledgers':totals,
            'static_costs':observed_costs(totals,config['grid']),
            'dynamic_costs':observed_costs(totals,config['grid'],'dynamic_skill'),
            'sequences':completed,'status':'exploratory_no_proposition_update',
            'limitations':['Only 8 related template families; repeated calls are not independent families.',
                           'First-attempt outcomes exclude repair success; repair expense remains in total.',
                           'No formal non-inferiority or full workflow timing claim.',
                           'No validated return-contract drift or unchanged-code misuse detector.',
                           'Provider aliases and recorded seeds do not ensure reproducibility.']}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute',action='store_true')
    ap.add_argument('--resume',type=Path)
    ap.add_argument('--repeats',type=int,default=2)
    ap.add_argument('--families',default='')
    ap.add_argument('--grid',default='0,1,2,4')
    ap.add_argument('--temperature',type=float,default=.7)
    args=ap.parse_args(argv)
    if args.execute:
        try:
            require_isolated_execution()
        except ExecutionUnavailable as exc:
            ap.error(str(exc))
    tasks=load_all_tasks()
    families=sorted(set(args.families.split(',')) if args.families else {t.family for t in tasks})
    grid=tuple(int(k) for k in args.grid.split(','))
    if args.repeats<1: ap.error('repeats must be positive')
    fams=eligible_sequences(tasks,families,grid)
    selected={f:ts[:max(grid)+1] for f,ts in fams.items()}
    entries=load_entries()
    sources=['run_e05_v2.py','e05_v2.py','run_e05.py','e05_arms.py','run_e01.py',
             'e01_arms.py','static_agent.py','backends.py','budget.py','sandbox.py','tasks.py','taskset_spec.py','trace.py']
    hashes={n:hashlib.sha256((ROOT/'experiments/lab'/n).read_bytes()).hexdigest() for n in sources}
    hashes['protocol']=hashlib.sha256((ROOT/'experiments/protocols/E05-v2.md').read_bytes()).hexdigest()
    design={'version':VERSION,'grid':sorted(grid),'families':families,'repeats':args.repeats,
            'temperature':args.temperature,'u_per_sequence':1,'base_seed':20260929,
            'budget':Budget().as_dict(),'source_sha256':hashes,
            'task_manifest':{f:[{'id':t.task_id,'split':t.split,'entry':entries.get(t.task_id,''),
                                'sha256':digest(vars(t))} for t in ts] for f,ts in selected.items()}}
    primary=len(families)*args.repeats*len(ARMS)*sum(k+1 for k in grid)
    repairs=len(families)*args.repeats*sum(k>0 for k in grid)
    print(json.dumps({'design':design,'primary_episodes':primary,'max_repair_episodes':repairs,
                      'max_successful_generate_calls':8*(primary+repairs),
                      'network_attempt_bound':None,
                      'note':'API internal retries and overshooting token calls prevent a monetary hard cap.'},ensure_ascii=False),flush=True)
    if not args.execute:
        return 0
    # Preflight/compatibility checks precede backend construction and all API calls.
    if args.resume:
        out=args.resume.resolve()
        if out.parent != (ROOT/'experiments/runs').resolve():
            raise ValueError('resume path must be an immediate child of experiments/runs')
        config=json.loads((out/'config.json').read_text(encoding='utf-8'))
        if config['design']!=design: raise ValueError('design/source/task mismatch; use a new run')
        if (out/'summary.json').exists(): raise ValueError('already completed')
    else:
        out=ROOT/'experiments/runs'/new_run_id('E05v2')
        out.mkdir(parents=True,exist_ok=False)
        config={'design':design,'grid':sorted(grid),'run_id':out.name,'git_head':git_head(),
                'started_at':datetime.now(timezone.utc).isoformat()}
        atomic_json(out/'config.json',config)
    from experiments.lab.backends import build_backend
    backend=build_backend('openai',temperature=args.temperature)
    identity={'model':backend.model,'base_url':backend.base_url,'max_retries':backend.max_retries}
    if 'backend' in config and config['backend']!=identity:
        raise ValueError('backend identity changed; use a new run')
    config['backend']=identity
    atomic_json(out/'config.json',config)
    completed={}
    for arm in ARMS:
        for k in sorted(grid):
            for family,seq in fams.items():
                for r in range(args.repeats):
                    key=f'{arm}-k{k}-{family}-r{r}'
                    seqdir=out/'sequences'/key
                    done=seqdir/'complete.json'
                    if done.exists():
                        result=json.loads(done.read_text(encoding='utf-8'))
                    else:
                        # Preserve incomplete attempts; never overwrite or silently repeat them.
                        if seqdir.exists():
                            raise RuntimeError(f'incomplete sequence {key}: audit attempts and costs before resuming')
                        try:
                            result=run_sequence(arm,k,seq,backend,20260929+7919*r,seqdir,entries)
                        except Exception as exc:
                            seqdir.mkdir(parents=True,exist_ok=True)
                            atomic_json(seqdir/'interruption.json',{
                                'exception_type':type(exc).__name__,
                                'message':str(exc),
                                'at':datetime.now(timezone.utc).isoformat(),
                                'backend_retries_this_process':getattr(backend,'retries',None),
                                'billing':'Interrupted API attempt costs may be unknown; do not impute zero.'})
                            raise
                        atomic_json(done,result)
                    completed[key]=result
                    atomic_json(out/'partial.json',{'config':config,'completed':list(completed)})
                    print('COMPLETED',key,flush=True)
    result=summarize(config,completed)
    result['finished_at']=datetime.now(timezone.utc).isoformat()
    result['backend_retries_this_process']=getattr(backend,'retries',None)
    result['backend_retry_scope']='current process only; earlier segments require separate reconciliation'
    result['model']=getattr(backend,'model','unknown')
    atomic_json(out/'summary.json',result)
    atomic_json(ROOT/'experiments/results'/f'{out.name}.json',result)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
