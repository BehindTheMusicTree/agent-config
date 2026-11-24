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
        self.git('update-ref', 'refs/remotes/origin/main', 'main')
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

    def test_branch_prefix_and_local_template(self):
        report = pr_context.collect(self.root, 'base', 30, [])
        self.assertEqual(report['branch_prefix'], 'n/a')
        self.assertEqual(report['pr_template'], {'source': 'unchecked', 'path': None})
        self.assertIsNone(report['merge_method'])
        (self.root / '.github').mkdir()
        (self.root / '.github' / 'pull_request_template.md').write_text('## Summary\n')
        self.git('update-ref', 'refs/remotes/origin/develop', 'main')
        report = pr_context.collect(self.root, 'base', 30, [])
        self.assertEqual(report['pr_template'], {'source': 'local', 'path': '.github/pull_request_template.md'})
        self.assertEqual(report['branch_prefix'], 'invalid')
        self.git('branch', '-m', 'feature', 'work')
        self.git('switch', '-qc', 'feature/x')
        self.assertEqual(pr_context.collect(self.root, 'base', 30, [])['branch_prefix'], 'valid')
        self.assertEqual(pr_context.collect(self.root, 'base', 30, [], 'back-merge')['branch_prefix'], 'n/a')

    def test_org_template_lookup_distinguishes_missing_from_errors(self):
        self.git('remote', 'add', 'origin', 'git@github.com:acme/app.git')

        def found(*args):
            return ('ok', '') if args[-1].endswith('contents/pull_request_template.md') else ('missing', '')
        with patch.object(pr_context, 'gh_api', side_effect=found):
            template = pr_context.pr_template(self.root, True)
        self.assertEqual(template, {'source': 'org', 'path': 'acme/.github:pull_request_template.md'})
        with patch.object(pr_context, 'gh_api', return_value=('missing', '')):
            self.assertEqual(pr_context.pr_template(self.root, True), {'source': 'none', 'path': None})
        with patch.object(pr_context, 'gh_api', side_effect=ValueError('boom')):
            with self.assertRaises(ValueError):
                pr_context.pr_template(self.root, True)

    def test_merge_method_single_documented_or_ambiguous(self):
        self.git('remote', 'add', 'origin', 'https://github.com/acme/app.git')
        flags = lambda **kw: ('ok', json.dumps({f'allow_{method}_merge' if method != 'merge' else 'allow_merge_commit': enabled
                                                        for method, enabled in kw.items()}))
        with patch.object(pr_context, 'gh_api', return_value=flags(squash=True)):
            self.assertEqual(pr_context.merge_method(self.root), 'squash')
        with patch.object(pr_context, 'gh_api', return_value=flags(squash=True, merge=True)):
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                pr_context.merge_method(self.root)
            (self.root / 'CONTRIBUTING.md').write_text('We use a merge commit for every PR.\n')
            self.assertEqual(pr_context.merge_method(self.root), 'merge')

    def test_btmt_merge_routes(self):
        routes = [
            ('github', 'main', 'release-please--branches--main', 'main', 'release', 'squash'),
            ('gitflow', 'develop', 'feature/change', 'develop', 'change', 'squash'),
            ('gitflow', 'develop', 'fix/cherry-pick', 'develop', 'change', 'squash'),
            ('gitflow', 'develop', 'hotfix/2.0.1', 'main', 'release', 'squash'),
            ('gitflow', 'develop', 'release/2.1.0', 'main', 'release', 'merge'),
            ('gitflow', 'develop', 'back-merge/2.1.0', 'develop', 'back-merge', 'merge'),
        ]
        flags = ('ok', '{"default_branch":"main","allow_squash_merge":true,"allow_merge_commit":true}')
        classic = ('ok', '{"data":{"repository":{"ref":{"branchProtectionRule":null}}}}')
        self.git('remote', 'add', 'origin', 'https://github.com/BehindTheMusicTree/app.git')
        for flow, _, source, target, intent, expected in routes:
            develop = ('ok', '{"ref":"refs/heads/develop"}') if flow == 'gitflow' else ('missing', '')
            responses = [flags, develop]
            if intent == 'back-merge':
                responses += [('ok', '{"merge_base_commit":{"sha":"456"}}'), ('ok', '{"status":"diverged"}')]
            responses += [('ok', '[[]]'), classic]
            with self.subTest(source=source), patch.object(pr_context, 'gh_api', side_effect=responses):
                self.assertEqual(pr_context.merge_method(self.root, source, target, intent, {'sha': '123'}), expected)

    def test_btmt_merge_route_refuses_disabled_method_and_inconsistent_release(self):
        self.git('remote', 'add', 'origin', 'https://github.com/BehindTheMusicTree/app.git')
        route = ('release/2.1.0', 'main', 'release')
        disabled = ('ok', '{"default_branch":"main","allow_squash_merge":true,"allow_merge_commit":false}')
        develop = ('ok', '{"ref":"refs/heads/develop"}')
        with patch.object(pr_context, 'gh_api', side_effect=[disabled, develop]):
            with self.assertRaisesRegex(ValueError, 'disables merge'):
                pr_context.merge_method(self.root, *route)
        for source, target, intent in (
            ('feature/x', 'main', 'release'),
            ('feature/x', 'develop', 'back-merge'),
            ('back-merge/2.1.0', 'develop', 'change'),
        ):
            with patch.object(pr_context, 'gh_api', side_effect=[disabled, develop]):
                with self.assertRaisesRegex(ValueError, 'no route'):
                    pr_context.merge_method(self.root, source, target, intent)

        flags = ('ok', '{"default_branch":"main","allow_squash_merge":true,"allow_merge_commit":true}')
        rule = ('ok', '[[],[{"type":"required_linear_history","ruleset_id":71}]]')
        with patch.object(pr_context, 'gh_api', side_effect=[flags, develop, rule]):
            with self.assertRaisesRegex(ValueError, 'ruleset 71 on main blocks .* merge'):
                pr_context.merge_method(self.root, *route)
        classic = ('ok', '{"data":{"repository":{"ref":{"branchProtectionRule":{"requiresLinearHistory":true}}}}}')
        with patch.object(pr_context, 'gh_api', side_effect=[flags, develop, ('ok', '[[]]'), classic]):
            with self.assertRaisesRegex(ValueError, 'Classic branch protection'):
                pr_context.merge_method(self.root, *route)
        with patch.object(pr_context, 'gh_api', side_effect=[flags, develop, ValueError('GitHub read failed')]):
            with self.assertRaisesRegex(ValueError, 'read failed'):
                pr_context.merge_method(self.root, *route)

    def test_classic_merge_queue_blocks_native_auto_merge(self):
        self.git('remote', 'add', 'origin', 'https://github.com/BehindTheMusicTree/app.git')
        flags = ('ok', '{"default_branch":"main","allow_squash_merge":true}')
        classic = ('ok', json.dumps({'data': {'repository': {
            'ref': {'branchProtectionRule': None}, 'mergeQueue': {'configuration': {'mergeMethod': 'SQUASH'}},
        }}}))
        with patch.object(pr_context, 'gh_api', side_effect=[flags, ('missing', ''), ('ok', '[[]]'), classic]):
            with self.assertRaisesRegex(ValueError, 'merge queue on main'):
                pr_context.merge_method(self.root, 'feature/x', 'main')

    def test_existing_pr_uses_github_refs_and_detects_develop_without_a_local_ref(self):
        self.git('remote', 'add', 'origin', 'https://github.com/BehindTheMusicTree/app.git')
        pr = {'head': {'ref': 'release/2.1.0', 'sha': '123'}, 'base': {'ref': 'main'}, 'state': 'open'}
        flags = ('ok', '{"default_branch":"main","allow_squash_merge":true,"allow_merge_commit":true}')
        classic = ('ok', '{"data":{"repository":{"ref":{"branchProtectionRule":null}}}}')
        responses = [('ok', json.dumps(pr)), flags, ('ok', '{"ref":"refs/heads/develop"}'), ('ok', '[[]]'), classic]
        with patch.object(pr_context, 'gh_api', side_effect=responses) as gh:
            result = pr_context.existing_pr_policy(self.root, 42, 'release')
        self.assertEqual(result, {
            'source': 'release/2.1.0', 'target': 'main', 'head_sha': '123', 'state': 'open', 'merge_method': 'merge',
        })
        gh.assert_any_call('repos/BehindTheMusicTree/app/pulls/42')
        gh.assert_any_call('repos/BehindTheMusicTree/app/git/ref/heads/develop')
        gh.assert_any_call('--paginate', '--slurp', 'repos/BehindTheMusicTree/app/rules/branches/main')

    def test_legacy_back_merge_requires_pending_main_history(self):
        self.git('remote', 'add', 'origin', 'https://github.com/BehindTheMusicTree/app.git')
        flags = ('ok', '{"default_branch":"main","allow_squash_merge":true,"allow_merge_commit":true}')
        develop = ('ok', '{"ref":"refs/heads/develop"}')
        common = ('ok', '{"merge_base_commit":{"sha":"456"}}')
        classic = ('ok', '{"data":{"repository":{"ref":{"branchProtectionRule":null}}}}')
        route = ('integration/main-into-develop-1.4.8', 'develop', 'back-merge', {'sha': '123'})
        with patch.object(pr_context, 'gh_api', side_effect=[flags, develop, common, ('ok', '{"status":"ahead"}')]):
            with self.assertRaisesRegex(ValueError, 'no main history pending'):
                pr_context.merge_method(self.root, *route)
        responses = [flags, develop, common, ('ok', '{"status":"diverged"}'), ('ok', '[[]]'), classic]
        with patch.object(pr_context, 'gh_api', side_effect=responses) as gh:
            self.assertEqual(pr_context.merge_method(self.root, *route), 'merge')
        gh.assert_any_call('repos/BehindTheMusicTree/app/compare/main...123')
        gh.assert_any_call('repos/BehindTheMusicTree/app/compare/456...develop')

    def test_external_existing_pr_uses_the_pr_contributing_docs(self):
        self.git('remote', 'add', 'origin', 'https://github.com/acme/app.git')
        (self.root / 'CONTRIBUTING.md').write_text('Use squash.\n')
        pr = {
            'head': {'ref': 'feature/x', 'sha': '123', 'repo': {'full_name': 'acme/app'}},
            'base': {'ref': 'main'}, 'state': 'open',
        }
        responses = [
            ('ok', json.dumps(pr)), ('ok', '{"allow_squash_merge":true,"allow_merge_commit":true}'),
            ('ok', '[{"type":"file","name":"CONTRIBUTING.md"}]'), ('ok', 'Use a merge commit.'),
        ]
        with patch.object(pr_context, 'gh_api', side_effect=responses) as gh:
            result = pr_context.existing_pr_policy(self.root, 42, 'change')
        self.assertEqual(result['merge_method'], 'merge')
        gh.assert_any_call('-H', 'Accept: application/vnd.github.raw+json',
                           'repos/acme/app/contents/CONTRIBUTING.md?ref=123')

    def test_already_integrated_back_merge_has_no_merge_method(self):
        self.git('update-ref', 'refs/remotes/origin/develop', 'main')
        self.git('remote', 'add', 'origin', 'https://github.com/BehindTheMusicTree/app.git')
        (self.root / '.github').mkdir()
        (self.root / '.github' / 'pull_request_template.md').write_text('## Summary\n')
        with patch.object(pr_context, 'gh_api') as gh:
            result = pr_context.collect(self.root, 'origin/develop', 30, [], 'back-merge', github=True)
        self.assertTrue(result['already_integrated'])
        self.assertIsNone(result['merge_method'])
        gh.assert_not_called()

    def test_local_develop_ahead_of_origin_does_not_count_as_integrated(self):
        self.git('update-ref', 'refs/remotes/origin/develop', 'main')
        self.git('commit', '--allow-empty', '-qm', 'released change')
        self.git('branch', 'develop')
        result = pr_context.collect(self.root, 'develop', 30, [], 'back-merge')
        self.assertFalse(result['already_integrated'])

    def test_review_request_is_not_an_automatic_risk_classification(self):
        report = pr_context.collect(self.root, 'base', 30, [], 'release', 'light')
        self.assertEqual(report['review_request'], {
            'intent': 'release', 'depth': 'light', 'classification': 'requires_hunk_review',
        })

    RELEASE_JOB = (
        'jobs:\n'
        '  build:\n'
        '    runs-on: ubuntu-latest\n'
        '{other}'
        '  release-please:\n'
        '    uses: acme/workflows/.github/workflows/release-please.yml@0123456789abcdef0123456789abcdef01234567\n'
        '    with:\n'
        '{release}'
    )

    def release_mode(self, files):
        for path, content in files.items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(content)
        self.git('add', '.')
        self.git('commit', '-qm', 'release setup')
        return pr_context.collect(self.root, 'HEAD', 30, [])['release_please']

    def test_release_please_none_without_config(self):
        self.assertEqual(pr_context.collect(self.root, 'base', 30, [])['release_please'], 'none')

    def test_release_please_auto_merge_in_release_job(self):
        workflow = self.RELEASE_JOB.format(other='', release='      auto-merge: true\n')
        self.assertEqual(self.release_mode({
            'release-please-config.json': '{}', '.github/workflows/publish.yml': workflow,
        }), 'auto_merge')

    def test_release_please_manual_when_auto_merge_false(self):
        workflow = self.RELEASE_JOB.format(other='', release='      auto-merge: false\n')
        self.assertEqual(self.release_mode({
            '.release-please-manifest.json': '{}', '.github/workflows/publish.yml': workflow,
        }), 'manual')

    def test_release_please_manual_when_auto_merge_in_another_job(self):
        workflow = self.RELEASE_JOB.format(other='    with:\n      auto-merge: true\n', release='      app-id: x\n')
        self.assertEqual(self.release_mode({
            'release-please-config.json': '{}', '.github/workflows/publish.yaml': workflow,
        }), 'manual')

    def auto_merge_mode(self, release, name='publish.yml'):
        workflow = self.RELEASE_JOB.format(other='', release=release)
        return self.release_mode({'release-please-config.json': '{}', f'.github/workflows/{name}': workflow})

    def test_release_please_flow_mapping(self):
        workflow = self.RELEASE_JOB.format(other='', release='').replace('    with:\n', '    with: { auto-merge: true }\n')
        self.assertEqual(self.release_mode({
            'release-please-config.json': '{}', '.github/workflows/publish.yml': workflow,
        }), 'auto_merge')

    def test_release_please_non_ascii_filename(self):
        self.assertEqual(self.auto_merge_mode('      auto-merge: true\n', 'déploi ement.yml'), 'auto_merge')

    def test_release_please_auto_merge_value_variants(self):
        for release in ('      auto-merge: True\n', '      auto-merge: "true"\n', '      app-id: x\n      auto-merge: true\n'):
            with self.subTest(release=release):
                self.assertEqual(self.auto_merge_mode(release), 'auto_merge')
        self.assertEqual(self.auto_merge_mode('      auto-merge: truex\n'), 'manual')

    def test_release_please_inline_flow_mapping_with_other_keys(self):
        workflow = self.RELEASE_JOB.format(other='', release='').replace(
            '    with:\n', '    with: {app-id: x, auto-merge: true}\n')
        self.assertEqual(self.release_mode({
            'release-please-config.json': '{}', '.github/workflows/publish.yml': workflow,
        }), 'auto_merge')

    def test_release_please_local_workflow_call(self):
        workflow = self.RELEASE_JOB.format(other='', release='      auto-merge: true\n').replace(
            'acme/workflows/.github/workflows/release-please.yml@0123456789abcdef0123456789abcdef01234567',
            './.github/workflows/release-please.yml')
        self.assertEqual(self.release_mode({
            'release-please-config.json': '{}', '.github/workflows/publish.yml': workflow,
        }), 'auto_merge')

    def test_release_please_other_action_with_stray_auto_merge_is_manual(self):
        workflow = ('jobs:\n  notify:\n    runs-on: ubuntu-latest\n    steps:\n'
                    '      - uses: acme/release-please-notify@v1\n'
                    '      - uses: acme/merge@v1\n        with:\n          auto-merge: true\n')
        self.assertEqual(self.release_mode({
            'release-please-config.json': '{}', '.github/workflows/notify.yml': workflow,
        }), 'manual')

    def test_release_please_reads_base_not_worktree(self):
        workflow = self.RELEASE_JOB.format(other='', release='      auto-merge: true\n')
        self.release_mode({'release-please-config.json': '{}', '.github/workflows/publish.yml': workflow})
        self.assertEqual(pr_context.collect(self.root, 'base', 30, [])['release_please'], 'none')

    def test_release_please_unreadable_workflow_fails(self):
        (self.root / '.github' / 'workflows').mkdir(parents=True)
        (self.root / '.github' / 'workflows' / 'bad.yml').write_bytes(b'jobs:\n  x: \xff\n')
        (self.root / 'release-please-config.json').write_text('{}')
        self.git('add', '.')
        self.git('commit', '-qm', 'bad workflow')
        with self.assertRaisesRegex(ValueError, 'Cannot read workflow .github/workflows/bad.yml'):
            pr_context.collect(self.root, 'HEAD', 30, [])

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
