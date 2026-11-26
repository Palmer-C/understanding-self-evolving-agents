"""Count E01 grid 4 lesson appearances in recorded requests, by phase.

The reader edition contains the eight training traces and a projection of the
first system step of each sealed trace. The full archive also verifies that
projection against the original 80 sealed traces and their file digests.
"""
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict

INDEX_FILE = "analysis/e01-grid4-prompt-index.csv"
INDEX_SHA256_LF = "895ec27c9f750fffe7b2672bfa8899bc1474a73c986b1848ac522e54b81b90aa"
READER_SEALED_SAMPLE = ("classstate-07", 0)
FIELDS = ["task_id", "repeat", "first_lesson", "second_lesson", "trace_sha256"]
HEADER = "\n\n以下是过去积累的注意事项：\n"


def prompt_lessons(trace, task, verdict, lesson_lines):
    if trace["task_id"] != task or type(verdict) is not bool or trace["verdict"] is not verdict:
        raise ValueError(f"Trace task or verdict mismatch for {task}")
    step = trace["steps"][0]
    if step["kind"] != "system":
        raise ValueError(f"Missing initial system prompt for {task}")
    prompt = step["content"]
    if HEADER not in prompt:
        return []
    if prompt.count(HEADER) != 1:
        raise ValueError(f"Ambiguous memory header for {task}")
    lines = prompt.split(HEADER)[1].splitlines()
    if not lines or any(line not in lesson_lines for line in lines):
        raise ValueError(f"Unknown lesson in the system prompt for {task}")
    return [lesson_lines[line] for line in lines]


def original_trace_matches(raw, expected):
    if hashlib.sha256(raw).hexdigest() == expected:
        return True
    # The archived byte digest includes Windows line endings. Git's text
    # checkout can supply LF instead. Only this reversible change is accepted.
    return b"\r" not in raw and hashlib.sha256(raw.replace(b"\n", b"\r\n")).hexdigest() == expected


def prompt_exposure(root, run, summary):
    lessons = summary["memory"]["grid4_lessons"]
    ids = list(range(len(lessons)))
    lesson_lines = {"- " + lesson["text"]: lesson["index"] for lesson in lessons}
    if list(lesson_lines.values()) != ids:
        raise ValueError("Grid 4 needs distinct lesson texts in archived order")
    traces = run / "traces/grid4"
    train_counts = Counter()
    for index, lesson in enumerate(lessons):
        task = lesson["source_task"]
        path = traces / "train" / f"{task}-e{index}" / "trace.json"
        selected = prompt_lessons(json.loads(path.read_bytes()), task, lesson["source_verdict"], lesson_lines)
        if selected != ids[:index]:
            raise ValueError(f"Unexpected training prompt history for {task}")
        train_counts.update(selected)

    index_text = (root / INDEX_FILE).read_text(encoding="ascii")
    if hashlib.sha256(index_text.encode("ascii")).hexdigest() != INDEX_SHA256_LF:
        raise ValueError("Sealed-prompt projection digest mismatch")
    reader = csv.DictReader(io.StringIO(index_text))
    if reader.fieldnames != FIELDS:
        raise ValueError("Unrecognized sealed-prompt columns")
    verdicts = summary["verdicts"]["grid4"]
    expected = {(task, i) for task, values in verdicts.items() for i in range(len(values))}
    seen = set()
    tasks_by_lesson = defaultdict(set)
    sealed_counts = Counter()
    sealed = traces / "sealed"
    require_all = (root / "analysis/all-evaluation-records.csv").is_file()
    originals_checked = 0
    for row in reader:
        task, repeat = row["task_id"], int(row["repeat"])
        key = task, repeat
        if key not in expected or key in seen:
            raise ValueError(f"Unexpected or duplicate sealed request {key}")
        seen.add(key)
        selected = [int(row["first_lesson"]), int(row["second_lesson"])]
        if len(set(selected)) != 2 or any(i not in ids for i in selected):
            raise ValueError(f"Invalid lesson pair for {key}")
        path = sealed / f"{task}-r{repeat}" / "trace.json"
        if require_all or key == READER_SEALED_SAMPLE or path.is_file():
            raw = path.read_bytes()
            if not original_trace_matches(raw, row["trace_sha256"]):
                raise ValueError(f"Original sealed trace digest mismatch for {key}")
            if prompt_lessons(json.loads(raw), task, verdicts[task][repeat], lesson_lines) != selected:
                raise ValueError(f"Sealed prompt does not match projection for {key}")
            originals_checked += 1
        sealed_counts.update(selected)
        for i in selected:
            tasks_by_lesson[i].add(task)
    if seen != expected:
        raise ValueError("Incomplete sealed-prompt projection")
    return {
        "index_sha256_lf": INDEX_SHA256_LF,
        "training_prompts": len(lessons),
        "sealed_tasks": len(verdicts),
        "sealed_prompts": len(seen),
        "sealed_originals_checked": originals_checked,
        "lessons": [
            {"index": i, "source_task": lesson["source_task"],
             "later_training_prompts": train_counts[i], "sealed_prompts": sealed_counts[i],
             "distinct_sealed_tasks": len(tasks_by_lesson[i])}
            for i, lesson in enumerate(lessons)
        ],
    }
