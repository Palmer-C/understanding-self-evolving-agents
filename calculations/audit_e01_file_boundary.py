"""Demonstrate legacy file-tool boundaries using ONLY fresh dummy temp files.

No model, network, credentials, historical tasks, or old experiment outputs.
The legacy module is imported without modification. All markers are generated
here; no pre-existing data outside the dummy task is read or written.
"""
from pathlib import Path
import hashlib,json,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.lab.sandbox import Sandbox
from experiments.lab.e01_v2_file_boundary import PublicFileBoundary,FileBoundaryViolation


def audit():
    with tempfile.TemporaryDirectory(prefix='e01-boundary-dummy-') as name:
        base=Path(name).resolve(); root=base/'task'; sibling=base/'task-shadow'
        root.mkdir();sibling.mkdir()
        marker=sibling/'marker.txt';marker.write_text('DUMMY-OUTSIDE',encoding='utf-8')
        protected=root/'test_public.py';protected.write_text('DUMMY-VERIFIER',encoding='utf-8')
        (root/'solution.py').write_text('DUMMY-SOURCE',encoding='utf-8')
        assert root.parent==base and sibling.parent==base
        old=Sandbox(root,protected=['test_public.py'])
        sibling_read=old.read_file('../task-shadow/marker.txt')=='DUMMY-OUTSIDE'
        protected_read=old.read_file('test_public.py')=='DUMMY-VERIFIER'
        # Controlled child reads only the dummy sibling and writes only the
        # dummy verifier created above; no unrelated target or content involved.
        code="from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text()); Path(sys.argv[2]).write_text('DUMMY-CHANGED')"
        child=old.run([sys.executable,'-c',code,str(marker),str(protected)],timeout=10)
        child_read=child.ok and 'DUMMY-OUTSIDE' in child.stdout
        child_write=protected.read_text()=='DUMMY-CHANGED'
        new=PublicFileBoundary(root,readable=['solution.py','test_public.py'],writable=['solution.py'])
        blocks={}
        for label,action in [('sibling_read',lambda:new.read('../task-shadow/marker.txt')),
                             ('verifier_write',lambda:new.write('test_public.py','DUMMY-NEW'))]:
            try:action();blocks[label]=False
            except FileBoundaryViolation:blocks[label]=True
        assert all((sibling_read,protected_read,child_read,child_write,*blocks.values()))
        return {'identity':'controlled local engineering counterexample with fresh dummy markers; no model test',
            'legacy':{'string_prefix_sibling_read_allowed':sibling_read,
                      'protected_test_is_readable':protected_read,
                      'child_can_read_dummy_outside_cwd':child_read,
                      'child_can_modify_dummy_protected_file':child_write},
            'new_file_tool':blocks,'os_process_isolation_fixed':False,
            'scope':'new tool fixes file manifest/path checks only; generated-code runner isolation remains blocked',
            'api_calls':0,'historical_files_modified':False}


if __name__=='__main__':
    result=audit();r=Path(__file__).resolve().parents[1]
    result['source_sha256']={p:hashlib.sha256((r/p).read_bytes()).hexdigest() for p in
        ['experiments/lab/sandbox.py','experiments/lab/e01_v2_file_boundary.py']}
    (r/'calculations/e01-file-boundary-audit-2026-09-30.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
