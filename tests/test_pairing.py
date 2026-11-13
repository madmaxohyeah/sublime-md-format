"""Regressions for proven sibling pairing, not full Markdown parsing."""
import unittest

from mdformat.engine import format_document


class SiblingPairingTests(unittest.TestCase):
    def test_plain_text_between_sibling_spans_never_consumes_the_siblings(self):
        cases = [
            ('italic', '*', '*', None),
            ('bold', '**', '**', None),
            ('bold_italic', '***', '***', None),
            ('strikethrough', '~~', '~~', None),
            ('inline_code', '`', '`', None),
            ('custom', '<mark>', '</mark>', {'prefix': '<mark>', 'suffix': '</mark>'}),
            ('html_comment', '<!-- ', ' -->', None),
            ('insertion', '<ins>', '</ins>', None),
        ]
        for action, prefix, suffix, options in cases:
            with self.subTest(action=action):
                left = prefix + 'one' + suffix + ' '
                right = ' ' + prefix + 'two' + suffix
                original = left + 'middle' + right
                start, end = len(left), len(left) + len('middle')
                first = format_document(original, [(start, end)], action, options)
                self.assertEqual(first.text, left + prefix + 'middle' + suffix + right)
                self.assertEqual(first.edits[0].start, start)
                self.assertEqual(first.edits[0].end, end)
                selected = first.text[slice(*first.selections[0])]
                self.assertEqual(selected, 'middle')
                repeated = format_document(first.text, list(first.selections), action, options)
                self.assertEqual(repeated.text, original)

    def test_overlapping_custom_tokens_repeat_and_preserve_nested_siblings(self):
        for prefix, suffix in (('ab', 'a'), ('<<', '<'), ('xyx', 'x'),
                               ('a', 'ab'), ('<', '<<'), ('abab', 'ab'), ('aaa', 'aa')):
            with self.subTest(prefix=prefix, suffix=suffix):
                options = {'prefix': prefix, 'suffix': suffix}
                first = format_document('middle', [(0, 6)], 'custom', options)
                self.assertEqual(first.text, prefix + 'middle' + suffix)
                repeated = format_document(first.text, list(first.selections), 'custom', options)
                self.assertEqual(repeated.text, 'middle')
                whole = format_document(first.text, [(0, len(first.text))], 'custom', options)
                self.assertEqual(whole.text, 'middle')
                nested = prefix + first.text + suffix
                start = len(prefix) * 2
                unwrapped = format_document(nested, [(start, start + 6)], 'custom', options)
                self.assertEqual(unwrapped.text, first.text)
                spaced = prefix + 'one ' + prefix + 'two ' + first.text + ' two' + suffix + ' one' + suffix
                start = spaced.index('middle')
                unwrapped = format_document(spaced, [(start, start + 6)], 'custom', options)
                expected = prefix + 'one ' + prefix + 'two middle two' + suffix + ' one' + suffix
                self.assertEqual(unwrapped.text, expected)
                adjacent = prefix + 'one' + suffix + prefix + 'middle' + suffix
                start = adjacent.index('middle')
                unwrapped = format_document(adjacent, [(start, start + 6)], 'custom', options)
                self.assertEqual(unwrapped.text, prefix + 'one' + suffix + 'middle')
                left, right = prefix + 'one' + suffix + ' ', ' ' + prefix + 'two' + suffix
                text = left + 'middle' + right
                result = format_document(text, [(len(left), len(left) + 6)], 'custom', options)
                self.assertEqual(result.text, left + first.text + right)
                self.assertEqual(result.edits[0].start, len(left))
                self.assertEqual(result.edits[0].end, len(left) + 6)

    def test_overlapping_literal_templates_preserve_whitespace(self):
        for prefix, suffix in (('<<', '<'), ('<', '<<'), ('abab', 'ab'), ('aaa', 'aa')):
            for content in (' middle ', 'first\n\nsecond', '  '):
                with self.subTest(prefix=prefix, suffix=suffix, content=content):
                    options = {'prefix': prefix, 'suffix': suffix}
                    text = 'before ' + content + ' after'
                    selection = (len('before '), len('before ') + len(content))
                    first = format_document(text, [selection], 'custom', options)
                    repeated = format_document(first.text, list(first.selections), 'custom', options)
                    self.assertEqual(repeated.text, text)

    def test_code_spans_with_different_lengths_do_not_reuse_closers(self):
        text = '`one` middle ``two`three``'
        start = text.index('middle')
        result = format_document(text, [(start, start + 6)], 'inline_code')
        self.assertEqual(result.text, '`one` `middle` ``two`three``')

    def test_fenced_blocks_are_paired_from_document_start(self):
        for fence in ('```', '~~~~'):
            with self.subTest(fence=fence):
                left = 'before\n' + fence + '\none\n' + fence + '\n'
                right = '\n' + fence + '\ntwo\n' + fence + '\nafter'
                text = left + 'middle' + right
                start = len(left)
                result = format_document(text, [(start, start + 6)], 'fenced_code')
                self.assertEqual(result.text, left + '```\nmiddle\n```' + right)
                self.assertEqual(result.edits[0].start, start)
                self.assertEqual(result.edits[0].end, start + 6)
                self.assertEqual(result.text[slice(*result.selections[0])], 'middle')
                repeated = format_document(result.text, list(result.selections), 'fenced_code')
                self.assertEqual(repeated.text, text)

    def test_nested_literal_wrapper_only_unwraps_one_proven_container(self):
        text = '<mark>one <mark>two</mark> three</mark>'
        start = text.index('two')
        result = format_document(text, [(start, start + 3)], 'custom',
                                 {'prefix': '<mark>', 'suffix': '</mark>'})
        self.assertEqual(result.text, '<mark>one two three</mark>')
