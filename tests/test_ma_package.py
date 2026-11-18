"""Local package recipe tests, not Docker or Supervisor installation tests."""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import shutil

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packaging/music_assistant'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PackageTests(unittest.TestCase):
    def test_self_contained_context_is_hash_manifested_and_never_overwritten(self):
        prepare = load('prepare_ma_package', PACKAGE / 'prepare.py')
        with tempfile.TemporaryDirectory(dir='/data/v2/cache/opencode') as parent:
            target = Path(parent) / 'local_app'
            hashes = prepare.prepare(target)
            self.assertEqual(json.loads((target / 'build-context.json').read_text()), hashes)
            for name, expected in hashes.items():
                self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), expected)
            self.assertIn('patches/alarm_commands.py.txt', hashes)
            with self.assertRaises(FileExistsError):
                prepare.prepare(target)

    def test_manifest_has_separate_data_identity_no_floating_image_or_updater(self):
        manifest = json.loads((PACKAGE / 'config.json').read_text())
        self.assertEqual(manifest['slug'], 'music_assistant_alarmclock')
        self.assertNotIn('image', manifest)
        self.assertEqual(list(manifest['options']), list(manifest['schema']))
        self.assertNotIn('all_addon_configs', str(manifest))
        docker = (PACKAGE / 'Dockerfile').read_text()
        self.assertIn('server@sha256:7eb272e2', docker)
        self.assertNotIn('latest', docker)
        self.assertNotIn('pip install', docker)
        self.assertNotIn('git clone', docker)

    def test_installer_fails_before_writes_when_source_hashes_differ(self):
        spec = load('package_builder', ROOT / 'prototypes/ma_one_shot/build_patch.py')
        previous = sys.modules.get('build_patch')
        sys.modules['build_patch'] = spec
        try:
            installer = load('package_installer', PACKAGE / 'install.py')
            with tempfile.TemporaryDirectory(dir='/data/v2/cache/opencode') as directory:
                root = Path(directory)
                with self.assertRaises(FileNotFoundError):
                    installer.install(root)
                self.assertFalse(list(root.iterdir()))
        finally:
            if previous is None:
                sys.modules.pop('build_patch', None)
            else:
                sys.modules['build_patch'] = previous

    def test_production_commands_and_installer_parse(self):
        ast.parse((PACKAGE / 'install.py').read_text())
        source = (ROOT / 'prototypes/ma_one_shot/alarm_commands.py.txt').read_text()
        tree = ast.parse('class Host:\n' + source)
        methods = [node for node in tree.body[0].body if isinstance(node, ast.AsyncFunctionDef)]
        self.assertEqual(len(methods), 3)
        for method in methods:
            self.assertTrue(any('Scope.QUEUES_CONTROL' in ast.unparse(node) for node in method.decorator_list))

    @unittest.skipUnless(sys.version_info >= (3, 14) and Path('/data/v2/cache/opencode/ma-native-runtime/server').is_dir(),
                         'Requires Python 3.14 (matching pinned MA) and pristine source checkout')
    def test_install_generated_candidates_against_all_pristine_source_hashes(self):
        builder = load('package_builder_real', ROOT / 'prototypes/ma_one_shot/build_patch.py')
        previous = sys.modules.get('build_patch')
        sys.modules['build_patch'] = builder
        try:
            installer = load('package_installer_real', PACKAGE / 'install.py')
            lock = json.loads((ROOT / 'prototypes/ma_one_shot/upstream.json').read_text())
            with tempfile.TemporaryDirectory(dir='/data/v2/cache/opencode') as directory:
                root = Path(directory)
                for name in lock['sha256']:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path('/data/v2/cache/opencode/ma-native-runtime/server') / name, path)
                installer.install(root)
                receipt = json.loads((root / 'alarmclock-build.json').read_text())
                self.assertEqual(receipt['protocol'], 2)
                self.assertEqual(len(receipt['sha256']), 4)
                for name, expected in receipt['sha256'].items():
                    self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)
                with self.assertRaises(ValueError):
                    installer.install(root)
        finally:
            if previous is None:
                sys.modules.pop('build_patch', None)
            else:
                sys.modules['build_patch'] = previous


if __name__ == '__main__':
    unittest.main()
