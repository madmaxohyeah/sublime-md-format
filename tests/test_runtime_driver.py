"""Acceptance probes must reject a theme notification that never rerenders."""
import types
import unittest
from unittest.mock import Mock

from test_adapter import Settings
from scripts.runtime_driver import PickerRuntimeChecks


class StopAfterThemeCheck(Exception):
    pass


class ThemeRefreshEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.probe = PickerRuntimeChecks.__new__(PickerRuntimeChecks)
        self.session = types.SimpleNamespace(_render=Mock(return_value='highlighted'))
        self.probe.session = Mock(return_value=self.session)
        self.preview = Mock()
        self.probe.assert_preview = self.preview
        self.probe.prefs = Settings(theme='Default.sublime-theme')
        self.probe.later = Mock()
        self.probe.view = Mock()
        self.probe.view.is_popup_visible.return_value = True
        self.probe.report = {'picker_appearance': {}}

    def prepare(self):
        self.probe.after_global_scheme()
        self.preview.side_effect = StopAfterThemeCheck

    def test_visible_popup_without_theme_rerender_fails_even_if_colors_still_match(self):
        self.prepare()
        try:
            self.probe.after_theme()
        except AssertionError as error:
            self.assertRegex(str(error), 'theme.*render')
        except StopAfterThemeCheck:
            self.fail('A theme change reached the color oracle without proving any rerender')
        else:
            self.fail('The missing theme rerender was accepted')

    def test_visible_popup_records_actual_theme_rerender(self):
        self.prepare()
        self.assertEqual(self.session._render(), 'highlighted')
        with self.assertRaises(StopAfterThemeCheck):
            self.probe.after_theme()
        self.assertEqual(self.probe.report.get('picker_theme_refresh'), {
            'automatic_render_calls': 1, 'dismissed_by_editor': False,
        })

    def test_editor_dismissal_is_recorded_instead_of_claiming_live_rerender(self):
        self.prepare()
        self.probe.view.is_popup_visible.return_value = False
        with self.assertRaises(StopAfterThemeCheck):
            self.probe.after_theme()
        self.probe.view.run_command.assert_called_once_with('md_format_picker')
        self.assertEqual(self.probe.report.get('picker_theme_refresh'), {
            'automatic_render_calls': 0, 'dismissed_by_editor': True,
        })
