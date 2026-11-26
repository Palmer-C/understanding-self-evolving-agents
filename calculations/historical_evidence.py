"""Read frozen E05 inputs and hash-bound historical audit data as bytes."""

import hashlib
import json
from pathlib import Path, PureWindowsPath
import os
import tempfile


E05_RUN = "E05v2-20260929T143245Z-d7a8db"
E05_DIGEST_LIST_SHA256 = "7827fc5d64d6fd7151b0391d7895974278d5c4320a5eae37c7398ad74e4e5eda"

BOUNDARY_RECORD = "calculations/e01-file-boundary-audit-2026-09-30.json"
READINESS_RECORD = "calculations/e12-readiness-audit-2026-09-30.json"
# Frozen Git LF bytes and the CRLF copies that were delivered.
RECORD_SHA256 = {
    BOUNDARY_RECORD: {
        "7f25fc3ff841e2bbf218e39d77b7806c43a2c53d1eafc581d9836dd9dec5f836",
        "22e6049145ee0b985341e1de9c96545ac7291d8c0d3fab8444d9118455565e58",
    },
    READINESS_RECORD: {
        "9794d0d26f4fcba8a876a5f006b2a6301c58fe8a9db06e3227a0964f4fa05d38",
        "eae545b4eef439e5941d3adbf53c2e0032a20dd9a1141a8301b7473be7be7098",
    },
}


def e05_source_identities(root, config):
    """Verify the source list and every file exactly as recorded for this one run."""
    if config["run_id"] != E05_RUN:
        raise ValueError("Unexpected E05 archive run ID")
    expected = config["design"]["source_sha256"]
    manifest = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode("ascii")
    if hashlib.sha256(manifest).hexdigest() != E05_DIGEST_LIST_SHA256:
        raise ValueError("Historical E05 source digest list differs from the sealed run")
    result = {}
    for name, recorded in expected.items():
        filename = "E05-v2.md" if name == "protocol" else name
        relative = Path("analysis", "historical-sources", E05_RUN, filename + ".txt")
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if digest != recorded:
            raise ValueError(f"Historical E05 source digest mismatch: {relative.as_posix()}")
        # Keep the documented audit fields as well as the lookup path.
        result[name] = {
            "sha256": digest,
            "recorded_sha256": recorded,
            "match": True,
            "lf_sha256": digest,
            "accepted_match": True,
            "match_mode": "raw",
            "archive_path": relative.as_posix(),
        }
    return result


def e05_trace_path(sequence_dir, recorded_path):
    """Resolve both recorded separator styles beneath the sequence directory."""
    relative = PureWindowsPath(recorded_path)
    if relative.anchor or not relative.parts or '..' in relative.parts:
        raise ValueError(f'Expected a relative E05 trace path: {recorded_path}')
    return sequence_dir.joinpath(*relative.parts)


def read_observation(root, relative):
    """Verify one of the two original read-only JSON records before parsing it."""
    allowed = RECORD_SHA256[relative]
    raw = (root / relative).read_bytes()
    if hashlib.sha256(raw).hexdigest() not in allowed:
        raise ValueError(f"Historical audit digest mismatch: {relative}")
    return json.loads(raw)


def write_reproduction(report, default, output):
    """Refresh the usual derived report atomically; an alternate must be a new file."""
    data = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        with output.open("x", encoding="utf-8") as dest:
            dest.write(data)
        return
    with tempfile.NamedTemporaryFile(dir=default.parent, prefix=default.name + ".",
                                     delete=False) as dest:
        temporary = Path(dest.name)
    try:
        temporary.write_text(data, encoding="utf-8")
        os.replace(temporary, default)
    finally:
        temporary.unlink(missing_ok=True)
