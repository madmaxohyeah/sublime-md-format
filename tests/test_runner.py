"""Keep CI Python settings away from the editor's embedded Python."""
import unittest

from scripts import run_editor_smoke as runner


class EditorEnvironmentTests(unittest.TestCase):
    def test_child_uses_bundled_runtime_without_mutating_parent_environment(self):
        parent = {
            'LD_LIBRARY_PATH': '/runner/python/lib',
            'PYTHONHOME': '/runner/python',
            'PYTHONPATH': '/runner/site-packages',
            'HOME': '/isolated/home',
            'PATH': '/usr/bin',
        }
        child = runner.editor_environment(parent, ':123', '/isolated/evidence')
        for variable in ('LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH'):
            self.assertNotIn(variable, child)
            self.assertIn(variable, parent)
        self.assertEqual(child['HOME'], parent['HOME'])
        self.assertEqual(child['PATH'], parent['PATH'])
        self.assertEqual(child['DISPLAY'], ':123')
        self.assertEqual(child['MD_FORMAT_EVIDENCE'], '/isolated/evidence')
