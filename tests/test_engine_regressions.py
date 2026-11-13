"""Regression tests for formatting engine edge cases."""
from __future__ import annotations

import time
import unittest

from mdformat.engine import format_document

from test_engine import EngineTestCase


def selected(result, index=0):
    return result.text[slice(*sorted(result.selections[index]))]


class LinkDetectionRegressions(EngineTestCase):
    def test_stray_bracket_before_link_does_not_swallow_text(self) -> None:
        text = "Use [ brackets\n\nsee [link](https://x.org) now"
        result = self.apply(text, [(21, 25)], "link")
        self.assertEqual(result.text, "Use [ brackets\n\nsee link now")
        self.assertEqual(selected(result), "link")

    def test_stray_bracket_on_same_line_unlinks_innermost(self) -> None:
        for text, expected in (
            ("a [b [c](u) d", "a [b c d"),
            ("a ![b [c](u) d", "a ![b c d"),
        ):
            with self.subTest(text=text):
                start = text.index("c")
                result = self.apply(text, [(start, start + 1)], "link")
                self.assertEqual(result.text, expected)

    def test_balanced_brackets_in_link_text_still_unlink(self) -> None:
        text = "see [a [b] c](u) now"
        start = text.index("c]")
        result = self.apply(text, [(start, start + 1)], "link")
        self.assertEqual(result.text, "see a [b] c now")

    def test_selection_in_destination_unlinks_instead_of_nesting(self) -> None:
        result = self.apply("[x](u)", [(4, 5)], "link")
        self.assertEqual(result.text, "x")

    def test_image_is_not_unlinked_by_link_action(self) -> None:
        text = "![a](u)"
        result = self.apply(text, [(2, 3)], "image")
        self.assertEqual(result.text, "a")
        result = self.apply(text, [(5, 6)], "image")
        self.assertEqual(result.text, "a")

    def test_link_after_bang_escapes_it_and_toggles_back(self) -> None:
        first = self.apply("Wow!great", [(4, 9)], "link")
        self.assertEqual(first.text, "Wow\\![great](https://example.com)")
        self.assertEqual(selected(first), "great")
        second = self.apply(first.text, list(first.selections), "link")
        self.assertEqual(second.text, "Wow\\!great")

    def test_bang_inside_a_previous_selection_is_not_escaped(self) -> None:
        result = self.apply("Wow!great", [(0, 4), (4, 9)], "link")
        self.assertEqual(
            result.text, "[Wow!](https://example.com)[great](https://example.com)"
        )


class EmphasisPairingRegressions(EngineTestCase):
    def test_italic_on_bold_text_adds_emphasis(self) -> None:
        for text, options, expected in (
            ("**hello**", None, "***hello***"),
            ("__hello__", {"emphasis_marker": "_", "strong_marker": "__"}, "___hello___"),
        ):
            for selection in ((2, 7), (4, 4)):
                with self.subTest(text=text, selection=selection):
                    first = self.apply(text, [selection], "italic", options)
                    self.assertEqual(first.text, expected)
                    # A caret word includes underscores (they are word characters).
                    self.assertEqual(selected(first).strip("_"), "hello")
                    second = self.apply(first.text, list(first.selections), "italic", options)
                    self.assertEqual(second.text, text)

    def test_bold_italic_text_still_loses_one_marker(self) -> None:
        self.assertEqual(self.apply("***hello***", [(3, 8)], "italic").text, "**hello**")
        self.assertEqual(self.apply("***hello***", [(3, 8)], "bold").text, "*hello*")

    def test_italic_inside_nested_strong_toggles_outer_emphasis(self) -> None:
        text = "*a **b** c*"
        self.assertEqual(self.apply(text, [(1, 1), (5, 5)], "italic").text, "a **b** c")
        self.assertEqual(self.apply(text, [(5, 6)], "italic").text, "a **b** c")

    def test_single_crlf_is_not_a_paragraph_break(self) -> None:
        result = self.apply("**a\r\nb**", [(2, 6)], "bold")
        self.assertEqual(result.text, "a\r\nb")

    def test_caret_on_marker_runs_unwraps(self) -> None:
        for caret in (0, 1, 8, 9):
            with self.subTest(caret=caret):
                result = self.apply("**hello**", [(caret, caret)], "bold")
                self.assertEqual(result.text, "hello")
        result = self.apply("x <ins>hello</ins>.", [(18, 18)], "insertion")
        self.assertEqual(result.text, "x hello.")

    def test_symmetric_templates_pair_nearest_flanking_markers(self) -> None:
        cases = (
            ("if a == b then ==hi== ok", "hi", "==", "if a == b then hi ok"),
            ("50% off, %note%", "note", "%", "50% off, note"),
        )
        for text, word, marker, expected in cases:
            with self.subTest(text=text):
                options = {"prefix": marker, "suffix": marker}
                start = text.index(word)
                result = self.apply(text, [(start, start + len(word))], "custom", options)
                self.assertEqual(result.text, expected)

    def test_symmetric_template_with_whitespace_content_round_trips(self) -> None:
        options = {"prefix": "==", "suffix": "=="}
        text = "a  mid  b"
        first = self.apply(text, [(1, 8)], "custom", options)
        self.assertEqual(first.text, "a==  mid  ==b")
        second = self.apply(first.text, list(first.selections), "custom", options)
        self.assertEqual(second.text, text)

    def test_intraword_underscores_are_not_emphasis(self) -> None:
        result = self.apply("x_y_z", [(2, 3)], "italic", {"emphasis_marker": "_"})
        self.assertNotEqual(result.text, "xyz")
        self.assertIn("x_", result.text)
        self.assertEqual(selected(result), "y")

    def test_intraword_underscore_marker_falls_back_to_asterisks(self) -> None:
        options = {"emphasis_marker": "_", "strong_marker": "__"}
        for action, wrapped in [("italic", "x_*y*_z"), ("bold", "x_**y**_z")]:
            with self.subTest(action=action):
                result = self.apply("x_y_z", [(2, 3)], action, options)
                self.assertEqual(result.text, wrapped)
                self.assertEqual(selected(result), "y")
                back = self.apply(result.text, list(result.selections), action, options)
                self.assertEqual(back.text, "x_y_z")
        self.assertEqual(self.apply("say hi", [(4, 6)], "italic", options).text, "say _hi_")


class UnwrapSelectionRegressions(EngineTestCase):
    def test_unwrap_keeps_the_content_selected(self) -> None:
        options = {"prefix": "<mark>", "suffix": "</mark>"}
        result = self.apply("<mark>a</mark>", [(6, 7)], "custom", options)
        self.assertEqual((result.text, result.selections), ("a", ((0, 1),)))

        result = self.apply("`` ` ``", [(3, 4)], "inline_code")
        self.assertEqual((result.text, result.selections), ("`", ((0, 1),)))


class InlineCodeRegressions(EngineTestCase):
    def test_adjacent_selections_become_one_code_span(self) -> None:
        first = self.apply("ab", [(0, 1), (1, 2)], "inline_code")
        self.assertEqual(first.text, "`ab`")
        second = self.apply(first.text, list(first.selections), "inline_code")
        self.assertEqual(second.text, "ab")

    def test_caret_touching_code_span_unwraps(self) -> None:
        self.assertEqual(self.apply("`hello` x", [(0, 0)], "inline_code").text, "hello x")

    def test_escaped_backtick_does_not_open_a_code_span(self) -> None:
        result = self.apply("\\`x` y", [(3, 3)], "inline_code")
        self.assertTrue(result.text.startswith("\\`"))
        self.assertIn("x", result.text)
        self.assertEqual(selected(result), "x")

    def test_backslash_inside_code_span_is_literal(self) -> None:
        result = self.apply("`a\\` b", [(1, 1)], "inline_code")
        self.assertEqual(result.text, "a\\ b")


class MultiLineInlineRegressions(EngineTestCase):
    def test_wrapper_across_blank_line_applies_per_paragraph_and_toggles(self) -> None:
        for action, marker in (("bold", "**"), ("italic", "*"), ("strikethrough", "~~")):
            with self.subTest(action=action):
                text = "one\n\ntwo"
                first = self.apply(text, [(0, 8)], action)
                self.assertEqual(first.text, marker + "one" + marker + "\n\n" + marker + "two" + marker)
                self.assertEqual(len(first.edits), 1)
                second = self.apply(first.text, list(first.selections), action)
                self.assertEqual(second.text, text)
                self.assertEqual(second.selections, ((0, 8),))

    def test_wrapper_across_list_items_wraps_item_content(self) -> None:
        first = self.apply("- a\n- b", [(2, 7)], "bold")
        self.assertEqual(first.text, "- **a**\n- **b**")
        second = self.apply(first.text, list(first.selections), "bold")
        self.assertEqual(second.text, "- a\n- b")

    def test_block_prefixes_stay_outside_wrappers(self) -> None:
        text = "# Title\n> quoted\n- [ ] task\n1. item"
        result = self.apply(text, [(0, len(text))], "inline_code")
        self.assertEqual(result.text, "# `Title`\n> `quoted`\n- [ ] `task`\n1. `item`")
        repeated = self.apply(result.text, [(0, len(result.text))], "inline_code")
        self.assertEqual(repeated.text, text)

    def test_mixed_lines_only_wrap_unwrapped_lines(self) -> None:
        result = self.apply("- **a**\n- b", [(0, 11)], "bold")
        self.assertEqual(result.text, "- **a**\n- **b**")

    def test_single_paragraph_soft_wrap_keeps_one_wrapper(self) -> None:
        self.assertEqual(self.apply("one\ntwo", [(0, 7)], "bold").text, "**one\ntwo**")

    def test_custom_and_critic_templates_split_per_line(self) -> None:
        result = self.apply("one\n\ntwo", [(0, 8)], "critic_highlight")
        self.assertEqual(result.text, "{==one==}\n\n{==two==}")
        options = {"prefix": "<mark>", "suffix": "</mark>"}
        result = self.apply("- a\n- b", [(0, 7)], "custom", options)
        self.assertEqual(result.text, "- <mark>a</mark>\n- <mark>b</mark>")

    def test_html_comment_and_multiline_templates_stay_whole(self) -> None:
        self.assertEqual(
            self.apply("one\n\ntwo", [(0, 8)], "html_comment").text, "<!-- one\n\ntwo -->"
        )
        options = {"prefix": ":::note\n", "suffix": "\n:::"}
        self.assertEqual(
            self.apply("one\n\ntwo", [(0, 8)], "custom", options).text, ":::note\none\n\ntwo\n:::"
        )


class BlockRegressions(EngineTestCase):
    def test_blank_lines_in_selection_do_not_block_toggle_off(self) -> None:
        cases = (
            ("- a\n\n- b", "unordered_list"),
            ("1. a\n\n2. b", "ordered_list"),
            ("# a\n\n# b", "heading_1"),
            ("> a\n\n> b", "blockquote"),
        )
        for text, action in cases:
            with self.subTest(action=action):
                result = self.apply(text, [(0, len(text))], action)
                self.assertEqual(result.text, "a\n\nb")

    def test_blank_lines_stay_blank_when_adding(self) -> None:
        cases = (
            ("unordered_list", "- a\n\n- b"),
            ("ordered_list", "1. a\n\n2. b"),
            ("heading_1", "# a\n\n# b"),
            ("task_list", "- [ ] a\n\n- [ ] b"),
        )
        for action, expected in cases:
            with self.subTest(action=action):
                self.assertEqual(self.apply("a\n\nb", [(0, 4)], action).text, expected)

    def test_blank_only_selection_keeps_placeholder(self) -> None:
        result = self.apply("\n\n", [(0, 2)], "heading_2")
        self.assertEqual(result.text, "## Heading\n## Heading\n")

    def test_ordered_list_numbers_each_indentation_level(self) -> None:
        text = "- a\n  - b\n  - c\n- d"
        result = self.apply(text, [(0, len(text))], "ordered_list")
        self.assertEqual(result.text, "1. a\n  1. b\n  2. c\n2. d")

    def test_block_actions_keep_blockquote_prefix(self) -> None:
        self.assertEqual(self.apply("> - [ ] a", [(9, 9)], "toggle_task").text, "> - [x] a")
        self.assertEqual(self.apply("> a\n> b", [(0, 7)], "unordered_list").text, "> - a\n> - b")
        self.assertEqual(self.apply("> - a\n> - b", [(0, 11)], "unordered_list").text, "> a\n> b")
        self.assertEqual(self.apply("> a", [(0, 3)], "heading_1").text, "> # a")
        self.assertEqual(self.apply("> # a", [(0, 5)], "heading_1").text, "> a")
        self.assertEqual(self.apply("> > a", [(5, 5)], "ordered_list").text, "> > 1. a")

    def test_caret_in_empty_quote_line_gets_list_placeholder(self) -> None:
        result = self.apply("> ", [(2, 2)], "unordered_list")
        self.assertEqual((result.text, result.selections), ("> - ", ((4, 4),)))

    def test_existing_pipe_table_is_realigned(self) -> None:
        text = "| a | b |\n|---|:-:|\n| long cell | x\\|y |"
        expected = (
            "| a         |  b   |\n"
            "| --------- | :--: |\n"
            "| long cell | x\\|y |"
        )
        result = self.apply(text, [(0, len(text))], "table")
        self.assertEqual(result.text, expected)
        self.assertEqual(self.apply(expected, [(0, len(expected))], "table").text, expected)

    def test_caret_inside_table_realigns_whole_table(self) -> None:
        text = "intro\n\n|a|b|\n|:-|-:|\n|1|22|\n\nafter"
        caret = text.index("22")
        result = self.apply(text, [(caret, caret)], "table")
        self.assertEqual(
            result.text,
            "intro\n\n| a   |   b |\n| :-- | --: |\n| 1   |  22 |\n\nafter",
        )
        self.assertEqual(result.text[result.selections[0][0] :][:2], "22")

    def test_fenced_code_in_list_item_keeps_indentation(self) -> None:
        text = "- item\n  code"
        first = self.apply(text, [(9, 13)], "fenced_code")
        self.assertEqual(first.text, "- item\n  ```\n  code\n  ```")
        self.assertEqual(selected(first), "code")
        second = self.apply(first.text, list(first.selections), "fenced_code")
        self.assertEqual(second.text, text)

    def test_large_block_selection_maps_carets_exactly(self) -> None:
        text = "\n".join("- item {0:02d}".format(index) for index in range(60))
        caret = text.index("item 55") + 3
        result = self.apply(text, [(0, len(text)), (caret, caret)], "ordered_list")
        position = result.selections[1][0]
        self.assertEqual(result.text[position - 3 : position + 4], "item 55")

        text = "\n".join("word{0}".format(index) for index in range(300))
        caret = text.index("word200") + 4
        for action in ("unordered_list", "blockquote", "heading_2"):
            with self.subTest(action=action):
                result = self.apply(text, [(0, len(text)), (caret, caret)], action)
                position = result.selections[1][0]
                self.assertEqual(result.text[position - 4 : position + 3], "word200")

    def test_footnote_labels_compare_case_insensitively(self) -> None:
        text = "Ref.\n\n[^Note]: existing"
        result = self.apply(text, [(4, 4)], "footnote", {"select_word_on_empty": False})
        self.assertIn("[^note2]: Footnote text", result.text)
        self.assertNotIn("[^note]", result.text)


class ManyCaretPerformanceRegressions(EngineTestCase):
    def test_caret_on_every_line_is_not_quadratic(self) -> None:
        count = 2000
        text = "\n".join("line {0} with some words".format(index) for index in range(count))
        line_starts = [0]
        for index, character in enumerate(text):
            if character == "\n":
                line_starts.append(index + 1)
        carets = [(start + 2, start + 2) for start in line_starts]
        # Generous bound so slow CI runners pass; quadratic mapping took 10s+.
        for action in ("unordered_list", "ordered_list", "blockquote", "bold", "link", "inline_code"):
            with self.subTest(action=action):
                started = time.perf_counter()
                result = format_document(text, carets, action)
                elapsed = time.perf_counter() - started
                self.assert_invariants(text, result)
                self.assertEqual(len(result.selections), count)
                self.assertLess(elapsed, 2.0, "{0} took {1:.2f}s".format(action, elapsed))

    def test_every_line_carets_map_to_the_same_word(self) -> None:
        text = "\n".join("item{0}".format(index) for index in range(500))
        carets = []
        start = 0
        for line in text.split("\n"):
            carets.append((start + 2, start + 2))
            start += len(line) + 1
        result = self.apply(text, carets, "unordered_list")
        for position, _ in result.selections:
            self.assertEqual(result.text[position - 4 : position], "- it")


if __name__ == "__main__":
    unittest.main()
