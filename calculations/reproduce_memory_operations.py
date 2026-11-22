"""Re-run the published local fixture without replacing its historical log."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from calculations.ch06_operation_demo import run
result=run()
if result['passed']!=7 or result['model_calls']!=0:raise ValueError('Teaching fixture coverage changed')
source=ROOT/'calculations/ch06_operation_demo.py'
result['script_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
result['classification']='new deterministic interface/arithmetic replay, no learned policy or E03b run'
result['amac_arithmetic']={'latency_reduction_percent':100*(3831-2644)/3831,'F1_difference':(.583-.476),'opposite_unit_vectors_cosine':-1,'novelty_one_minus_cosine':2,'note':'Arithmetic from cited rounded table values or explicit teaching vectors; not new admission predictions'}
out=ROOT/'analysis/memory-operations-reproduction.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'local_checks':result['passed'],'model_calls':0,'output':out.relative_to(ROOT).as_posix()}))
