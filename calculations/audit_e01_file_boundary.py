"""Read the hash-bound September 30 file-boundary observation. Runs no checks on the host."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculations.historical_evidence import BOUNDARY_RECORD, read_observation


def audit(root=ROOT):
    return read_observation(root, BOUNDARY_RECORD)


if __name__ == "__main__":
    print(json.dumps({"historical_record": BOUNDARY_RECORD, "observation": audit()},
                     ensure_ascii=False, indent=2))
