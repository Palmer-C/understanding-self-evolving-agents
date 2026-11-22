"""Exact two-action teaching model and finite KL/PPO arithmetic; no training."""
from fractions import Fraction as F
import json, math
from pathlib import Path


def calculate():
    p=F(1,4)
    def moments(b):
        values=[(1-p)*(1-b), -p*(0-b)]
        mean=p*values[0]+(1-p)*values[1]
        var=p*(values[0]-mean)**2+(1-p)*(values[1]-mean)**2
        assert mean==F(3,16)
        return {'baseline':float(b),'gradient_if_action1':float(values[0]),
                'gradient_if_action0':float(values[1]),'mean':float(mean),'variance':float(var)}
    rows=[moments(b) for b in (F(0),F(1,4),F(3,4),F(2))]
    assert [x['variance'] for x in rows]==[.10546875,.046875,0.,.29296875]
    beta=math.log(3); weights=[.75,.25*math.exp(beta)]; new=[x/sum(weights) for x in weights]
    assert all(math.isclose(x,.5) for x in new)
    kl=sum(x*math.log(x/y) for x,y in zip(new,[.75,.25]))
    objective=new[1]-kl/beta
    ppo=[]
    for ratio,advantage in [(1.5,1),(1.5,-1),(.5,1),(.5,-1)]:
        clipped=max(.8,min(1.2,ratio))
        ppo.append({'ratio':ratio,'advantage':advantage,'unclipped':ratio*advantage,
                    'clipped':clipped*advantage,'objective':min(ratio*advantage,clipped*advantage)})
    assert [x['objective'] for x in ppo]==[1.2,-1.5,.5,-.8]
    return {'identity':'constructed two-action model; deterministic derivation; no model training',
            'action1_probability':float(p),'deterministic_rewards':[1,0],
            'gradient_baselines':rows,'jit_kl_example':{'reference':[.75,.25],'advantages':[0,1],
              'beta':beta,'penalty_coefficient':1/beta,'updated':new,'kl_new_to_reference':kl,
              'objective_new':objective,'objective_reference':.25},
            'ppo_examples':ppo,'api_calls':0}


if __name__=='__main__':
    result=calculate()
    Path(__file__).with_name('appendix-c-worked-2026-09-30.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
