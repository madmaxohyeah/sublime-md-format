"""Adapter contract tests. Real editor acceptance lives in scripts/runtime_driver.py."""
import contextlib
import importlib
import io
import sys
import types
import unittest
from html import escape
from pathlib import Path
from unittest.mock import Mock, patch


class Region:
    def __init__(self, a, b=None):
        self.a, self.b = a, a if b is None else b

    def begin(self):
        return min(self.a, self.b)

    def end(self):
        return max(self.a, self.b)


class Selection(list):
    def add(self, region):
        self.append(region)


class Settings(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callbacks = {}

    def set(self, key, value):
        changed = self.get(key) != value
        self[key] = value
        if changed:
            for callback in list(self.callbacks.values()):
                callback()

    def erase(self, key):
        if key in self:
            del self[key]
            for callback in list(self.callbacks.values()):
                callback()

    def add_on_change(self, tag, callback):
        self.callbacks[tag] = callback

    def clear_on_change(self, tag):
        self.callbacks.pop(tag, None)


class Preview:
    """API interaction fake, not evidence of real syntax highlighting."""
    def __init__(self):
        self.config = Settings()
        self.text = ''
        self.assign_syntax = Mock()
        self.set_scratch = Mock()
        self.set_read_only = Mock()
        self.exports = []

    def settings(self):
        return self.config

    def run_command(self, name, args=None):
        if name == 'insert':
            self.text = args['characters']
        elif name != 'select_all':
            raise AssertionError(name)

    def export_to_html(self, **kwargs):
        self.exports.append((self.text, kwargs))
        color = '#eeeeee' if self.config.get('color_scheme') == 'Light' else '#222222'
        return '<span style="color:{}">{}</span>'.format(
            color, escape(self.text).replace('\n', '<br>'))


class View:
    def __init__(self, text='hello world'):
        self.text = text
        self.regions = Selection([Region(0, 5)])
        self.config = Settings()
        self.readonly = False
        self.valid = True
        self.markdown = True
        self.count = 0
        self.replacements = []
        self.win = Mock()
        self.win.project_data.return_value = None
        self.panels = {}
        self.created_panels = []
        self.win.create_output_panel.side_effect = self._create_panel
        self.win.destroy_output_panel.side_effect = lambda name: self.panels.pop(name, None)
        self.popup_visible = False
        self.popup_hide = None
        self.show_popup = Mock(side_effect=self._show_popup)
        self.hide_popup = Mock(side_effect=self._hide_popup)
        self.update_popup = Mock()

    def id(self):
        return id(self)

    def syntax(self):
        return types.SimpleNamespace(path='Packages/Markdown/Markdown.sublime-syntax',
                                     scope='text.html.markdown' if self.markdown else 'text.plain')

    def _create_panel(self, name, unlisted=False):
        assert unlisted
        panel = Preview()
        self.panels[name] = panel
        self.created_panels.append(panel)
        return panel

    def _show_popup(self, content, **kwargs):
        self._hide_popup()
        self.popup_visible = True
        self.popup_hide = kwargs.get('on_hide')

    def _hide_popup(self):
        callback = self.popup_hide
        self.popup_visible = False
        self.popup_hide = None
        if callback:
            callback()

    def is_popup_visible(self):
        return self.popup_visible

    def settings(self):
        return self.config

    def window(self):
        return self.win

    def match_selector(self, point, selector):
        return self.markdown

    def is_read_only(self):
        return self.readonly

    def is_valid(self):
        return self.valid

    def change_count(self):
        return self.count

    def size(self):
        return len(self.text)

    def substr(self, region):
        return self.text[region.begin():region.end()]

    def sel(self):
        return self.regions

    def replace(self, edit, region, text):
        self.replacements.append((region.begin(), region.end(), text))
        self.text = self.text[:region.begin()] + text + self.text[region.end():]
        self.count += 1

    def show(self, region):
        pass

    def run_command(self, name, args=None):
        cls = {'md_format': PLUGIN.MdFormatCommand}[name]
        cls(self).run(None, **(args or {}))


class TextCommand:
    def __init__(self, view):
        self.view = view


class WindowCommand:
    def __init__(self, window):
        self.window = window


SUBLIME = types.ModuleType('sublime')
SUBLIME.Region = Region
SUBLIME.status_message = Mock()
SUBLIME.load_settings = Mock(return_value=Settings())
SUBLIME.COOPERATE_WITH_AUTO_COMPLETE = 0
SUBLIME.KEEP_OPEN_ON_FOCUS_LOST = 1
SUBLIME.set_timeout = lambda fn, *args: fn()
SUBLIME_PLUGIN = types.ModuleType('sublime_plugin')
SUBLIME_PLUGIN.TextCommand = TextCommand
SUBLIME_PLUGIN.WindowCommand = WindowCommand
SUBLIME_PLUGIN.EventListener = object
sys.modules['sublime'] = SUBLIME
sys.modules['sublime_plugin'] = SUBLIME_PLUGIN
package = types.ModuleType('MarkdownFormatting')
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules['MarkdownFormatting'] = package
PLUGIN = importlib.import_module('MarkdownFormatting.markdown_formatting')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        SUBLIME.load_settings.side_effect = None
        SUBLIME.load_settings.return_value = Settings()
        SUBLIME.status_message.reset_mock()
        self.view = View()

    def tearDown(self):
        self.view.hide_popup()

    def test_edits_target_only_selected_region(self):
        PLUGIN.MdFormatCommand(self.view).run(None, action='bold')
        self.assertEqual(self.view.text, '**hello** world')
        self.assertEqual(self.view.replacements, [(0, 5, '**hello**')])
        self.assertEqual([(r.a, r.b) for r in self.view.sel()], [(2, 7)])

    def test_readonly_blocks_direct_execution(self):
        self.view.readonly = True
        cmd = PLUGIN.MdFormatCommand(self.view)
        self.assertFalse(cmd.is_enabled(action='bold'))
        cmd.run(None, action='bold')
        self.assertEqual(self.view.text, 'hello world')

    def test_profile_blocks_direct_execution(self):
        self.view.config.set('markdown_formatting', {'profile': 'commonmark'})
        cmd = PLUGIN.MdFormatCommand(self.view)
        self.assertFalse(cmd.is_visible(action='strikethrough'))
        cmd.run(None, action='strikethrough')
        self.assertEqual(self.view.text, 'hello world')

    def test_hidden_action_blocks_execution(self):
        SUBLIME.load_settings.return_value = Settings(hidden_actions=['bold'])
        PLUGIN.MdFormatCommand(self.view).run(None, action='bold')
        self.assertEqual(self.view.text, 'hello world')

    def test_critic_default_edits_and_explicit_false_blocks_direct_execution(self):
        PLUGIN.MdFormatCommand(self.view).run(None, action='critic_addition')
        self.assertEqual(self.view.text, '{++hello++} world')
        disabled = View()
        disabled.config.set('markdown_formatting', {'enable_critic_markup': False})
        PLUGIN.MdFormatCommand(disabled).run(None, action='critic_addition')
        self.assertEqual(disabled.text, 'hello world')

    def test_scope_and_opt_out(self):
        self.view.markdown = False
        # Outside Markdown the root is hidden where the platform honors it (Linux);
        # Windows and macOS keep the heading, with its always-visible Settings leaf.
        self.assertFalse(PLUGIN.MdFormatMenuCommand(self.view).is_visible())
        for group in ('Headings', 'Lists', 'Insert', 'Review'):
            self.assertFalse(PLUGIN.MdFormatMenuCommand(self.view).is_visible(group=group))
        self.assertFalse(PLUGIN.MdFormatPickerCommand(self.view).is_visible())
        self.assertFalse(PLUGIN.MdFormatRepeatCommand(self.view).is_visible())
        self.assertFalse(PLUGIN.MdFormatProfileCommand(self.view).is_visible())
        self.view.config.set('markdown_formatting', {'markdown_only': False})
        self.assertTrue(PLUGIN.MdFormatMenuCommand(self.view).is_visible())
        for group in ('Headings', 'Lists', 'Insert', 'Review'):
            self.assertTrue(PLUGIN.MdFormatMenuCommand(self.view).is_visible(group=group))

    def test_context_menu_opt_out_hides_root_in_markdown(self):
        self.assertTrue(PLUGIN.MdFormatMenuCommand(self.view).is_visible())
        self.view.config.set('markdown_formatting', {'show_in_context_menu': False})
        self.assertFalse(PLUGIN.MdFormatMenuCommand(self.view).is_visible())
        self.assertFalse(PLUGIN.MdFormatMenuCommand(self.view).is_visible(group='Headings'))
        self.assertTrue(PLUGIN.MdFormatCommand(self.view).is_visible(action='bold'))
        SUBLIME.load_settings.return_value = Settings(show_in_context_menu='no')
        self.view.config.set('markdown_formatting', {})
        self.assertTrue(PLUGIN.MdFormatMenuCommand(self.view).is_visible())

    def test_layered_settings_and_malformed_overrides(self):
        SUBLIME.load_settings.return_value = Settings(profile='commonmark')
        self.view.win.project_data.return_value = {'settings': {'markdown_formatting': {'profile': 'multimarkdown'}}}
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'multimarkdown')
        self.view.config.set('markdown_formatting', {'profile': 'gfm'})
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'gfm')
        self.view.config.set('markdown_formatting', ['invalid'])
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'multimarkdown')
        self.view.win.project_data.return_value = ['invalid']
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'commonmark')

    def test_malformed_project_and_view_fields_preserve_valid_lower_layers(self):
        global_values = {
            'profile': 'commonmark',
            'markdown_only': False,
            'hidden_actions': ['bold'],
            'labels': {'bold': 'Strong'},
            'picker_order': ['italic'],
            'styles': {'bold': {'color': '#abc'}},
            'custom_formats': [
                {'label': 'Mark', 'prefix': '<mark>', 'suffix': '</mark>'}
            ],
            'enable_critic_markup': True,
            'select_word_on_empty': False,
            'bullet_marker': '+',
            'emphasis_marker': '_',
            'strong_marker': '__',
            'fence_language': 'python',
            'link_url': '/global',
        }
        invalid = {
            'profile': 'invalid',
            'markdown_only': 0,
            'hidden_actions': 'bold',
            'labels': ['Strong'],
            'picker_order': {'first': 'italic'},
            'styles': ['bold'],
            'custom_formats': {'label': 'Mark'},
            'enable_critic_markup': 1,
            'select_word_on_empty': None,
            'bullet_marker': True,
            'emphasis_marker': '**',
            'strong_marker': '*',
            'fence_language': 'python\nhtml',
            'link_url': '/project\nnext',
        }
        SUBLIME.load_settings.return_value = Settings(global_values)
        self.view.win.project_data.return_value = {
            'settings': {'markdown_formatting': invalid}
        }
        self.assertEqual(
            PLUGIN.settings_for(self.view),
            PLUGIN.resolve_settings(global_values),
        )

        project_values = {
            'profile': 'multimarkdown',
            'markdown_only': True,
            'hidden_actions': ['italic'],
            'labels': {'italic': 'Slant'},
            'picker_order': ['link'],
            'styles': {'italic': {'italic': True}},
            'custom_formats': [
                {'label': 'Key', 'prefix': '<kbd>', 'suffix': '</kbd>'}
            ],
            'enable_critic_markup': False,
            'select_word_on_empty': True,
            'bullet_marker': '*',
            'emphasis_marker': '*',
            'strong_marker': '**',
            'fence_language': 'ruby',
            'link_url': '/project',
        }
        self.view.win.project_data.return_value = {
            'settings': {'markdown_formatting': project_values}
        }
        self.view.config.set('markdown_formatting', invalid)
        self.assertEqual(
            PLUGIN.settings_for(self.view),
            PLUGIN.resolve_settings(project_values),
        )

    def test_view_settings_can_explicitly_clear_project_containers(self):
        SUBLIME.load_settings.return_value = Settings(profile='commonmark')
        self.view.win.project_data.return_value = {
            'settings': {
                'markdown_formatting': {
                    'profile': 'multimarkdown',
                    'hidden_actions': ['bold'],
                    'labels': {'bold': 'Strong'},
                    'picker_order': ['link'],
                    'styles': {'bold': {'bold': True}},
                    'custom_formats': [
                        {'label': 'Mark', 'prefix': '<mark>', 'suffix': '</mark>'}
                    ],
                    'enable_critic_markup': True,
                }
            }
        }
        self.view.config.set('markdown_formatting', {
            'profile': 'gfm',
            'hidden_actions': [],
            'labels': {},
            'styles': {},
            'custom_formats': [],
            'enable_critic_markup': False,
        })

        settings = PLUGIN.settings_for(self.view)

        self.assertEqual(settings['profile'], 'gfm')
        self.assertEqual(settings['hidden_actions'], [])
        self.assertEqual(settings['labels'], {})
        self.assertEqual(settings['picker_order'], ['link'])
        self.assertEqual(settings['styles'], {})
        self.assertEqual(settings['custom_formats'], [])
        self.assertIs(settings['enable_critic_markup'], False)

    def test_custom_format_only_resolves_configured_index(self):
        SUBLIME.load_settings.return_value = Settings(custom_formats=[{'label': 'Mark', 'prefix': '<mark>', 'suffix': '</mark>', 'placeholder': 'text'}])
        PLUGIN.MdFormatCommand(self.view).run(None, action='custom', custom_index=0)
        self.assertEqual(self.view.text, '<mark>hello</mark> world')
        for index in (-1, 5, True, '0'):
            view = View()
            PLUGIN.MdFormatCommand(view).run(None, action='custom', custom_index=index)
            self.assertEqual(view.text, 'hello world')

    def test_repeat_is_per_view_and_rechecks_profile(self):
        PLUGIN.MdFormatCommand(self.view).run(None, action='bold')
        PLUGIN.MdFormatRepeatCommand(self.view).run(None)
        self.assertEqual(self.view.text, 'hello world')
        other = View()
        self.assertFalse(PLUGIN.MdFormatRepeatCommand(other).is_enabled())

    def test_search_cancel_and_stale_document_are_non_destructive(self):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='search')
        done = self.view.win.show_quick_panel.call_args.args[1]
        done(-1)
        self.assertEqual(self.view.text, 'hello world')
        self.view.count += 1
        done(0)
        self.assertEqual(self.view.text, 'hello world')
        self.assertTrue(SUBLIME.status_message.called)

    def test_popup_ignores_untrusted_navigation(self):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='styled')
        navigate = self.view.show_popup.call_args.kwargs['on_navigate']
        for value in ('https://evil.invalid/', 'command:exec', 'custom:-1', 'action:unknown'):
            navigate(value)
        self.assertEqual(self.view.text, 'hello world')

    def test_closed_view_ignores_styled_settings_navigation(self):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='styled')
        navigate = self.view.show_popup.call_args.kwargs['on_navigate']
        self.view.valid = False

        navigate('settings')

        self.view.hide_popup.assert_not_called()
        self.view.win.run_command.assert_not_called()

    def test_label_override_in_native_menu(self):
        SUBLIME.load_settings.return_value = Settings(labels={'bold': 'Strong'})
        self.assertEqual(PLUGIN.MdFormatCommand(self.view).description(action='bold'), 'Strong')

    def test_profile_switch_is_view_local(self):
        PLUGIN.MdFormatProfileCommand(self.view).run(None)
        items, choose = self.view.win.show_quick_panel.call_args.args[:2]
        choose(items.index('CommonMark'))
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'commonmark')
        self.assertEqual(PLUGIN.settings_for(View())['profile'], 'gfm')
        self.assertEqual(SUBLIME.load_settings.return_value, {})

    def test_group_visibility_predicate_respects_critic_setting(self):
        command = PLUGIN.MdFormatMenuCommand(self.view)
        self.assertTrue(command.is_visible(group='Review'))
        self.view.config.set('markdown_formatting', {'enable_critic_markup': False})
        self.assertFalse(command.is_visible(group='Review'))
        self.assertTrue(command.is_visible(group='Headings'))
        self.view.config.set('markdown_formatting', {'enable_critic_markup': True})
        self.assertTrue(command.is_visible(group='Review'))
        self.assertFalse(command.is_visible(group='not-a-group'))

    def test_native_profile_label_includes_active_profile(self):
        self.view.config.set('markdown_formatting', {'profile': 'commonmark'})
        self.assertEqual(PLUGIN.MdFormatProfileCommand(self.view).description(),
                         'Markdown profile: CommonMark…')

    def test_group_visibility_predicate_respects_hidden_actions_and_custom_formats(self):
        self.view.config.set('markdown_formatting', {'hidden_actions': list(PLUGIN.ACTIONS)})
        menu = PLUGIN.MdFormatMenuCommand(self.view)
        for group in ('Headings', 'Lists', 'Insert', 'Review'):
            self.assertFalse(menu.is_visible(group=group))
        self.assertTrue(menu.is_visible())
        self.view.config.set('markdown_formatting', {
            'hidden_actions': list(PLUGIN.ACTIONS),
            'custom_formats': [{'label': 'Mark', 'prefix': '<mark>', 'suffix': '</mark>'}],
        })
        self.assertTrue(menu.is_visible(group='Insert'))

    def test_custom_picker_is_hidden_when_unconfigured(self):
        self.assertFalse(PLUGIN.MdFormatPickerCommand(self.view).is_visible(custom_only=True))

    def test_styled_picker_consumes_click_once(self):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='styled')
        navigate = self.view.show_popup.call_args.kwargs['on_navigate']
        navigate('action:bold')
        navigate('action:bold')
        self.assertEqual(self.view.text, '**hello** world')

    def test_picker_refuses_selection_changes(self):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='styled')
        navigate = self.view.show_popup.call_args.kwargs['on_navigate']
        self.view.regions = Selection([Region(6, 11)])
        navigate('action:bold')
        self.assertEqual(self.view.text, 'hello world')

    def test_settings_uses_actual_package_resource(self):
        PLUGIN.MdFormatSettingsCommand(self.view.win).run()
        name, args = self.view.win.run_command.call_args.args
        self.assertEqual(name, 'edit_settings')
        self.assertEqual(args['base_file'], '${packages}/MarkdownFormatting/MarkdownFormatting.sublime-settings')

    # The context-menu opt-out must hide leaves too, because Windows and
    # macOS show submenu headings regardless of their is_visible callbacks.
    def test_context_menu_opt_out_hides_every_context_leaf_but_settings(self):
        self.view.config.set('markdown_formatting', {
            'show_in_context_menu': False,
            'custom_formats': [{'label': 'Mark', 'prefix': '<mark>', 'suffix': '</mark>'}],
        })
        PLUGIN.MdFormatCommand(self.view).run(None, action='italic')
        self.assertFalse(PLUGIN.MdFormatCommand(self.view).is_visible(action='bold', context=True))
        self.assertFalse(PLUGIN.MdFormatCommand(self.view).is_enabled(action='bold', context=True))
        self.assertFalse(PLUGIN.MdFormatPickerCommand(self.view).is_visible(mode='search', context=True))
        self.assertFalse(PLUGIN.MdFormatPickerCommand(self.view).is_visible(custom_only=True, context=True))
        self.assertFalse(PLUGIN.MdFormatRepeatCommand(self.view).is_visible(context=True))
        self.assertFalse(PLUGIN.MdFormatRepeatCommand(self.view).is_enabled(context=True))
        self.assertFalse(PLUGIN.MdFormatProfileCommand(self.view).is_visible(context=True))
        # Palette, key bindings and the pickers pass no context argument.
        self.assertTrue(PLUGIN.MdFormatCommand(self.view).is_visible(action='bold'))
        self.assertTrue(PLUGIN.MdFormatPickerCommand(self.view).is_visible(mode='search'))
        self.assertTrue(PLUGIN.MdFormatPickerCommand(self.view).is_visible(custom_only=True))
        self.assertTrue(PLUGIN.MdFormatRepeatCommand(self.view).is_enabled())
        self.assertTrue(PLUGIN.MdFormatProfileCommand(self.view).is_visible())
        # Menu-only arguments are accepted everywhere Sublime passes them.
        self.assertEqual(PLUGIN.MdFormatCommand(self.view).description(action='bold', context=True), 'Bold')
        self.assertIn('profile', PLUGIN.MdFormatProfileCommand(self.view).description(context=True))
        self.view.config.set('markdown_formatting', {'show_in_context_menu': True})
        self.assertTrue(PLUGIN.MdFormatCommand(self.view).is_visible(action='bold', context=True))
        self.assertTrue(PLUGIN.MdFormatRepeatCommand(self.view).is_visible(context=True))
        self.assertTrue(PLUGIN.MdFormatProfileCommand(self.view).is_visible(context=True))
        self.assertTrue(PLUGIN.MdFormatPickerCommand(self.view).is_visible(mode='styled', context=True))

    def test_context_argument_is_accepted_by_run(self):
        PLUGIN.MdFormatCommand(self.view).run(None, action='bold', context=True)
        self.assertEqual(self.view.text, '**hello** world')
        PLUGIN.MdFormatRepeatCommand(self.view).run(None, context=True)
        self.assertEqual(self.view.text, 'hello world')
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='search', context=True)
        PLUGIN.MdFormatProfileCommand(self.view).run(None, context=True)
        self.assertEqual(self.view.win.show_quick_panel.call_count, 2)

    # The per-view profile choice is stored separately.
    def test_profile_choice_never_freezes_merged_project_settings_into_view(self):
        project = {'settings': {'markdown_formatting': {'hidden_actions': ['image']}}}
        self.view.win.project_data.return_value = project
        PLUGIN.MdFormatProfileCommand(self.view).run(None)
        items = self.view.win.show_quick_panel.call_args.args[0]
        choose = self.view.win.show_quick_panel.call_args.args[1]
        choose(items.index('MultiMarkdown'))
        self.assertNotIn('markdown_formatting', self.view.config)
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'multimarkdown')
        self.assertEqual(PLUGIN.settings_for(self.view)['hidden_actions'], ['image'])
        # Editing the project afterwards still takes effect in this view.
        project['settings']['markdown_formatting'] = {'hidden_actions': []}
        self.assertEqual(PLUGIN.settings_for(self.view)['hidden_actions'], [])
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'multimarkdown')

    def test_profile_choice_wins_over_view_dict_and_default_entry_clears_it(self):
        self.view.config.set('markdown_formatting', {'profile': 'commonmark', 'labels': {'bold': 'B'}})
        PLUGIN.MdFormatProfileCommand(self.view).run(None)
        args, kwargs = self.view.win.show_quick_panel.call_args
        items = args[0]
        self.assertEqual(items[kwargs['selected_index']], 'CommonMark (current)')
        args[1](items.index('MultiMarkdown'))
        self.assertEqual(self.view.config['markdown_formatting'],
                         {'profile': 'commonmark', 'labels': {'bold': 'B'}})
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'multimarkdown')
        self.assertEqual(PLUGIN.MdFormatProfileCommand(self.view).description(),
                         'Markdown profile: MultiMarkdown…')
        PLUGIN.MdFormatProfileCommand(self.view).run(None)
        args, kwargs = self.view.win.show_quick_panel.call_args
        self.assertEqual(args[0][kwargs['selected_index']], 'MultiMarkdown (current)')
        default = [index for index, item in enumerate(args[0]) if item.startswith('Default')]
        self.assertEqual(len(default), 1)
        args[1](default[0])
        self.assertNotIn(PLUGIN.PROFILE_KEY, self.view.config)
        self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'commonmark')
        args[1](-1)  # Cancelling changes nothing.
        self.assertNotIn(PLUGIN.PROFILE_KEY, self.view.config)

    def test_malformed_per_view_profile_choice_is_ignored(self):
        for value in (['gfm'], {'profile': 'commonmark'}, 'CommonMark', 3, None):
            self.view.config.set(PLUGIN.PROFILE_KEY, value)
            self.assertEqual(PLUGIN.settings_for(self.view)['profile'], 'gfm')
            self.assertEqual(PLUGIN.MdFormatProfileCommand(self.view).description(),
                             'Markdown profile: GitHub Flavored Markdown…')

    # S3: unexpected engine failures must not reach the console as tracebacks.
    def test_unexpected_engine_failure_leaves_buffer_untouched(self):
        for error in (RuntimeError('edit plan does not reconstruct formatted text'),
                      KeyError('secret document text')):
            SUBLIME.status_message.reset_mock()
            console = io.StringIO()
            failing = patch.object(PLUGIN, 'format_document', side_effect=error)
            with failing, contextlib.redirect_stdout(console):
                PLUGIN.MdFormatCommand(self.view).run(None, action='bold')
            self.assertNotIn('secret', console.getvalue())
            self.assertNotIn('hello', console.getvalue())
            self.assertEqual(self.view.text, 'hello world')
            self.assertEqual(self.view.replacements, [])
            message = SUBLIME.status_message.call_args.args[0]
            self.assertNotIn('secret', message)
            self.assertNotIn('hello', message)
            self.assertNotIn(PLUGIN.LAST_ACTION_KEY, self.view.config)

    # S1: Settings must work without an open file.
    def test_settings_command_is_a_window_command_without_frozen_defaults(self):
        self.assertTrue(issubclass(PLUGIN.MdFormatSettingsCommand, SUBLIME_PLUGIN.WindowCommand))
        self.assertFalse(issubclass(PLUGIN.MdFormatSettingsCommand, TextCommand))
        window = Mock()
        window.active_view.return_value = None
        PLUGIN.MdFormatSettingsCommand(window).run()
        name, args = window.run_command.call_args.args
        self.assertEqual(name, 'edit_settings')
        self.assertNotIn('profile', args['default'])
        body = ''.join(line for line in args['default'].splitlines()
                       if not line.strip().startswith('//'))
        self.assertNotIn(':', body)

    def test_styled_picker_settings_link_runs_window_command(self):
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='styled')
        navigate = self.view.show_popup.call_args.kwargs['on_navigate']
        navigate('settings')
        self.view.win.run_command.assert_called_once_with('md_format_settings')
        self.assertFalse(self.view.is_popup_visible())

    def test_repeat_resolves_settings_once_per_run(self):
        PLUGIN.MdFormatCommand(self.view).run(None, action='bold')
        self.view.run_command = Mock()
        with patch.object(PLUGIN, 'settings_for', wraps=PLUGIN.settings_for) as spy:
            PLUGIN.MdFormatRepeatCommand(self.view).run(None)
        self.assertEqual(spy.call_count, 1)
        self.view.run_command.assert_called_once_with('md_format', {'action': 'bold'})

    def test_profile_names_have_a_single_source(self):
        from MarkdownFormatting.mdformat import catalog, picker
        self.assertIs(getattr(PLUGIN, 'PROFILE_NAMES', catalog.PROFILE_NAMES), catalog.PROFILE_NAMES)
        self.assertFalse(hasattr(picker, '_PROFILE_LABELS'))
        self.assertEqual(tuple(catalog.PROFILE_NAMES), catalog.PROFILES)

    # Cleanup: an ignored legacy colour is not part of a template's identity.
    def test_repeat_survives_ignored_legacy_custom_color_edit(self):
        template = {'label': 'Mark', 'prefix': '<mark>', 'suffix': '</mark>', 'color': '#abc'}
        self.view.config.set('markdown_formatting', {'custom_formats': [template]})
        PLUGIN.MdFormatCommand(self.view).run(None, action='custom', custom_index=0)
        self.assertEqual(self.view.text, '<mark>hello</mark> world')
        self.view.config.set('markdown_formatting', {'custom_formats': [dict(template, color='#def')]})
        self.assertTrue(PLUGIN.MdFormatRepeatCommand(self.view).is_enabled())
        PLUGIN.MdFormatRepeatCommand(self.view).run(None)
        self.assertEqual(self.view.text, 'hello world')

    def test_picker_ignores_legacy_custom_color_edit(self):
        template = {'label': 'Mark', 'prefix': '<mark>', 'suffix': '</mark>', 'color': '#abc'}
        self.view.config.set('markdown_formatting', {'custom_formats': [template]})
        PLUGIN.MdFormatPickerCommand(self.view).run(None, mode='search')
        items, done = self.view.win.show_quick_panel.call_args.args[:2]
        self.view.config.set('markdown_formatting', {'custom_formats': [dict(template, color='#def')]})
        done(items.index('Mark'))
        self.assertEqual(self.view.text, '<mark>hello</mark> world')
