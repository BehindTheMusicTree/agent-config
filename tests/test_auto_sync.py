import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('auto_sync', ROOT / 'scripts/manage-auto-sync.py')
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class AutoSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='auto sync ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.active = self.root / 'current'
        (self.active / 'scripts').mkdir(parents=True)
        (self.active / 'scripts/prepare-remote-release.py').write_text('# updater\n')
        self.state = self.root / 'state'
        self.agents = self.root / 'agents'

    def test_plist_points_to_active_release_and_is_valid(self):
        config = auto.build_plist(self.active, self.state, 3600, '/bin:/usr/bin')
        self.assertEqual(plistlib.loads(plistlib.dumps(config)), config)
        self.assertEqual(config['ProgramArguments'][1], str(self.active / 'scripts/prepare-remote-release.py'))
        self.assertIn('--sync-local', config['ProgramArguments'])
        self.assertEqual(config['ProgramArguments'][-2:], ['--releases', str(self.state / 'releases')])
        self.assertEqual(config['StartInterval'], 3600)

    def test_rejects_too_short_interval_and_missing_updater(self):
        with self.assertRaises(ValueError):
            auto.build_plist(self.active, self.state, 5, '/bin')
        with self.assertRaises(ValueError):
            auto.build_plist(self.root / 'missing', self.state, 3600, '/bin')

    def test_profile_job_passes_profile_and_release_directory(self):
        profile = self.root / 'profile.json'
        profile.write_text('{}')
        config = auto.build_plist(self.active, self.state, 3600, '/bin', profile)
        self.assertEqual(config['ProgramArguments'][-4:], [
            '--releases', str(self.state / 'releases'), '--profile', str(profile),
        ])

    def test_install_refuses_unmanaged_file(self):
        self.agents.mkdir()
        target = self.agents / (auto.LABEL + '.plist')
        target.write_text('personal')
        with patch.object(auto.sys, 'platform', 'darwin'):
            with self.assertRaisesRegex(ValueError, 'unmanaged'):
                auto.install(self.active, self.state, self.agents, 3600, '/bin')
        self.assertEqual(target.read_text(), 'personal')

    def test_failed_bootstrap_restores_old_configuration(self):
        with patch.object(auto.sys, 'platform', 'darwin'), patch.object(auto.subprocess, 'run') as run:
            run.return_value.returncode = 0
            target = auto.install(self.active, self.state, self.agents, 3600, '/bin')
            original = target.read_bytes()
            marker = (self.state / 'launchd-installed.plist').read_bytes()
            failure = type('Result', (), {'returncode': 1, 'stderr': 'failure'})()
            success = type('Result', (), {'returncode': 0, 'stderr': ''})()
            run.side_effect = [success, failure, success, success]
            with self.assertRaisesRegex(RuntimeError, 'Failed to start'):
                auto.install(self.active, self.state, self.agents, 7200, '/bin')
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual((self.state / 'launchd-installed.plist').read_bytes(), marker)

    def test_install_and_remove_managed_job(self):
        with patch.object(auto.sys, 'platform', 'darwin'), patch.object(auto.subprocess, 'run') as run:
            run.return_value.returncode = 0
            target = auto.install(self.active, self.state, self.agents, 3600, '/bin')
            self.assertTrue(target.exists())
            self.assertTrue((self.state / 'launchd-installed.plist').exists())
            auto.uninstall(self.state, self.agents)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
