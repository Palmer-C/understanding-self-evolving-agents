"""Exact constructed counterexample: one-minus-cosine need not be subadditive."""
from fractions import Fraction as F
from pathlib import Path
import json,hashlib

def run():
    # u=(1,0), v=(1/2,sqrt(3)/2), w=(-1/2,sqrt(3)/2).
    uv=F(1,2);vw=F(1,2)*F(-1,2)+F(3,4);uw=F(-1,2)
    assert F(1,4)+F(3,4)==1
    a,b,c=(1-x for x in (uv,vw,uw))
    assert (a,b,c)==(F(1,2),F(1,2),F(3,2)) and c>a+b
    return {'identity':'exact geometric construction; not model data or an unconditional refutation of SSGM',
        'vectors':['(1,0)','(1/2,sqrt(3)/2)','(-1/2,sqrt(3)/2)'],
        'distances':{'u_v':str(a),'v_w':str(b),'u_w':str(c),'two_step_sum':str(a+b)},
        'conclusion':'adjacent one-minus-cosine bounds do not alone imply a linear cumulative bound',
        'required_distinction':'increment bound relative to a fixed reference is an additional assumption',
        'source_equation':'SSGM arXiv:2603.11768 Eq.4, Theorem 1 and its stated additive-bound assumption',
        'api_calls':0,'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False,indent=2))
