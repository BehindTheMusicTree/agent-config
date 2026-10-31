import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr_context = load('pr-context')
ci_context = load('ci-failure-context')


class PrContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pr context ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.root / 'old name.txt').write_text('original\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')
        self.git('branch', 'base')
        self.git('switch', '-qc', 'feature')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def test_rename_unusual_paths_dirty_changes_and_validation_reference(self):
        target = 'new\nname.txt'
        self.git('mv', 'old name.txt', target)
        self.git('commit', '-qm', 'rename')
        (self.root / target).write_text('dirty\n')
        (self.root / 'untracked file').write_text('untracked')
        report = pr_context.collect(self.root, 'base', 30, [target])
        self.assertEqual(report['files']['items'], [{'status': 'R100', 'path': target, 'previous_path': 'old name.txt'}])
        self.assertTrue(report['worktree']['dirty'])
        self.assertEqual(report['worktree']['total'], 2)
        self.assertEqual(report['validation_logs'][0]['validity'], 'not_verified')
        self.assertEqual(report['commits']['items'][0]['subject'], 'rename')
        self.assertEqual((self.root / target).read_text(), 'dirty\n')

    def test_default_base_uses_existing_detector_and_remote_ref(self):
        self.git('update-ref', 'refs/remotes/origin/main', 'main')
        report = pr_context.collect(self.root, None, 30, [])
        self.assertEqual(report['base_ref'], 'origin/main')
        self.assertEqual(report['flow'], 'github')
        self.assertEqual(report['files']['total'], 0)

    def test_missing_base_and_validation_log_fail(self):
        with self.assertRaises(subprocess.CalledProcessError):
            pr_context.collect(self.root, 'missing', 30, [])
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            pr_context.collect(self.root, 'base', 30, ['missing.log'])

    def test_limits_do_not_hide_omissions(self):
        for name in ('one', 'two'):
            (self.root / name).write_text(name)
            self.git('add', name)
            self.git('commit', '-qm', name)
        report = pr_context.collect(self.root, 'base', 1, [])
        self.assertEqual(report['files']['total'], 2)
        self.assertEqual(report['files']['omitted'], 1)
        self.assertEqual(report['commits']['omitted'], 1)

    def test_staged_worktree_rename_preserves_both_names(self):
        self.git('mv', 'old name.txt', 'staged name')
        report = pr_context.collect(self.root, 'base', 30, [])
        self.assertEqual(report['worktree']['items'][0]['previous_path'], 'old name.txt')
        self.assertEqual(report['worktree']['items'][0]['path'], 'staged name')

    def test_explicit_base_does_not_bypass_gitflow_detection(self):
        self.git('update-ref', 'refs/remotes/origin/develop', 'main')
        report = pr_context.collect(self.root, 'base', 30, [])
        self.assertEqual(report['base_ref'], 'base')
        self.assertEqual(report['flow'], 'gitflow')

    def test_review_request_is_not_an_automatic_risk_classification(self):
        report = pr_context.collect(self.root, 'base', 30, [], 'release', 'light')
        self.assertEqual(report['review_request'], {
            'intent': 'release', 'depth': 'light', 'classification': 'requires_hunk_review',
        })

    def test_invalid_review_arguments_fail_before_collecting(self):
        result = subprocess.run([
            'python3', str(ROOT / 'scripts/pr-context.py'), '--repo', str(self.root), '--depth', 'skip',
        ], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')


class CiContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ci context ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.head = 'a' * 40
        self.check = {'name': 'tests', 'conclusion': 'FAILURE', 'detailsUrl':
                      'https://github.com/owner/repo/actions/runs/12/job/34'}
        self.metadata = {'number': 5, 'url': 'https://github.com/owner/repo/pull/5',
                         'headRefOid': self.head, 'statusCheckRollup': [self.check]}
        self.current = {'headRefOid': self.head, 'statusCheckRollup': [self.check]}
        self.run = {'headSha': self.head, 'attempt': 2, 'jobs': [{'databaseId': 34}]}

    def download(self, args, **kwargs):
        kwargs['stdout'].write(b'start\nERROR: repeated\nERROR: repeated\nERROR: unique\nend\n')
        self.assertIn('--log', args)
        self.assertEqual(args[args.index('--attempt') + 1], '2')
        return subprocess.CompletedProcess(args, 0, stderr=b'')

    def test_full_logs_and_distinct_errors_survive_bounded_output(self):
        with patch.object(ci_context, 'gh_json', side_effect=[self.metadata, self.run, self.current]), \
                patch.object(ci_context.subprocess, 'run', side_effect=self.download):
            result = ci_context.collect('5', 'owner/repo', self.root, 1)
        entry = result['failed_checks'][0]
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(entry['candidate_groups'], 2)
        self.assertEqual(entry['omitted_groups'], 1)
        self.assertIn(self.head + '-12-2-34', entry['log'])
        self.assertIn('ERROR: unique', Path(entry['log']).read_text())
        groups = json.loads(Path(entry['index']).read_text())
        self.assertEqual(groups[0]['count'], 2)
        self.assertEqual(groups[1]['lines'], [4])
        self.assertTrue(Path(result['manifest']).is_file())

    def test_missing_or_failed_logs_are_partial_not_success(self):
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code), \
                    patch.object(ci_context, 'gh_json', side_effect=[self.metadata, self.run, self.current]), \
                    patch.object(ci_context.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess([], exit_code, stderr=b'log not found')):
                result = ci_context.collect('5', 'owner/repo', self.root, 1)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['failed_checks'][0]['status'], 'collection_failed')
            self.assertEqual(list(Path(result['artifacts']).glob('*.log')), [])

    def test_old_sha_or_job_cannot_be_used_as_current_evidence(self):
        for run in ({**self.run, 'headSha': 'b' * 40}, {**self.run, 'jobs': []}):
            with self.subTest(run=run), \
                    patch.object(ci_context, 'gh_json', side_effect=[self.metadata, run, self.current]), \
                    patch.object(ci_context.subprocess, 'run') as download:
                result = ci_context.collect('5', 'owner/repo', self.root, 1)
            download.assert_not_called()
            self.assertEqual(result['status'], 'partial')

    def test_push_or_check_change_during_collection_marks_snapshot_stale(self):
        for current in ({**self.current, 'headRefOid': 'b' * 40}, {**self.current, 'statusCheckRollup': []}):
            with self.subTest(current=current), \
                    patch.object(ci_context, 'gh_json', side_effect=[self.metadata, self.run, current]), \
                    patch.object(ci_context.subprocess, 'run', side_effect=self.download):
                result = ci_context.collect('5', 'owner/repo', self.root, 1)
            self.assertEqual(result['status'], 'stale')

    def test_refresh_failure_preserves_collected_evidence_and_manifest(self):
        with patch.object(ci_context, 'gh_json', side_effect=[self.metadata, self.run, ValueError('network failed')]), \
                patch.object(ci_context.subprocess, 'run', side_effect=self.download):
            result = ci_context.collect('5', 'owner/repo', self.root, 1)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('unverified', result['error'])
        manifest = json.loads(Path(result['manifest']).read_text())
        self.assertEqual(manifest['failed_checks'][0]['status'], 'collected')
        self.assertTrue(Path(manifest['failed_checks'][0]['log']).is_file())

    def test_external_check_retains_link_without_inventing_job(self):
        check = {'context': 'deploy', 'state': 'ERROR', 'targetUrl': 'https://example.invalid/deploy/12'}
        metadata = {**self.metadata, 'statusCheckRollup': [check]}
        with patch.object(ci_context, 'gh_json', side_effect=[metadata, metadata]), \
                patch.object(ci_context.subprocess, 'run') as download:
            result = ci_context.collect('5', 'owner/repo', self.root, 1)
        download.assert_not_called()
        self.assertEqual(result['failed_checks'][0]['url'], check['targetUrl'])
        self.assertEqual(result['status'], 'partial')

    def test_no_error_match_never_claims_success(self):
        path = self.root / 'job.log'
        path.write_text('unexpected exit\n' * 100)
        report = ci_context.index_log(path, 1)
        self.assertEqual(len(report['excerpts']), 20)
        self.assertIn('does not establish success', report['selection'])

    def test_auth_failure_is_not_an_empty_check_list(self):
        with patch.object(ci_context, 'gh_json', side_effect=ValueError('authentication failed')):
            with self.assertRaisesRegex(ValueError, 'authentication failed'):
                ci_context.collect('5', 'owner/repo', self.root, 1)

    def test_cli_bounds_check_preview_but_preserves_manifest(self):
        checks = [{'context': str(i), 'state': 'FAILURE', 'targetUrl': 'https://example.invalid'} for i in range(6)]
        metadata = {**self.metadata, 'statusCheckRollup': checks}
        output = io.StringIO()
        with patch.object(ci_context, 'gh_json', side_effect=[metadata, metadata]), \
                patch('sys.argv', ['ci-failure-context.py', '5', '--repo', 'owner/repo']), \
                patch('sys.stdout', output), \
                patch.object(ci_context.tempfile, 'gettempdir', return_value=str(self.root)):
            status = ci_context.main()
        preview = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(len(preview['failed_checks']), 5)
        self.assertEqual(preview['omitted_checks'], 1)
        self.assertEqual(len(json.loads(Path(preview['manifest']).read_text())['failed_checks']), 6)

    def test_cli_refuses_unignored_repository_artifacts_before_network(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        directory = self.root / 'logs'
        directory.mkdir()
        with patch('sys.argv', ['ci-failure-context.py', '5', '--repo', 'owner/repo', '--output-dir', str(directory)]), \
                patch('sys.stderr', io.StringIO()), patch.object(ci_context, 'gh_json') as api:
            self.assertEqual(ci_context.main(), 1)
        api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
