import re
import unittest
from html import escape
from html.parser import HTMLParser

from mdformat.catalog import ACTIONS, available_actions, resolve_settings
from mdformat.picker import render_picker


HREF_RE = re.compile(r'href="([^"]*)"')


class Rows(HTMLParser):
    def __init__(self, rendered):
        super().__init__(convert_charrefs=True)
        self.rows = {}
        self.target = None
        self.feed(rendered)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.target = dict(attrs).get('href')
            self.rows[self.target] = ''
        elif tag == 'br' and self.target is not None:
            self.rows[self.target] += '\n'

    def handle_endtag(self, tag):
        if tag == 'a':
            self.target = None

    def handle_data(self, data):
        if self.target is not None:
            self.rows[self.target] += data


class PickerRendererTests(unittest.TestCase):
    def test_every_builtin_is_one_example_using_its_label(self):
        expected = {
            'heading_1': '# Heading 1',
            'heading_2': '## Heading 2',
            'heading_3': '### Heading 3',
            'heading_4': '#### Heading 4',
            'heading_5': '##### Heading 5',
            'heading_6': '###### Heading 6',
            'bold': '**Bold**',
            'italic': '*Italic*',
            'bold_italic': '***Bold + Italic***',
            'strikethrough': '~~Strikethrough~~',
            'inline_code': '`Inline Code`',
            'fenced_code': '```\nFenced Code Block\n```',
            'link': '[Link](https://example.com)',
            'image': '![Image](https://example.com)',
            'blockquote': '> Blockquote',
            'unordered_list': '- Unordered List',
            'ordered_list': '1. Ordered List',
            'task_list': '- [ ] Task List',
            'toggle_task': '- [x] Toggle Task',
            'horizontal_rule': 'Horizontal Rule\n\n---',
            'table': '| Table |\n| ----- |',
            'html_comment': '<!-- HTML Comment -->',
            'insertion': '<ins>Insertion</ins>',
            'footnote': '[^note]\n\n[^note]: Footnote',
            'critic_addition': '{++Critic Addition++}',
            'critic_deletion': '{--Critic Deletion--}',
            'critic_substitution': '{~~Critic Substitution~>new~~}',
            'critic_highlight': '{==Critic Highlight==}',
            'critic_comment': '{>>Critic Comment<<}',
        }
        self.assertEqual(set(expected), set(ACTIONS))
        seen = set()
        for profile in ('gfm', 'commonmark', 'multimarkdown'):
            settings = {'profile': profile}
            rendered = render_picker(settings)
            rows = Rows(rendered).rows
            self.assertNotIn('class="label"', rendered)
            self.assertNotIn('class="hint"', rendered)
            for action in available_actions(settings):
                with self.subTest(profile=profile, action=action):
                    self.assertEqual(rows['action:' + action], expected[action])
                    seen.add(action)
        self.assertEqual(seen, set(ACTIONS))

    def test_filtering_order_and_groups_remain_unchanged(self):
        settings = resolve_settings({
            'profile': 'gfm', 'hidden_actions': ['bold'],
            'picker_order': ['table', 'italic', 'heading_2'],
        })
        rendered = render_picker(settings)
        action_hrefs = [h for h in HREF_RE.findall(rendered) if h.startswith('action:')]
        self.assertEqual(action_hrefs, ['action:' + a for a in available_actions(settings)])
        self.assertEqual(action_hrefs[:3], ['action:table', 'action:italic', 'action:heading_2'])
        self.assertNotIn('action:bold', action_hrefs)
        self.assertIn('Headings', rendered)
        self.assertIn('Profile: GitHub Flavored Markdown', rendered)

    def test_examples_follow_configured_labels_and_marker_preferences(self):
        rows = Rows(render_picker({
            'labels': {'heading_1': 'Title', 'bold': 'Strong', 'link': 'Website'},
            'strong_marker': '__', 'emphasis_marker': '_', 'bullet_marker': '+',
            'fence_language': 'python', 'link_url': '/docs',
        })).rows
        self.assertEqual(rows['action:heading_1'], '# Title')
        self.assertEqual(rows['action:bold'], '__Strong__')
        self.assertEqual(rows['action:italic'], '_Italic_')
        self.assertEqual(rows['action:bold_italic'], '___Bold + Italic___')
        self.assertEqual(rows['action:unordered_list'], '+ Unordered List')
        self.assertEqual(rows['action:fenced_code'], '```python\nFenced Code Block\n```')
        self.assertEqual(rows['action:link'], '[Website](/docs)')

    def test_markup_in_labels_is_example_content_not_a_toggle_request(self):
        rows = Rows(render_picker({'labels': {
            'bold': '**Already bold**', 'heading_1': '# Caption',
            'inline_code': '`ticks`', 'link': '[Caption](url)',
        }})).rows
        self.assertEqual(rows['action:bold'], '****Already bold****')
        self.assertEqual(rows['action:heading_1'], '# # Caption')
        self.assertEqual(rows['action:inline_code'], '`` `ticks` ``')
        self.assertEqual(rows['action:link'], '[\\[Caption\\](url)](https://example.com)')

    def test_preview_guard_cannot_remove_user_content(self):
        caption = 'MDFORMATPREVIEWGUARD and MDFORMATPREVIEWGUARDx'
        rows = Rows(render_picker({'labels': {'bold': caption}, 'link_url': caption})).rows
        self.assertEqual(rows['action:bold'], '**' + caption + '**')
        self.assertIn(caption.replace(' ', '%20'), rows['action:link'])

    def test_highlighter_receives_complete_examples_not_separate_captions(self):
        seen = []

        def highlight(text):
            seen.append(text)
            return '<span style="color: #123456">' + escape(text) + '</span>'

        rendered = render_picker({'hidden_actions': ['image']}, highlight=highlight)
        self.assertIn('# Heading 1', seen)
        self.assertIn('**Bold**', seen)
        self.assertNotIn('Heading 1', seen)
        self.assertNotIn('# text', seen)
        self.assertEqual(len(seen), len(available_actions({'hidden_actions': ['image']})))
        self.assertIn('<span style="color: #123456"># Heading 1</span>', rendered)
        self.assertEqual(Rows(rendered).rows['action:heading_1'], '# Heading 1')

    def test_legacy_manual_styles_do_not_override_theme_highlighting(self):
        def highlight(text):
            return '<span style="color: #123456">' + escape(text) + '</span>'

        settings = {'styles': {'bold': {'color': '#aBc', 'bold': True},
                               'italic': {'italic': True}}}
        self.assertEqual(render_picker(settings, highlight=highlight),
                         render_picker({}, highlight=highlight))
        self.assertEqual(render_picker(settings), render_picker({}))

    def test_custom_examples_use_label_not_insertion_placeholder_or_manual_color(self):
        settings = {'custom_formats': [{
            'label': 'Keyboard', 'prefix': '<kbd>', 'suffix': '</kbd>',
            'placeholder': 'key', 'color': '#0fA',
        }]}
        rendered = render_picker(settings, custom_only=True)
        self.assertEqual(Rows(rendered).rows['custom:0'], '<kbd>Keyboard</kbd>')
        self.assertNotIn('#0fA', rendered)
        self.assertEqual(settings['custom_formats'][0]['placeholder'], 'key')
        self.assertEqual(HREF_RE.findall(rendered), ['custom:0', 'settings'])

    def test_labels_and_custom_wrappers_are_escaped_and_never_navigation(self):
        caption = '<img src=x onerror="boom"> & Bold'
        rendered = render_picker({
            'labels': {'bold': caption},
            'custom_formats': [{
                'label': '<script>alert("label")</script>',
                'prefix': '<mark data-x="prefix">', 'suffix': '</mark>&suffix',
            }],
        })
        self.assertNotIn('<img', rendered.lower())
        self.assertNotIn('<script', rendered.lower())
        self.assertEqual(Rows(rendered).rows['action:bold'], '**' + caption + '**')
        self.assertIn('&lt;script&gt;', rendered)
        for href in HREF_RE.findall(rendered):
            self.assertRegex(href, r'^(?:action:[a-z0-9_]+|custom:[0-9]+|settings)$')

    def test_empty_custom_only_picker_keeps_settings_access(self):
        # The adapter never opens an empty chooser; the renderer stays safe anyway.
        rendered = render_picker({}, custom_only=True)
        self.assertEqual(HREF_RE.findall(rendered), ['settings'])

    def test_failed_highlighter_is_not_misrepresented_as_highlighting(self):
        def fail(text):
            raise RuntimeError('export unavailable')

        with self.assertRaisesRegex(RuntimeError, 'export unavailable'):
            render_picker({}, highlight=fail)
        with self.assertRaises(ValueError):
            render_picker({}, highlight=lambda text: '')
        with self.assertRaises(ValueError):
            render_picker({}, highlight=lambda text: None)


if __name__ == '__main__':
    unittest.main()
