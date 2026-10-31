import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_skills', ROOT / 'scripts/sync-codex-skills.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skill sync ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / 'codex skills'

    def source(self, name, names):
        source = self.root / name
        for skill in names:
            directory = source / 'skills' / skill
            directory.mkdir(parents=True)
            (directory / 'SKILL.md').write_text('# skill\n')
        return source

    def run_sync(self, source):
        desired, changes = sync.plan(source, self.destination)
        sync.apply(self.destination, desired, changes)

    def test_add_change_delete_and_idempotence(self):
        first = self.source('v1', ['one', 'old'])
        second = self.source('v2', ['one', 'new'])
        self.run_sync(first)
        personal = self.destination / 'personal'
        personal.mkdir()
        self.run_sync(second)
        self.assertEqual(os.readlink(self.destination / 'one'), str((second / 'skills/one').resolve()))
        self.assertTrue((self.destination / 'new').is_symlink())
        self.assertFalse((self.destination / 'old').is_symlink())
        self.assertTrue(personal.is_dir())
        self.assertEqual(sync.plan(second, self.destination)[1], [])

    def test_conflict_does_not_modify_anything(self):
        source = self.source('v1', ['one', 'two'])
        self.destination.mkdir()
        (self.destination / 'two').mkdir()
        with self.assertRaisesRegex(ValueError, 'existing entry'):
            sync.plan(source, self.destination)
        self.assertFalse((self.destination / 'one').exists())

    def test_modified_managed_link_blocks_update(self):
        first = self.source('v1', ['one'])
        second = self.source('v2', ['one'])
        self.run_sync(first)
        link = self.destination / 'one'
        link.unlink()
        link.symlink_to(self.root / 'personal')
        with self.assertRaisesRegex(ValueError, 'modified'):
            sync.plan(second, self.destination)

    def test_explicit_migration_preserves_unrelated_links(self):
        legacy = self.source('legacy', ['one', 'removed'])
        (legacy / '.git').mkdir()
        release = self.source('v2', ['one', 'new'])
        self.destination.mkdir()
        for name in ('one', 'removed'):
            (self.destination / name).symlink_to(legacy / 'skills' / name)
        unrelated = self.destination / 'personal'
        unrelated.symlink_to(self.root / 'other')
        desired, changes = sync.plan(release, self.destination, legacy)
        sync.apply(self.destination, desired, changes)
        self.assertEqual((self.destination / 'one').resolve(), (release / 'skills/one').resolve())
        self.assertFalse((self.destination / 'removed').is_symlink())
        self.assertTrue(unrelated.is_symlink())
        self.assertTrue((self.destination / 'new').is_symlink())

    def test_multisource_adoption_keeps_source_ownership(self):
        legacy = self.source('legacy', ['common', 'ops'])
        (legacy / '.git').mkdir()
        public = self.source('public', ['common'])
        private = self.source('private', ['ops'])
        self.destination.mkdir()
        for name in ('common', 'ops'):
            (self.destination / name).symlink_to(legacy / 'skills' / name)
        desired, changes = sync.plan_sources({'public': public, 'private': private}, self.destination, legacy)
        sync.apply(self.destination, desired, changes)
        state = json.loads((self.destination / sync.STATE).read_text())
        self.assertEqual(state['version'], 2)
        self.assertEqual(state['owners'], {'common': 'public', 'ops': 'private'})
        with self.assertRaisesRegex(ValueError, 'Missing managed sources'):
            sync.plan_sources({'public': public}, self.destination)

    def test_empty_source_does_not_delete_existing_links(self):
        source = self.source('v1', ['one'])
        self.run_sync(source)
        empty = self.root / 'empty'
        (empty / 'skills').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'empty'):
            sync.plan(empty, self.destination)
        self.assertTrue((self.destination / 'one').is_symlink())

    def test_multiple_sources_are_reconciled_together(self):
        public = self.source('public', ['common'])
        private = self.source('private', ['ops'])
        desired, changes = sync.plan_sources({'public': public, 'private': private}, self.destination)
        sync.apply(self.destination, desired, changes)
        self.assertEqual((self.destination / 'common').resolve(), (public / 'skills/common').resolve())
        self.assertEqual((self.destination / 'ops').resolve(), (private / 'skills/ops').resolve())
        self.assertEqual(sync.plan_sources({'public': public, 'private': private}, self.destination)[1], [])

    def test_multiple_sources_refuse_name_collisions(self):
        public = self.source('public', ['same'])
        private = self.source('private', ['same'])
        with self.assertRaisesRegex(ValueError, 'collision'):
            sync.plan_sources({'public': public, 'private': private}, self.destination)
        self.assertFalse(self.destination.exists())

    def test_migration_blocks_missing_sources_and_legacy_updater(self):
        legacy = self.source('legacy', ['common', 'ops'])
        self.run_sync(legacy)
        public = self.source('public', ['common'])
        private = self.source('private', ['ops'])
        desired, changes = sync.plan_sources({'public': public, 'private': private}, self.destination)
        sync.apply(self.destination, desired, changes)
        state = json.loads((self.destination / sync.STATE).read_text())
        self.assertEqual(state['owners'], {'common': 'public', 'ops': 'private'})
        private_replacement = self.source('private-replacement', ['common', 'ops'])
        public_replacement = self.source('public-replacement', ['new'])
        with self.assertRaisesRegex(ValueError, 'ownership changed'):
            sync.plan_sources({'public': public_replacement, 'private': private_replacement}, self.destination)
        with self.assertRaisesRegex(ValueError, 'Missing managed sources'):
            sync.plan_sources({'public': public}, self.destination)
        with self.assertRaisesRegex(ValueError, 'multi-source synchronizer'):
            sync.plan(public, self.destination)
        self.assertTrue((self.destination / 'ops').is_symlink())
        desired, changes = sync.plan_sources({'public': public}, self.destination, remove_sources=['private'])
        sync.apply(self.destination, desired, changes)
        self.assertFalse((self.destination / 'ops').is_symlink())


if __name__ == '__main__':
    unittest.main()
