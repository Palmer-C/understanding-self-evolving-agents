"""Self-contained interface fixtures, not the absent historical JSON task catalog.

These labels and dummy files exercise sequencing and provenance only. They are
not executable problems, independently collected families, or sealed data.
"""
from experiments.lab.e01_v2_manifest import TaskSpec,ExperimentManifest

def manifest():
    phases={phase:tuple(f'fixture-{phase}-{i}' for i in range(n))
            for phase,n in [('prepare',2),('online',4),('transfer',6)]}
    specs=[]
    for phase,names in phases.items():
        for i,name in enumerate(names):
            family=('fixture-target-' if phase=='transfer' else 'fixture-source-')+str(i%2)
            prompt=f'SCRIPTED INTERFACE FIXTURE {name}; no candidate task or capability claim.'
            specs.append(TaskSpec(name,family,prompt,
                (('candidate.py','# No candidate process is executed.\n'),('statement.md',prompt)),
                (('final_cases.json','{"fixture_only":true}'),),('candidate.py',)))
    return ExperimentManifest(tuple(specs),phases['prepare'],phases['online'],phases['transfer'],1)
