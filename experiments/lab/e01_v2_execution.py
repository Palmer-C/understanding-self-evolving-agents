"""E01 v2 separate-oracle contract for JSON-function tasks; OFFLINE ONLY.

No subprocess, import of candidate modules, backend, Docker, or live adapter.
These checks prevent accidental protocol leakage, not malicious host access.
The JSON-function interface is a new task contract, not a silent conversion of
historical unittest tasks. Real process isolation is an unmet prerequisite.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from .e01_v2_design import canonical, digest, identifier, integer
from .e01_v2_manifest import TaskSpec, sha256_text


class ExecutionUnavailable(RuntimeError): pass
class ProtocolViolation(ValueError): pass


def strict_json(raw):
    """Finite JSON, no repeated keys. Bool and number remain distinct in scoring."""
    if type(raw) is not bytes: raise ProtocolViolation('JSON bytes required')
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ProtocolViolation('duplicate JSON key')
            out[key] = value
        return out
    def constant(value): raise ProtocolViolation('nonfinite JSON value')
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
        canonical(result)  # Also rejects overflowing exponent -> infinity.
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolViolation('invalid finite UTF-8 JSON') from exc
    return result


@dataclass(frozen=True)
class ExecutionLimits:
    wall_ms: int = 2000
    memory_bytes: int = 268435456
    pids: int = 32
    input_bytes: int = 65536
    output_bytes: int = 65536
    stderr_bytes: int = 16384
    source_bytes: int = 262144

    def __post_init__(self):
        for name, value in vars(self).items(): integer(value, name, 1)


@dataclass(frozen=True)
class CandidateBundle:
    task_id: str
    candidate_id: str
    public_files: tuple[tuple[str, str], ...]

    def __post_init__(self):
        from .e01_v2_file_boundary import relative_name
        identifier(self.task_id); identifier(self.candidate_id)
        if type(self.public_files) is not tuple or not self.public_files:
            raise ProtocolViolation('immutable public file tuple required')
        names=[]
        for pair in self.public_files:
            if type(pair) is not tuple or len(pair)!=2 or type(pair[1]) is not str:
                raise ProtocolViolation('immutable name/text pair required')
            if relative_name(pair[0])!=pair[0]: raise ProtocolViolation('canonical path required')
            names.append(pair[0].casefold())
        if len(names)!=len(set(names)): raise ProtocolViolation('duplicate file identity')

    def sha256(self):
        return digest({'task_id': self.task_id, 'candidate_id': self.candidate_id,
                       'public_files': sorted(self.public_files)})


def build_candidate(task, candidate_id, replacements, limits):
    if type(task) is not TaskSpec or type(limits) is not ExecutionLimits:
        raise ProtocolViolation('typed task and limits required')
    if type(replacements) is not dict or not set(replacements)<=set(task.writable):
        raise ProtocolViolation('candidate may replace only declared writable files')
    if any(type(x) is not str for x in replacements.values()):
        raise ProtocolViolation('candidate source must be text')
    public={**dict(task.public_files), **replacements}
    if len(canonical(public))>limits.source_bytes: raise ProtocolViolation('source size cap')
    return CandidateBundle(task.task_id, candidate_id, tuple(sorted(public.items())))


@dataclass(frozen=True)
class OracleCase:
    case_id: str
    input_json: bytes
    expected_json: bytes

    def __post_init__(self):
        identifier(self.case_id); strict_json(self.input_json); strict_json(self.expected_json)


@dataclass(frozen=True)
class OracleSuite:
    task_id: str
    visibility: str
    cases: tuple[OracleCase, ...]

    def __post_init__(self):
        identifier(self.task_id)
        if self.visibility not in ('public', 'final'): raise ProtocolViolation('unknown visibility')
        if type(self.cases) is not tuple or not self.cases or any(type(x) is not OracleCase for x in self.cases):
            raise ProtocolViolation('immutable nonempty oracle cases required')
        if len({x.case_id for x in self.cases}) != len(self.cases): raise ProtocolViolation('duplicate case')

    def commitment(self):
        # Host-only commitment; never part of a candidate invocation.
        return digest({'task_id':self.task_id,'visibility':self.visibility,
                       'cases':[(c.case_id, strict_json(c.input_json), strict_json(c.expected_json)) for c in self.cases]})


@dataclass(frozen=True)
class Invocation:
    invocation_id: str
    candidate_sha256: str
    input_json: bytes

    def __post_init__(self):
        identifier(self.invocation_id);sha256_text(self.candidate_sha256);strict_json(self.input_json)

    def candidate_stdin(self):
        # IDs, answers, suite identity, score and sibling cases are NOT sent.
        return canonical({'input': strict_json(self.input_json)}) + b'\n'


@dataclass(frozen=True)
class TransportObservation:
    """Trusted adapter envelope; do not populate status from candidate stdout."""
    invocation_id: str
    candidate_sha256: str
    status: str
    stdout: bytes
    stderr: bytes = b''
    cleanup_confirmed: bool = True

    def __post_init__(self):
        identifier(self.invocation_id);sha256_text(self.candidate_sha256)
        if self.status not in ('exited', 'candidate_error', 'timeout', 'output_limit',
                               'memory_limit', 'start_failure', 'transport_failure'):
            raise ProtocolViolation('unknown trusted adapter status')
        if type(self.stdout) is not bytes or type(self.stderr) is not bytes or type(self.cleanup_confirmed) is not bool:
            raise ProtocolViolation('bounded byte streams and cleanup flag required')


def score_observation(request, case, observation, limits):
    if (type(request) is not Invocation or type(case) is not OracleCase or
        type(observation) is not TransportObservation or type(limits) is not ExecutionLimits):
        raise ProtocolViolation('typed scoring inputs required')
    if (observation.invocation_id!=request.invocation_id or
        observation.candidate_sha256!=request.candidate_sha256):
        raise ProtocolViolation('stale or substituted observation')
    if request.input_json != case.input_json: raise ProtocolViolation('wrong case binding')
    if not observation.cleanup_confirmed: return ('missing', 'cleanup_unconfirmed')
    if observation.status in ('start_failure','transport_failure'):
        return ('missing', observation.status)
    if len(observation.stdout)>limits.output_bytes or len(observation.stderr)>limits.stderr_bytes:
        return ('failed','output_limit')
    if observation.status!='exited': return ('failed',observation.status)
    try:
        answer=strict_json(observation.stdout)
        if type(answer) is not dict or set(answer)!={'result'}:
            return ('failed','invalid_output')
        passed=canonical(answer['result'])==canonical(strict_json(case.expected_json))
    except ProtocolViolation: return ('failed','invalid_output')
    return ('passed' if passed else 'failed','answer_match' if passed else 'answer_mismatch')


class EvaluationSession:
    """Single-writer, in-memory host state; NO crash-resume guarantee.

    A final session binds one already selected candidate plus publication state.
    Each test is issued once. Missing results stay missing; they do not authorize
    reissue or reselection. A persistent runner must additionally journal this.
    """
    def __init__(self, session_id, bundle, suite, limits, *, publication_sha256=None):
        identifier(session_id)
        if type(bundle) is not CandidateBundle or type(suite) is not OracleSuite or type(limits) is not ExecutionLimits:
            raise ProtocolViolation('typed session inputs required')
        if bundle.task_id != suite.task_id: raise ProtocolViolation('task mismatch')
        if suite.visibility=='final': sha256_text(publication_sha256)
        elif publication_sha256 is not None: raise ProtocolViolation('public session has no final publication')
        if len(canonical(dict(bundle.public_files)))>limits.source_bytes: raise ProtocolViolation('source size cap')
        identifier(f'{session_id}-{len(suite.cases)-1}')
        self._id=session_id; self._bundle=bundle; self._suite=suite; self._limits=limits
        self._publication=publication_sha256; self._issued={}; self._results={}
        for case in suite.cases:
            dummy=Invocation('probe',bundle.sha256(),case.input_json)
            if len(dummy.candidate_stdin())>limits.input_bytes: raise ProtocolViolation('input size cap')

    def issue(self, index):
        integer(index,'case index')
        if index>=len(self._suite.cases) or index in self._issued:
            raise ProtocolViolation('unknown or already issued test')
        request=Invocation(identifier(f'{self._id}-{index}'),self._bundle.sha256(),self._suite.cases[index].input_json)
        self._issued[index]=request
        return request

    def accept(self, index, observation):
        integer(index, 'case index')
        if index not in self._issued or index in self._results:
            raise ProtocolViolation('unissued or already scored test')
        result=score_observation(self._issued[index],self._suite.cases[index],observation,self._limits)
        self._results[index]=result
        return result

    def report(self):
        count=len(self._suite.cases)
        rows=[self._results.get(i,('missing','not_observed')) for i in range(count)]
        observed=sum(s!='missing' for s,_ in rows)
        passed=sum(s=='passed' for s,_ in rows)
        return {'visibility':self._suite.visibility,'candidate_sha256':self._bundle.sha256(),
                'suite_sha256':self._suite.commitment(),'publication_sha256':self._publication,
                'planned':count,'observed':observed,'passed':passed,'missing':count-observed,
                'failed':observed-passed,'complete_observation':observed==count,
                'all_passed':False if observed>passed else (True if passed==count else None),
                'outcomes':[{'status':s,'reason':reason} for s,reason in rows]}

    def model_feedback(self):
        if self._suite.visibility!='public': raise ProtocolViolation('final feedback never enters model/update history')
        report=self.report()
        return {k:report[k] for k in ('planned','observed','passed','missing','all_passed')}


def execution_readiness():
    return {'live_execution':False,'candidate_processes_launched':0,
            'implemented':'offline separate-oracle I/O, submission binding and scoring only',
            'required_runtime_probes':['host and secret file denial','outbound network denial',
                'readonly candidate and no verifier mount','process/memory/wall limits',
                'bounded stdout/stderr while streaming','whole process-tree termination',
                'fresh instance for each final case','environment allowlist and no daemon socket'],
            'unverified':'all OS runtime probes; no validated live adapter is installed'}


def launch_candidate(*args, **kwargs):
    # There is intentionally no allow_unsafe flag or host-subprocess fallback.
    raise ExecutionUnavailable('No validated OS runtime adapter; candidate execution is disabled')
