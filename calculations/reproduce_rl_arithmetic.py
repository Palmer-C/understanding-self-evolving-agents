"""Recompute Appendix C into a new analysis artifact; preserve dated reports."""
import hashlib
import json
import math
from pathlib import Path
from appendix_c_worked import calculate

ROOT = Path(__file__).resolve().parents[1]

def compare(expected, actual, location='root'):
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            raise ValueError(f'{location}: keys differ')
        for key in expected:
            compare(expected[key], actual[key], f'{location}.{key}')
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise ValueError(f'{location}: lengths differ')
        for i, (left, right) in enumerate(zip(expected, actual)):
            compare(left, right, f'{location}[{i}]')
    elif isinstance(expected, (int, float)):
        if not math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f'{location}: values differ')
    elif expected != actual:
        raise ValueError(f'{location}: values differ')

def main():
    old = ROOT / 'calculations/appendix-c-worked-2026-09-30.json'
    result = calculate()
    compare(json.loads(old.read_text('utf-8')), result)
    output = dict(result=result, dated_report_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),
                  dated_report_matches=True, api_calls=0,
                  scope='Constructed two-action model, finite PPO and KL arithmetic; no training or empirical validation.')
    target = ROOT / 'analysis/rl-arithmetic-reproduction.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print('Appendix C arithmetic matches the preserved dated report; new analysis artifact written; API calls: 0.')

if __name__ == '__main__':
    main()
