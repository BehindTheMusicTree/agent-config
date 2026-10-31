import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_release', ROOT / 'scripts/prepare-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PrepareReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='release test ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / 'source'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Release Test')
        self.git('config', 'user.email', 'release@example.invalid')
        (self.repo / '.claude-plugin').mkdir()
        self.manifest = self.repo / '.claude-plugin/plugin.json'
        self.manifest.write_text(json.dumps({'version': '1.0.0'}))
        (self.repo / 'tracked.txt').write_text('released')
        self.git('add', '.')
        self.git('commit', '-qm', 'release')
        self.git('tag', 'v1.0.0')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True, text=True).stdout

    def test_snapshot_is_from_tag_not_dirty_checkout(self):
        (self.repo / 'tracked.txt').write_text('local change')
        (self.repo / 'untracked.txt').write_text('private')
        target = release.prepare(self.repo, 'v1.0.0', self.base / 'releases')
        self.assertEqual((target / 'tracked.txt').read_text(), 'released')
        self.assertFalse((target / 'untracked.txt').exists())
        self.assertEqual(json.loads((target / '.agent-config-release.json').read_text())['tag'], 'v1.0.0')
        self.assertEqual((self.repo / 'tracked.txt').read_text(), 'local change')

    def test_rejects_mismatched_version_and_modified_snapshot(self):
        self.git('tag', 'v2.0.0')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            release.prepare(self.repo, 'v2.0.0', self.base / 'releases')
        target = release.prepare(self.repo, 'v1.0.0', self.base / 'releases')
        self.assertEqual(release.prepare(self.repo, 'v1.0.0', self.base / 'releases'), target)
        (target / 'tracked.txt').write_text('modified snapshot')
        with self.assertRaisesRegex(ValueError, 'does not match release'):
            release.prepare(self.repo, 'v1.0.0', self.base / 'releases')

    def test_rejects_non_stable_tag(self):
        with self.assertRaisesRegex(ValueError, 'Invalid stable'):
            release.prepare(self.repo, 'v1.0.0-rc.1', self.base / 'releases')


if __name__ == '__main__':
    unittest.main()
