"""Popup ownership/lifecycle contracts; real rendering is tested in Sublime."""
import types
import unittest
from unittest.mock import Mock, patch

from test_adapter import PLUGIN, SUBLIME, Settings, View


class ThemePickerTests(unittest.TestCase):
    def setUp(self):
        self.view = View()
        self.prefs = Settings(theme='Default.sublime-theme')
        self.package = Settings()
        self.settings = {'Preferences.sublime-settings': self.prefs,
                         PLUGIN.SETTINGS_FILE: self.package}
        SUBLIME.load_settings.side_effect = self.settings.__getitem__
        SUBLIME.status_message.reset_mock()

    def tearDown(self):
        self.view.hide_popup()
        SUBLIME.load_settings.side_effect = None

    def open(self, **kwargs):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, **kwargs)
        return self.view.show_popup.call_args

    def test_export_uses_source_scheme_and_markdown_syntax_without_editing_source(self):
        self.view.config.set('color_scheme', 'Light')
        before = self.view.text, list(self.view.regions), self.view.count, dict(self.view.config)
        call = self.open()
        self.assertIn('color:#eeeeee', call.args[0])
        self.assertEqual((self.view.text, list(self.view.regions), self.view.count,
                          dict(self.view.config)), before)
        panel = self.view.created_panels[0]
        self.assertEqual(panel.config.get('color_scheme'), 'Light')
        self.assertEqual(panel.assign_syntax.call_args.args[0].scope, 'text.html.markdown')
        self.assertIn('# Heading 1', [text for text, _ in panel.exports])
        self.assertEqual(panel.exports[0][1], {'minihtml': True, 'enclosing_tags': False,
                                            'font_size': False, 'font_family': False})
        self.assertEqual(self.view.panels, {})
        self.view.win.focus_view.assert_not_called()
        self.view.win.run_command.assert_not_called()

    def test_custom_markdown_syntax_is_reused(self):
        syntax = types.SimpleNamespace(path='Packages/Local/MyMarkdown.sublime-syntax',
                                       scope='text.html.markdown.custom')
        self.view.syntax = lambda: syntax
        self.open()
        self.assertIs(self.view.created_panels[0].assign_syntax.call_args.args[0], syntax)

    def test_non_markdown_source_uses_builtin_markdown_for_examples(self):
        self.view.markdown = False
        self.package.set('markdown_only', False)
        self.open()
        self.assertEqual(self.view.created_panels[0].assign_syntax.call_args.args[0],
                         'Packages/Markdown/Markdown.sublime-syntax')

    def test_source_scheme_change_updates_existing_popup_without_reopening(self):
        self.view.config.set('color_scheme', 'Dark')
        self.open()
        self.view.config.set('color_scheme', 'Light')
        self.assertEqual(self.view.show_popup.call_count, 1)
        self.assertIn('color:#eeeeee', self.view.update_popup.call_args.args[0])
        self.assertTrue(self.view.is_popup_visible())
        self.assertEqual(self.view.panels, {})
        self.assertEqual(self.view.text, 'hello world')

    def test_global_theme_change_refreshes_popup(self):
        self.open()
        self.prefs.set('theme', 'Adaptive.sublime-theme')
        self.view.update_popup.assert_called_once()
        self.assertTrue(self.view.is_popup_visible())

    def test_global_scheme_change_refreshes_popup(self):
        self.open()
        self.prefs.set('color_scheme', 'Light')
        self.view.update_popup.assert_called_once()

    def test_refreshes_are_coalesced_and_pending_work_cannot_reopen_closed_popup(self):
        queued = []
        with patch.object(SUBLIME, 'set_timeout', side_effect=lambda fn, *args: queued.append(fn)):
            self.open()
            self.prefs.set('theme', 'Adaptive.sublime-theme')
            self.view.config.set('color_scheme', 'Light')
            self.assertEqual(len(queued), 1)
            self.view.hide_popup()
            queued.pop()()
        self.view.update_popup.assert_not_called()
        self.assertEqual(self.view.show_popup.call_count, 1)
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})

    def test_cancel_discards_callbacks_and_rejects_stale_navigation(self):
        call = self.open()
        navigate = call.kwargs['on_navigate']
        self.view.hide_popup()
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})
        navigate('action:bold')
        self.assertEqual(self.view.text, 'hello world')
        self.prefs.set('theme', 'Adaptive.sublime-theme')
        self.view.update_popup.assert_not_called()

    def test_replaced_popup_is_never_overwritten_by_late_theme_change(self):
        call = self.open()
        self.view.show_popup('<b>Another plugin</b>')
        self.prefs.set('color_scheme', 'Light')
        self.view.update_popup.assert_not_called()
        call.kwargs['on_navigate']('action:bold')
        self.assertEqual(self.view.text, 'hello world')

    def test_reopening_keeps_only_new_callbacks_even_if_old_hide_arrives_late(self):
        old = self.open()
        self.open()
        old.kwargs['on_hide']()
        self.assertEqual(len(self.prefs.callbacks), 1)
        self.assertEqual(len(self.view.config.callbacks), 1)
        self.prefs.set('theme', 'Adaptive.sublime-theme')
        self.view.update_popup.assert_called_once()

    def test_closing_view_cleans_up_and_prevents_pending_refresh(self):
        self.open()
        self.view.valid = False
        PLUGIN.MdFormatPickerListener().on_close(self.view)
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})
        self.prefs.set('theme', 'Adaptive.sublime-theme')
        self.view.update_popup.assert_not_called()

    def test_plugin_unload_closes_owned_popup_and_removes_callbacks(self):
        self.open()
        PLUGIN.plugin_unloaded()
        self.assertFalse(self.view.is_popup_visible())
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})

    def test_export_failure_is_reported_and_plain_safe_examples_remain_usable(self):
        def broken_panel(name, unlisted=False):
            panel = self.view._create_panel(name, unlisted)
            panel.export_to_html = Mock(side_effect=RuntimeError('export failed'))
            return panel

        self.view.win.create_output_panel.side_effect = broken_panel
        self.package.set('labels', {'bold': '<script>Bold</script>'})
        call = self.open()
        self.assertIn('&lt;script&gt;', call.args[0])
        self.assertNotIn('<script>', call.args[0])
        self.assertEqual(self.view.panels, {})
        self.assertIn('plain examples', SUBLIME.status_message.call_args.args[0])
        call.kwargs['on_navigate']('action:bold')
        self.assertEqual(self.view.text, '**hello** world')

    def test_failure_to_show_popup_leaks_no_watchers_or_panels(self):
        self.view.show_popup.side_effect = RuntimeError('view closed during open')
        self.open()
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})
        self.assertEqual(self.view.panels, {})

    def test_refresh_failure_closes_popup_and_releases_watchers(self):
        self.open()
        self.view.update_popup.side_effect = RuntimeError('view disappeared')
        self.prefs.set('theme', 'Adaptive.sublime-theme')
        self.assertFalse(self.view.is_popup_visible())
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})

    def test_observer_registration_failure_leaves_no_dead_popup(self):
        self.prefs.add_on_change = Mock(side_effect=RuntimeError('settings unavailable'))
        self.open()
        self.assertFalse(self.view.is_popup_visible())
        self.assertEqual(self.view.config.callbacks, {})
        self.assertEqual(self.view.panels, {})

    def test_searchable_picker_uses_no_preview_buffers_or_observers(self):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='search')
        self.assertEqual(self.view.created_panels, [])
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})
        self.view.win.show_quick_panel.assert_called_once()

    def test_separate_views_keep_independent_watchers_and_schemes(self):
        other = View()
        try:
            self.open()
            other.config.set('color_scheme', 'Light')
            PLUGIN.MdFormatPickerCommand(other).run(None)
            self.assertEqual(len(self.prefs.callbacks), 2)
            self.view.hide_popup()
            self.assertEqual(len(self.prefs.callbacks), 1)
            self.prefs.set('theme', 'Adaptive.sublime-theme')
            self.view.update_popup.assert_not_called()
            self.assertIn('color:#eeeeee', other.update_popup.call_args.args[0])
        finally:
            other.hide_popup()

    def test_save_of_scheme_asset_requests_refresh_but_normal_document_does_not(self):
        self.open()
        asset = Mock()
        asset.file_name.return_value = '/somewhere/Custom.sublime-color-scheme'
        PLUGIN.MdFormatPickerListener().on_post_save(asset)
        self.view.update_popup.assert_called_once()
        self.view.update_popup.reset_mock()
        asset.file_name.return_value = '/somewhere/document.md'
        PLUGIN.MdFormatPickerListener().on_post_save(asset)
        self.view.update_popup.assert_not_called()


    # S4: unrelated view settings (git gutter, LSP, repeat state...) must not
    # recreate preview panels while the picker is open.
    def test_unrelated_setting_changes_do_not_rerender(self):
        self.view.config.set('color_scheme', 'Dark')
        self.open()
        created = len(self.view.created_panels)
        for key, value in (('git_gutter_is_enabled', True), ('lsp_active', 1),
                           (PLUGIN.LAST_ACTION_KEY, {'action': 'bold'}),
                           ('markdown_formatting', {'labels': {'bold': 'B'}})):
            self.view.config.set(key, value)
        self.prefs.set('word_wrap', True)
        self.view.update_popup.assert_not_called()
        self.assertEqual(len(self.view.created_panels), created)
        for key, value in (('font_size', 20), ('font_face', 'Mono'),
                           ('syntax', 'Packages/Local/Other.sublime-syntax')):
            self.view.update_popup.reset_mock()
            self.view.config.set(key, value)
            self.view.update_popup.assert_called_once()
        self.view.update_popup.reset_mock()
        self.view.config.erase('color_scheme')
        self.view.update_popup.assert_called_once()

    def test_explicit_refresh_still_rerenders_without_setting_change(self):
        self.open()
        PLUGIN.sublime_picker.refresh_all()
        self.view.update_popup.assert_called_once()

    # S3: a failing plain fallback must not leave a registered, unclosed
    # session behind, which would later hide another plugin's popup.
    def test_failed_plain_fallback_unregisters_session_and_spares_other_popups(self):
        def broken_panel(name, unlisted=False):
            panel = self.view._create_panel(name, unlisted)
            panel.export_to_html = Mock(side_effect=RuntimeError('export failed'))
            return panel

        self.view.win.create_output_panel.side_effect = broken_panel
        with patch.object(PLUGIN, 'render_picker', side_effect=KeyError('render failed')):
            PLUGIN.MdFormatPickerCommand(self.view).run(None)
        self.assertEqual(PLUGIN.sublime_picker._SESSIONS, {})
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})
        self.assertEqual(self.view.panels, {})
        self.view.show_popup.assert_not_called()
        self.assertIn('could not be opened', SUBLIME.status_message.call_args.args[0])
        # Another plugin's popup survives the next opening attempt.
        self.view.win.create_output_panel.side_effect = self.view._create_panel
        self.view.show_popup('<b>Another plugin</b>')
        self.view.hide_popup.reset_mock()
        sublime_picker = PLUGIN.sublime_picker
        sublime_picker.close_view(self.view, hide=True)
        self.view.hide_popup.assert_not_called()

    def test_unexpected_render_error_during_refresh_closes_session(self):
        calls = []

        def render(highlight):
            calls.append(highlight)
            if len(calls) > 1:
                raise KeyError('late failure')
            return '<b>ok</b>'

        PLUGIN.sublime_picker.show(self.view, render, lambda target: None, 0)
        self.prefs.set('theme', 'Adaptive.sublime-theme')
        self.assertEqual(PLUGIN.sublime_picker._SESSIONS, {})
        self.assertFalse(self.view.is_popup_visible())
        self.assertEqual(self.prefs.callbacks, {})
        self.assertEqual(self.view.config.callbacks, {})
        self.assertEqual(self.view.panels, {})


if __name__ == '__main__':
    unittest.main()
