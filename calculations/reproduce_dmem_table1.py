"""Check D-MEM Table 1 against three fixed local JSON files (offline, conv-26).

Supply the original downloaded bytes from the D-MEM and LoCoMo repositories.
Only the 47 adversarial answers are also checked by LoCoMo's refusal phrase rule.
The result is a summary; no questions, answers or conversation text are exported.
"""
import argparse
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculations.historical_evidence import write_reproduction

# Raw Git blob contents. Re-serializing JSON or changing line endings changes the identity.
SOURCE_SHA256 = {
    "LoCoMo": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
    "A-MEM": "3df76f75fe850020002dd7fff8c78dbfbcdd7a96428393452fb073037adedce8",
    "D-MEM": "3c069d2416abf752dc1b16a34b5280a50126a1e56c208e38f55f47651b502776",
}
CATEGORY_NAMES = {1: "multi-hop", 2: "temporal", 3: "open domain", 4: "single-hop", 5: "adversarial"}
REFUSAL_PHRASES = ("no information available", "not mentioned")
SAMPLE = "conv-26"


def load_fixed(path, source):
    if not path.is_file():
        raise ValueError(f"{source}: expected a regular local JSON file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256[source]:
        raise ValueError(f"{source}: SHA-256 mismatch; use the original bytes from the pinned revision")
    return json.loads(data)


def index_questions(rows):
    indexed = {}
    for row in rows:
        question = row["question"]
        if not isinstance(question, str) or not question or question in indexed:
            raise ValueError("Expected a unique, nonempty question in each row")
        indexed[question] = row
    return indexed


def word_set_f1(prediction, reference):
    # D-MEM utils.py::simple_tokenize and calculate_metrics use four punctuation
    # replacements, then unique tokens. Numeric references are strings at this step.
    def tokens(value):
        return set(re.sub(r"[.,!?]", " ", str(value).lower()).split())

    predicted = tokens(prediction)
    expected = tokens(reference)
    if not predicted or not expected:
        return Fraction(0)
    return Fraction(2 * len(predicted & expected), len(predicted) + len(expected))


def score_method(original, rows):
    results = index_questions(rows)
    if results.keys() != original.keys():
        raise ValueError("Result questions differ from the original conversation")
    by_category = defaultdict(list)
    refused = set()
    for question, item in original.items():
        row = results[question]
        category = item["category"]
        if row["category"] != category or category not in CATEGORY_NAMES:
            raise ValueError("Result category differs from the original label")
        key = "adversarial_answer" if category == 5 else "answer"
        reference = item[key]
        if type(row["reference"]) is not type(reference) or row["reference"] != reference:
            raise ValueError("Result reference differs from the original answer or adversarial distractor")
        f1 = word_set_f1(row["prediction"], reference)
        if not math.isclose(float(f1), row["metrics"]["f1"], rel_tol=0, abs_tol=1e-12):
            raise ValueError("Recomputed word-set F1 differs from the saved row")
        by_category[category].append(f1)
        if category == 5 and any(p in row["prediction"].lower() for p in REFUSAL_PHRASES):
            refused.add(question)
    all_scores = [value for values in by_category.values() for value in values]
    summary = {
        "questions": len(all_scores),
        "overall_word_set_f1": float(mean(all_scores)),
        "by_locomo_category": {
            str(category): {"label": CATEGORY_NAMES[category], "questions": len(values),
                            "word_set_f1": float(mean(values))}
            for category, values in sorted(by_category.items())
        },
        "category_5_official_phrase_hits": len(refused),
    }
    return summary, refused


def table1_report(locomo, a_mem, d_mem):
    samples = [sample for sample in locomo if sample["sample_id"] == SAMPLE]
    if len(samples) != 1:
        raise ValueError(f"Expected one LoCoMo conversation with ID {SAMPLE}")
    original = index_questions(samples[0]["qa"])
    scores = {}
    hits = {}
    for method, result in (("A-MEM", a_mem), ("D-MEM", d_mem)):
        if result["method"] != method:
            raise ValueError(f"Expected {method} predictions")
        scores[method], hits[method] = score_method(original, result["results"])
    a_hits, d_hits = hits["A-MEM"], hits["D-MEM"]
    n = scores["A-MEM"]["by_locomo_category"]["5"]["questions"]
    return {
        "scope": "Stored predictions only, one conversation. LoCoMo phrase check applies only to category 5.",
        "sample_id": SAMPLE,
        "source_commits": {"D-MEM result files": "68410d0568b2ccbdc859f451c3494a72e814c505",
                           "D-MEM scoring code": "e6f4043daf099cfb39263c865972661d89e5a44b",
                           "LoCoMo data and scoring code": "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"},
        "verified_input_sha256": SOURCE_SHA256,
        "paper_table1_overall_f1_as_printed": {"A-MEM": 0.336, "D-MEM": 0.369},
        "scores_from_predictions": scores,
        "category_5_official_phrase_rule": {
            "phrases": list(REFUSAL_PHRASES), "questions": n,
            "both": len(a_hits & d_hits), "a_mem_only": len(a_hits - d_hits),
            "d_mem_only": len(d_hits - a_hits), "neither": n - len(a_hits | d_hits),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locomo", type=Path, required=True, help="LoCoMo data/locomo10.json")
    parser.add_argument("--a-mem", type=Path, required=True, help="D-MEM release: A-MEM noise75 result")
    parser.add_argument("--d-mem", type=Path, required=True, help="D-MEM release: D-MEM noise75 result")
    parser.add_argument("--output", type=Path, help="write to a new JSON file; default is standard output")
    args = parser.parse_args(argv)
    try:
        report = table1_report(load_fixed(args.locomo, "LoCoMo"),
                               load_fixed(args.a_mem, "A-MEM"), load_fixed(args.d_mem, "D-MEM"))
        if args.output is None:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            write_reproduction(report, None, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot reproduce D-MEM Table 1: {exc}\n")


if __name__ == "__main__":
    main()
