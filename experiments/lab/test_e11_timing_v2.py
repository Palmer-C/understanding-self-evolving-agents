import json,unittest
from pathlib import Path
from .e11_timing_v2 import TimingController

def observe(c,vs,texts=None):
    return [c.observe(episode_id=f'ep{i}',verdict=v,task_text=(texts[i] if texts else 'same task')) for i,v in enumerate(vs)]

class TimingTests(unittest.TestCase):
    def test_periodic_after_p_completed(self):
        x=observe(TimingController('periodic',8),[True]*8)
        self.assertEqual([i for i,r in enumerate(x) if r['decision']=='attempt_reserved'],[1,3,5])
        self.assertEqual(x[-1]['decision'],'terminal_no_future_task')
    def test_current_error_not_sparse_memory(self):
        x=observe(TimingController('event',6),[True,False,False,False])
        self.assertEqual([r['error_run'] for r in x],[0,1,2,3])
        self.assertIn('error_run',x[-1]['trigger_reasons'])
    def test_drift_warmup_is_missing_not_zero(self):
        x=observe(TimingController('event',8),[True,True,False,False])
        self.assertIsNone(x[2]['absolute_failure_shift'])
        self.assertEqual(x[3]['absolute_failure_shift'],1)
    def test_improvement_also_triggers_absolute_shift(self):
        x=observe(TimingController('event',8),[False,False,True,True])
        self.assertEqual(x[-1]['absolute_failure_shift'],1)
    def test_input_novelty_not_old_lesson(self):
        x=observe(TimingController('event',5),[True]*3,['aaaa','aaaa','bbbb'])
        self.assertEqual([r['input_novelty'] for r in x],[1,0,1])
    def test_write_attempt_bound(self):
        x=observe(TimingController('per_task',5,write_attempt_limit=1),[True]*5)
        self.assertEqual([r['decision'] for r in x],['attempt_reserved']+['write_attempt_limit']*3+['terminal_no_future_task'])
        self.assertEqual(x[-1]['attempts_reserved'],1)
    def test_no_refund_on_missing_publish(self):
        c=TimingController('per_task',3,write_attempt_limit=1)
        # No generator/publisher is called; grant is still consumed.
        self.assertEqual(c.observe(episode_id='a',verdict=True,task_text='x')['decision'],'attempt_reserved')
        self.assertEqual(c.observe(episode_id='b',verdict=True,task_text='y')['decision'],'write_attempt_limit')
    def test_duplicate_rejected(self):
        c=TimingController('event',2);c.observe(episode_id='a',verdict=True,task_text='x')
        with self.assertRaises(ValueError):c.observe(episode_id='a',verdict=False,task_text='x')
    def test_invalid_observation_does_not_advance(self):
        c=TimingController('event',2)
        with self.assertRaises(ValueError):c.observe(episode_id='a',verdict=None,task_text='x')
        self.assertEqual(c.observe(episode_id='a',verdict=True,task_text='x')['episode_index'],0)
    def test_extra_episode_rejected(self):
        c=TimingController('event',1);observe(c,[True])
        with self.assertRaises(ValueError):c.observe(episode_id='next',verdict=True,task_text='x')
    def test_empty_observation_rejected(self):
        for text in ['', ' ',None]:
            with self.assertRaises(ValueError):TimingController('event',2).observe(episode_id='a',verdict=True,task_text=text)
    def test_controller_state_isolated(self):
        c=TimingController('event',3);observe(c,[False,False])
        self.assertEqual(observe(TimingController('event',3),[True])[0]['error_run'],0)
    def test_zero_write_budget(self):
        self.assertEqual(observe(TimingController('event',2,write_attempt_limit=0),[True])[0]['decision'],'write_attempt_limit')
    def test_invalid_configuration(self):
        for k,v in [('period',0),('sequence_length',0),('drift_window',True),('write_attempt_limit',-1),('novelty_threshold',float('nan')),('drift_threshold',0),('error_threshold',.5)]:
            args={'arm':'event','sequence_length':4};args[k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):TimingController(**args)
    def test_model_monitor_cost_zero_cpu_recorded(self):
        r=observe(TimingController('event',2),[True])[0]
        self.assertEqual(r['signal_model_calls'],0);self.assertGreaterEqual(r['monitor_seconds'],0)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TimingTests))
    p=Path(__file__).resolve().parents[2]/'calculations/e11-timing-checks-2026-09-30.json'
    p.write_text(json.dumps({'identity':'offline synthetic checks; no capability evidence','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'live_runner_integrated':False},indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
