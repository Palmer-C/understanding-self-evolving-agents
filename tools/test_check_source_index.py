"""Synthetic regressions; fixtures use a dedicated external artifact directory.

Fixtures are preserved for review. Set SOURCE_INDEX_TEST_ARTIFACT_ROOT to an
audit workspace; otherwise use the system temporary source-index-fixtures dir.
Run: python -B -m unittest -v
"""
import contextlib
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'check_source_index.py'
SPEC = importlib.util.spec_from_file_location('source_index_candidate', SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class RepositoryFixture(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get('SOURCE_INDEX_TEST_ARTIFACT_ROOT')
        fixture_base = Path(configured) if configured else Path(tempfile.gettempdir()) / 'source-index-fixtures'
        fixture_base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=fixture_base))
        for relative in ('references', 'book/bib', 'book/chapters'):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def repository(self, rows, bib, tex='', files=()):
        with (self.root / 'references/sources.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['short_name', 'arxiv_id', 'bib_alias', 'local_pdf'])
            writer.writeheader()
            writer.writerows(rows)
        (self.root / 'book/bib/references.bib').write_text(bib, encoding='utf-8')
        (self.root / 'book/chapters/ch01.tex').write_text(tex, encoding='utf-8')
        for relative in files:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'%PDF synthetic fixture; existence only\n')
        return CHECKER.build_report(self.root)

    def test_documented_alias_controls_coverage_pdf_and_citation(self):
        report = self.repository([{'short_name': 'canonical', 'bib_alias': 'alias-2601', 'local_pdf': 'files/source.pdf'}],
                                 '@misc{alias-2601, title={One}}', r'\cite{alias-2601}',
                                 ['references/files/source.pdf'])
        for field in ('bib_without_csv', 'csv_without_bib', 'missing_local_pdf', 'bib_not_cited', 'csv_not_cited'):
            self.assertEqual([], report[field], field)
        self.assertIn('bib_alias', report['mappings'][0]['methods'])

    def test_alias_missing_pdf_checks_declared_path_without_cache_guess(self):
        report = self.repository([{'short_name': 'canonical', 'bib_alias': 'alias', 'local_pdf': 'files/missing.pdf'}],
                                 '@misc{alias, title={One}}', r'\cite{alias}',
                                 ['references/cache/missing.pdf'])
        self.assertEqual([('alias', 'canonical', 'files/missing.pdf')],
                         [(m['bib_key'], m['csv_key'], m['local_pdf']) for m in report['missing_local_pdf']])
        self.assertEqual([], report['csv_not_cited'])

    def test_undeclared_pdf_is_unknown_not_missing_or_pass(self):
        report = self.repository([{'short_name': 'one'}], '@misc{one, title={One}}', r'\cite{one}')
        self.assertEqual([], report['missing_local_pdf'])
        self.assertEqual('one', report['local_pdf_not_declared'][0]['csv_key'])
        self.assertIn('not a file-existence PASS', CHECKER.format_report(report))

    def test_eprint_only_paper_id_resolves_different_keys(self):
        report = self.repository([{'short_name': 'different-csv-name', 'arxiv_id': '2401.12345'}],
                                 '@misc{unrelated-bib-key, eprint={2401.12345}}', r'\cite{unrelated-bib-key}')
        self.assertEqual([], report['bib_without_csv'])
        self.assertEqual([], report['csv_without_bib'])
        self.assertEqual([], report['csv_not_cited'])
        self.assertEqual(['arxiv'], report['mappings'][0]['methods'])

    def test_arxiv_url_field_resolves_and_normalizes_pdf_suffix(self):
        report = self.repository([{'short_name': 'csv-name', 'arxiv_id': 'arXiv:2402.1234v2'}],
                                 '@article{bib-key, url="https://arxiv.org/pdf/2402.1234v1.pdf"}', r'\citep{bib-key}')
        self.assertEqual([], report['bib_without_csv'])
        self.assertEqual('2402.1234', report['mappings'][0]['arxiv_paper_ids'][0])

    def test_long_nested_entry_does_not_borrow_next_entry_id(self):
        title = '{Nested {subgroup, with commas} title} ' * 100
        report = self.repository([{'short_name': 'paper-two', 'arxiv_id': '2403.12345'}],
            '@misc{first, title={' + title + '}, note={arXiv:2403.12345}}\n'
            '@misc{second, eprint={2403.12345}}', r'\cite{first,second}')
        self.assertEqual(['first'], report['bib_without_csv'])
        self.assertEqual(['second'], [m['bib_key'] for m in report['mappings']])
        entries, warnings = CHECKER.parse_bibtex('@misc{first,title={' + title + '}}\n@misc{second,eprint={2403.12345}}')
        self.assertEqual(2, len(entries))
        self.assertEqual([], CHECKER.entry_arxiv_identities(entries[0]))
        self.assertEqual([], warnings)

    def test_own_eprint_after_long_title_is_not_truncated(self):
        report = self.repository([{'short_name': 'csv', 'arxiv_id': '2404.12345'}],
            '@misc{bib,title={' + ('long {nested} title, ' * 100) + '},eprint={2404.12345}}', r'\cite{bib}')
        self.assertEqual([], report['bib_without_csv'])

    def test_versions_match_at_paper_level_without_version_confirmation(self):
        report = self.repository([{'short_name': 'csv', 'arxiv_id': '2405.12345v2'}],
                                 '@misc{bib,eprint={2405.12345v1}}', r'\cite{bib}')
        mapping = report['mappings'][0]
        self.assertFalse(mapping['version_verified'])
        self.assertEqual('v1', mapping['bib_arxiv_metadata'][0]['version'])
        self.assertEqual('v2', mapping['csv_arxiv_metadata']['version'])
        self.assertIn('paper-level only', mapping['identity_scope'])
        self.assertIn('never version/PDF-content verification', CHECKER.format_report(report))

    def test_duplicate_source_paper_id_is_not_arbitrarily_selected(self):
        report = self.repository([{'short_name': 'a', 'arxiv_id': '2406.12345v1'},
                                  {'short_name': 'b', 'arxiv_id': '2406.12345v2'}],
                                 '@misc{bib,eprint={2406.12345}}', r'\cite{bib}')
        self.assertEqual([], report['mappings'])
        self.assertEqual(['bib'], report['bib_without_csv'])
        self.assertEqual(['a', 'b'], report['csv_citation_unresolved'])
        self.assertIn('duplicate_source_arxiv', {a['kind'] for a in report['ambiguities']})

    def test_multiple_bib_versions_keep_many_to_one_paper_mapping(self):
        report = self.repository([{'short_name': 'csv', 'arxiv_id': '2407.12345'}],
            '@misc{one,eprint={2407.12345v1}}\n@misc{two,url={https://arxiv.org/abs/2407.12345v2}}', r'\cite{one}')
        self.assertEqual([('one', 'csv'), ('two', 'csv')],
                         [(m['bib_key'], m['csv_key']) for m in report['mappings']])
        self.assertEqual([], report['bib_without_csv'])
        self.assertEqual([], report['csv_without_bib'])
        self.assertEqual([], report['csv_not_cited'])
        self.assertTrue(all(not m['version_verified'] for m in report['mappings']))
        self.assertIn('duplicate_bib_arxiv', {a['kind'] for a in report['ambiguities']})
        self.assertEqual('informational', report['ambiguities'][0]['severity'])

    def test_duplicate_alias_is_not_arbitrarily_selected(self):
        report = self.repository([{'short_name': 'a', 'bib_alias': 'alias'}, {'short_name': 'b', 'bib_alias': 'alias'}],
                                 '@misc{alias,title={One}}', r'\cite{alias}')
        self.assertEqual([], report['mappings'])
        self.assertIn('duplicate_alias', {a['kind'] for a in report['ambiguities']})

    def test_slug_collision_is_not_arbitrarily_selected(self):
        report = self.repository([{'short_name': 'my-paper1'}, {'short_name': 'my-paper2'}],
                                 '@misc{my-paper-2601,title={One}}')
        self.assertEqual([], report['mappings'])
        self.assertIn('duplicate_source_slug', {a['kind'] for a in report['ambiguities']})

    def test_conflicting_entry_arxiv_fields_remain_unresolved(self):
        report = self.repository([{'short_name': 'csv', 'bib_alias': 'bib', 'arxiv_id': '2408.12345'}],
            '@misc{bib,eprint={2408.12345},url={https://arxiv.org/abs/2409.12345}}', r'\cite{bib}')
        self.assertEqual([], report['mappings'])
        self.assertIn('conflicting_arxiv_fields', report['ambiguities'][-1]['reasons'])

    def test_alias_and_arxiv_disagreement_remain_unresolved(self):
        report = self.repository([{'short_name': 'a', 'bib_alias': 'bib', 'arxiv_id': '2410.12345'},
                                  {'short_name': 'b', 'arxiv_id': '2411.12345'}],
                                 '@misc{bib,eprint={2411.12345}}', r'\cite{bib}')
        self.assertEqual([], report['mappings'])
        self.assertIn('multiple_source_candidates', report['ambiguities'][-1]['reasons'])

    def test_true_unreferenced_and_uncovered_records_stay_visible(self):
        report = self.repository([{'short_name': 'cited'}, {'short_name': 'uncited'}, {'short_name': 'csv-only'}],
                                 '@misc{cited,title={One}}\n@misc{uncited,title={Two}}\n@misc{bib-only,title={Three}}',
                                 r'\cite{cited,undefined}')
        self.assertEqual(['undefined'], report['cited_not_in_bib'])
        self.assertEqual(['bib-only'], report['bib_without_csv'])
        self.assertEqual(['csv-only'], report['csv_without_bib'])
        self.assertEqual(['bib-only', 'uncited'], report['bib_not_cited'])
        self.assertEqual(['uncited', 'csv-only'], report['csv_not_cited'])

    def test_citation_optional_arguments_star_and_numeric_macro(self):
        found = CHECKER.cited_keys(r'''
            \cite [see {nested text}] [p.~3] {one,two}
            \citep*[e.g.][§2]{three} \Citet{four}
            \citeauthor{five} \cited{1.000} \cited{not-a-bib-key}
            \citedate[chapter~2]{date-key}
            % \cite{commented}
            \begin{lstlisting}\cite{example-only}\end{lstlisting}
        ''')
        self.assertEqual({'one', 'two', 'three', 'four', 'five', 'date-key'}, found)

    def test_percent_and_comma_inside_values_do_not_strip_neighbour_fields(self):
        entries, warnings = CHECKER.parse_bibtex(r'''
            % @misc{commented,eprint={2412.99999}}
            @misc{real,
                title={A nested {title, % literal text} and more}, % outside value
                url={https://arxiv.org/abs/2412.12345?note=one%20two},
                eprint={2412.12345}
            }
            @misc{next,title={Different}}
        ''')
        self.assertEqual(['real', 'next'], [e['key'] for e in entries])
        self.assertEqual([], warnings)
        self.assertEqual('2412.12345', CHECKER.entry_arxiv_identities(entries[0])[0]['paper_id'])
        self.assertEqual([], CHECKER.entry_arxiv_identities(entries[1]))

    def test_build_directory_is_excluded(self):
        self.repository([{'short_name': 'real'}], '@misc{real,title={One}}', r'\cite{real}')
        (self.root / 'book/Build/nested').mkdir(parents=True)
        (self.root / 'book/Build/nested/generated.tex').write_text(r'\cite{generated-missing}', encoding='utf-8')
        report = CHECKER.build_report(self.root)
        self.assertEqual(['real'], report['cited_keys'])
        self.assertEqual([], report['cited_not_in_bib'])
        self.assertEqual(['book/chapters/ch01.tex'], report['tex_files'])

    def test_exact_and_slug_matches_use_same_reverse_mapping(self):
        report = self.repository([{'short_name': 'exact'}, {'short_name': 'my-paper'}],
                                 '@misc{exact,title={One}}\n@misc{my-paper-2601,title={Two}}',
                                 r'\cite{exact,my-paper-2601}')
        self.assertEqual([], report['csv_not_cited'])
        self.assertEqual([], report['csv_without_bib'])
        self.assertEqual([], report['bib_without_csv'])
        self.assertEqual({'exact', 'my-paper'}, {m['csv_key'] for m in report['mappings']})

    def test_non_arxiv_fields_and_domains_do_not_supply_identifiers(self):
        entries, _ = CHECKER.parse_bibtex(r'''
            @misc{title-only,title={arXiv:2412.12345},note={arXiv:2412.12345}}
            @misc{evil-url,url={https://arxiv.org.example/abs/2412.12345}}
            @misc{not-arxiv,eprint={2412.12345},archivePrefix={Zenodo}}
        ''')
        self.assertEqual([[], [], []], [CHECKER.entry_arxiv_identities(e) for e in entries])
        self.assertIsNone(CHECKER.arxiv_identity('2412.123456'))

    def test_unclosed_entry_is_reported_and_not_spliced_to_a_neighbour(self):
        entries, warnings = CHECKER.parse_bibtex('@misc{first,title={unclosed\n@misc{second,eprint={2412.12345}}')
        self.assertEqual([], entries)
        self.assertEqual('unclosed_bib_entry', warnings[0]['kind'])

    def test_balanced_parenthesized_entry_and_ignored_directives(self):
        entries, warnings = CHECKER.parse_bibtex('''
            @comment{ @misc{fake,eprint={2412.12345}} }
            @string{macro = "value"}
            @misc(real, title = "A (nested) title with {group, comma}", eprint={2412.12345})
        ''')
        self.assertEqual(['real'], [e['key'] for e in entries])
        self.assertEqual('2412.12345', CHECKER.entry_arxiv_identities(entries[0])[0]['paper_id'])
        self.assertEqual('bib_string_not_expanded', warnings[0]['kind'])

    def test_import_has_no_repository_io_or_report_output(self):
        specification = importlib.util.spec_from_file_location('import_probe', SCRIPT)
        module = importlib.util.module_from_spec(specification)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            specification.loader.exec_module(module)
        self.assertEqual('', output.getvalue())
        self.assertTrue(callable(module.build_report))

    def test_cli_text_and_json_report_same_real_gaps_without_new_exit_gate(self):
        expected = self.repository([{'short_name': 'only-csv'}], '@misc{only-bib,title={One}}', r'\cite{missing}')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        command = [sys.executable, '-B', str(SCRIPT), '--root', str(self.root)]
        text = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', env=env, check=False)
        data = subprocess.run(command + ['--json'], capture_output=True, text=True, encoding='utf-8', env=env, check=False)
        self.assertEqual(0, text.returncode, text.stderr)
        self.assertEqual(0, data.returncode, data.stderr)
        self.assertIn('SUMMARY: A=1 B=1 C=1 D=0', text.stdout)
        self.assertEqual(expected, json.loads(data.stdout))

    def test_cli_missing_input_is_explicit_nonzero_input_error(self):
        run = subprocess.run([sys.executable, '-B', str(SCRIPT), '--root', str(self.root)],
                             capture_output=True, text=True, encoding='utf-8', check=False)
        self.assertEqual(2, run.returncode)
        self.assertEqual('', run.stdout)
        self.assertIn('SOURCE-INDEX INPUT ERROR', run.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
