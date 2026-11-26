"""Read the six archived benchmarks used in the book's AFlow table."""

import csv
import hashlib
import io
import json
import re
import string
import tarfile
from collections import Counter
from decimal import Decimal
from pathlib import PurePosixPath


ARCHIVE_SHA256 = "f460f9c9218216f6fbaf553f4f215248317b7f37dd715ae146cd38199eabe5f7"
PAPER_SCORES = {"HotpotQA": "73.5", "DROP": "80.6", "HumanEval": "94.7",
                "MBPP": "83.4", "GSM8K": "93.5", "MATH": "56.2"}
MATH_VALIDATION = "results/MATH/graphs/round_5/0.57143_20240928_042911.csv"
ANSWER_DATASETS = ("DROP", "GSM8K", "HotpotQA")
SCORE_TOLERANCE = 1e-12
NUMBER = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
ARTICLES = re.compile(r"\b(?:a|an|the)\b")
REMOVE_PUNCTUATION = str.maketrans("", "", string.punctuation)


def answer_tokens(value):
    return ARTICLES.sub(" ", value.lower().translate(REMOVE_PUNCTUATION)).split()


def token_f1(reference, prediction):
    overlap = sum((Counter(reference) & Counter(prediction)).values())
    return 2 * overlap / (len(reference) + len(prediction)) if overlap else 0.0


def check_answers(text, dataset):
    """Compare saved text with the historical AFlow grader for these three datasets."""
    rows = 0
    mismatches = []
    multiple_full_credit = []
    largest_error = 0.0
    for rows, record in enumerate(csv.DictReader(io.StringIO(text, newline="")), start=1):
        reference, prediction = record["expected_output"], record["prediction"]
        if dataset == "GSM8K":
            numbers = NUMBER.findall(prediction)
            score = 0.0
            if numbers:
                last = float(numbers[-1].replace(",", ""))
                score = float(abs(float(reference) - last) <= 1e-6)
        elif dataset == "DROP":
            references = [answer_tokens(value) for value in reference.split("|") if value.strip()]
            predictions = [answer_tokens(value) for value in prediction.split("|")]
            score = max((token_f1(r, p) for r in references for p in predictions), default=0.0)
            distinct_answers = {tuple(tokens) for tokens in predictions if tokens}
            if score == 1.0 and len(distinct_answers) > 1:
                multiple_full_credit.append(rows + 1)
        else:
            score = token_f1(answer_tokens(reference), answer_tokens(prediction))
        error = abs(score - float(record["score"]))
        largest_error = max(largest_error, error)
        if error > SCORE_TOLERANCE:
            mismatches.append(rows + 1)
    check = {"rows": rows, "matching_rows": rows - len(mismatches),
             "absolute_tolerance": SCORE_TOLERANCE, "max_absolute_difference": largest_error,
             "mismatch_csv_records": mismatches}
    if dataset == "DROP":
        check["multiple_prediction_full_credit_csv_records"] = multiple_full_credit
    return check


def score_file(raw, dataset):
    text = raw.decode("utf-8-sig")
    records = csv.reader(io.StringIO(text, newline=""))
    header = next(records)
    # Two HumanEval CSVs start with a one-cell score before the real header.
    if len(header) == 1:
        header = next(records)
    score_col = header.index("score")
    id_fields = {"DROP": ["inputs"], "HotpotQA": ["question", "context"]}.get(dataset, ["question"])
    id_cols = [header.index(field) for field in id_fields]
    identifiers = []
    score_sum = Decimal(0)
    max_cost = Decimal(0)
    cost_col = header.index("cost")
    for row in records:
        score_sum += Decimal(row[score_col])
        identifier = [row[col].replace("\r\n", "\n").replace("\r", "\n").strip() for col in id_cols]
        identifiers.append(hashlib.sha256(json.dumps(identifier, ensure_ascii=False).encode()).hexdigest())
        if dataset == "HumanEval":
            max_cost = max(max_cost, Decimal(row[cost_col]))
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(identifiers),
        "score_sum": str(score_sum),
        "question_multiset_sha256": hashlib.sha256("\n".join(sorted(identifiers)).encode()).hexdigest(),
        "score_mean": str(score_sum / len(identifiers)),
        **({"max_recorded_cost": str(max_cost)} if dataset == "HumanEval" else {}),
        **({"answer_score_check": check_answers(text, dataset)} if dataset in ANSWER_DATASETS else {}),
    }


def read_archive(path):
    """Only read data from the known release; no archive member is installed."""
    datasets = {name: [] for name in PAPER_SCORES}
    validation_hash = None
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != ARCHIVE_SHA256:
            raise ValueError("AFlow archive differs from the edition identified in the reader guide.")
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r|gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                parts = PurePosixPath(member.name).parts
                if member.name == MATH_VALIDATION:
                    validation_hash = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                elif (len(parts) == 5 and parts[0] == "results" and parts[1] in datasets
                      and parts[2] == "graphs_test" and parts[-1].endswith(".csv")):
                    record = score_file(tar.extractfile(member).read(), parts[1])
                    datasets[parts[1]].append({"member": member.name, **record})

    if validation_hash is None:
        raise ValueError("Missing reference CSV for the MATH validation run.")
    summary = {}
    for name, files in datasets.items():
        if len(files) != 3:
            raise ValueError(f"Expected three published test CSVs for {name}.")
        files.sort(key=lambda item: item["member"])
        matched_questions = len({f["question_multiset_sha256"] for f in files}) == 1
        duplicates = [f["member"] for f in files if f["sha256"] == validation_hash]
        report = {"paper_table_1": PAPER_SCORES[name], "files": files, "same_questions": matched_questions,
                  "also_in_math_validation": duplicates, "archived_three_run_mean_percent": None}
        if matched_questions and not duplicates:
            mean = sum(Decimal(f["score_mean"]) for f in files) * 100 / len(files)
            report["archived_three_run_mean_percent"] = str(mean.quantize(Decimal("0.1")))
        if name == "HumanEval":
            costs = [Decimal(f["max_recorded_cost"]) for f in files]
            report["mean_of_run_max_costs"] = str(sum(costs) / len(costs))
        summary[name] = report
    checks = [record["answer_score_check"] for dataset in ANSWER_DATASETS for record in datasets[dataset]]
    return {"sha256": ARCHIVE_SHA256, "math_validation_member": MATH_VALIDATION,
            "math_validation_sha256": validation_hash, "benchmarks": summary,
            "answer_score_check": {"datasets": list(ANSWER_DATASETS), "absolute_tolerance": SCORE_TOLERANCE,
                                  "matching_rows": sum(check["matching_rows"] for check in checks),
                                  "rows": sum(check["rows"] for check in checks)}}
