import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_package', ROOT / 'scripts/build_package.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class PackageTests(unittest.TestCase):
    def test_reproducible_installable_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.sublime-package'
            second = Path(directory) / 'second.sublime-package'
            BUILD.build(first)
            BUILD.build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                self.assertEqual(names, set(BUILD.PACKAGE_FILES))
                self.assertIn('markdown_formatting.py', names)
                self.assertIn('mdformat/engine.py', names)
                self.assertIn('mdformat/sublime_picker.py', names)
                self.assertIn('Context.sublime-menu', names)
                self.assertEqual(archive.read('.python-version').strip(), b'3.8')
                self.assertFalse(any(name.startswith(('tests/', '.git/', 'scripts/')) for name in names))
                for name in names:
                    self.assertEqual(archive.read(name), (ROOT / name).read_bytes())
                    if name.endswith(('.sublime-menu', '.sublime-commands', '.sublime-settings')):
                        json.loads(archive.read(name))
            self.assertEqual(len(hashlib.sha256(first.read_bytes()).hexdigest()), 64)

    def test_context_menu_covers_all_builtins(self):
        from mdformat.catalog import ACTIONS
        menu = json.loads((ROOT / 'Context.sublime-menu').read_text())
        found = []
        def walk(rows):
            for row in rows:
                if row.get('command') == 'md_format':
                    found.append(row['args']['action'])
                walk(row.get('children', []))
        walk(menu)
        self.assertEqual(set(found), set(ACTIONS))
        self.assertEqual(len(found), len(set(found)))
