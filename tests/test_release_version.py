import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_version', ROOT / 'scripts/check-release-version.py')
release_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_version)


class ReleaseVersionTests(unittest.TestCase):
    def test_valid_and_invalid_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'plugin.json'
            manifest.write_text(json.dumps({'version': '2.0.0'}))
            self.assertEqual(release_version.check('v2.0.0', manifest), '2.0.0')
            for tag in ('2.0.0', 'v02.0.0', 'v2.0.1', 'v2.0.0-rc.1', 'v2.0.0/other'):
                with self.subTest(tag=tag), self.assertRaises(ValueError):
                    release_version.check(tag, manifest)


if __name__ == '__main__':
    unittest.main()
