from __future__ import annotations

import unittest
import time

from mdformat.engine import FormatResult, Replacement, format_document


class EngineTestCase(unittest.TestCase):
    def assert_invariants(self, original: str, result: FormatResult) -> None:
        self.assertIsInstance(result, FormatResult)
        self.assertIsInstance(result.selections, tuple)
        self.assertIsInstance(result.edits, tuple)

        previous_end = 0
        rebuilt = original
        for index, edit in enumerate(result.edits):
            self.assertIsInstance(edit, Replacement)
            self.assertGreaterEqual(edit.start, 0)
            self.assertGreaterEqual(edit.end, edit.start)
            self.assertLessEqual(edit.end, len(original))
            if index:
                self.assertGreaterEqual(edit.start, previous_end)
            previous_end = edit.end

        for edit in reversed(result.edits):
            rebuilt = rebuilt[: edit.start] + edit.text + rebuilt[edit.end :]
        self.assertEqual(result.text, rebuilt)

        for a, b in result.selections:
            self.assertGreaterEqual(a, 0)
            self.assertGreaterEqual(b, 0)
            self.assertLessEqual(a, len(result.text))
            self.assertLessEqual(b, len(result.text))

    def apply(self, text: str, selections, action: str, options=None) -> FormatResult:
        result = format_document(text, selections, action, options)
        self.assert_invariants(text, result)
        self.assertEqual(len(selections), len(result.selections))
        return result


class InlineFormattingTests(EngineTestCase):
    def test_bold_wraps_selected_text_and_returns_bounded_edit(self) -> None:
        result = self.apply("hello", [(0, 5)], "bold")

        self.assertEqual(result.text, "**hello**")
        self.assertEqual(result.selections, ((2, 7),))
        self.assertEqual(result.edits, (Replacement(0, 5, "**hello**"),))

    def test_multiple_unicode_and_reversed_selections_preserve_direction(self) -> None:
        result = self.apply("café tea", [(0, 4), (8, 5)], "bold")

        self.assertEqual(result.text, "**café** **tea**")
        self.assertEqual(result.selections, ((2, 6), (14, 11)))
        self.assertEqual(len(result.edits), 2)

    def test_empty_caret_selects_unicode_word_and_repeat_unwraps_it(self) -> None:
        text = "say café now"
        first = self.apply(text, [(6, 6)], "bold")

        self.assertEqual(first.text, "say **café** now")
        self.assertEqual(first.selections, ((6, 10),))

        second = self.apply(first.text, list(first.selections), "bold")
        self.assertEqual(second.text, text)
        self.assertEqual(second.selections, ((4, 8),))

    def test_empty_caret_uses_selected_placeholder_when_word_selection_disabled(self) -> None:
        result = self.apply("", [(0, 0)], "bold", {"select_word_on_empty": False})

        self.assertEqual(result.text, "**text**")
        self.assertEqual(result.selections, ((2, 6),))

    def test_selected_markup_toggles_off(self) -> None:
        result = self.apply("before **bold** after", [(7, 15)], "bold")

        self.assertEqual(result.text, "before bold after")
        self.assertEqual(result.selections, ((7, 11),))

    def test_common_emphasis_keeps_selected_boundary_whitespace_outside_markers(self) -> None:
        cases = {
            "italic": "*",
            "bold": "**",
            "bold_italic": "***",
            "strikethrough": "~~",
        }

        for action, marker in cases.items():
            with self.subTest(action=action):
                first = self.apply(" hello ", [(0, 7)], action)
                self.assertEqual(first.text, " " + marker + "hello" + marker + " ")
                self.assertEqual(first.text[slice(*first.selections[0])], "hello")

                second = self.apply(first.text, list(first.selections), action)
                self.assertEqual(second.text, " hello ")
                self.assertEqual(second.selections, ((1, 6),))

    def test_common_emphasis_is_a_noop_for_all_whitespace_selection(self) -> None:
        for action in ("italic", "bold", "bold_italic", "strikethrough"):
            with self.subTest(action=action):
                result = self.apply("before   after", [(6, 9)], action)
                self.assertEqual(result.text, "before   after")
                self.assertEqual(result.selections, ((6, 9),))
                self.assertEqual(result.edits, ())

    def test_trailing_whitespace_inside_strong_markers_is_not_toggled_as_valid_markup(self) -> None:
        text = "**hello **"
        result = self.apply(text, [(0, len(text))], "bold")

        self.assertEqual(result.text, "**" + text + "**")
        self.assertNotEqual(result.text, "hello ")

    def test_partial_selection_inside_matching_delimiters_toggles_whole_wrapper(self) -> None:
        text = "**some bold text**"
        start = text.index("bold")
        result = self.apply(text, [(start, start + 4)], "bold")

        self.assertEqual(result.text, "some bold text")
        self.assertEqual(result.selections, ((5, 9),))
        self.assertEqual(result.edits, (Replacement(0, len(text), "some bold text"),))

    def test_duplicate_inline_selections_share_one_edit(self) -> None:
        result = self.apply("word", [(0, 4), (0, 4)], "italic")

        self.assertEqual(result.text, "*word*")
        self.assertEqual(result.selections, ((1, 5), (1, 5)))
        self.assertEqual(len(result.edits), 1)

    def test_multiple_selections_touching_one_existing_wrapper_deduplicate(self) -> None:
        result = self.apply("**bold**", [(5, 4), (3, 1), (0, 0)], "bold")

        self.assertEqual(result.text, "bold")
        self.assertEqual(len(result.edits), 1)

    def test_adjacent_symmetric_markers_do_not_create_overlapping_empty_wrappers(self) -> None:
        result = self.apply("**bold**", [(7, 1), (0, 0)], "italic")

        self.assertEqual(result.text, "*text**bold*")
        self.assertEqual(len(result.edits), 2)

    def test_all_simple_inline_actions_emit_expected_markup(self) -> None:
        cases = {
            "italic": "*x*",
            "bold_italic": "***x***",
            "strikethrough": "~~x~~",
            "html_comment": "<!-- x -->",
            "insertion": "<ins>x</ins>",
            "critic_addition": "{++x++}",
            "critic_deletion": "{--x--}",
            "critic_highlight": "{==x==}",
            "critic_comment": "{>>x<<}",
        }

        for action, expected in cases.items():
            with self.subTest(action=action):
                result = self.apply("x", [(0, 1)], action)
                self.assertEqual(result.text, expected)
                self.assertEqual(result.text[slice(*result.selections[0])], "x")

    def test_configurable_emphasis_and_strong_markers(self) -> None:
        options = {"emphasis_marker": "_", "strong_marker": "__"}
        self.assertEqual(
            self.apply("x", [(0, 1)], "italic", options).text,
            "_x_",
        )
        self.assertEqual(
            self.apply("x", [(0, 1)], "bold", options).text,
            "__x__",
        )
        self.assertEqual(
            self.apply("x", [(0, 1)], "bold_italic", options).text,
            "___x___",
        )

    def test_custom_format_wraps_and_toggles(self) -> None:
        options = {"prefix": "<mark>", "suffix": "</mark>", "placeholder": "value"}
        first = self.apply("", [(0, 0)], "custom", options)

        self.assertEqual(first.text, "<mark>value</mark>")
        self.assertEqual(first.selections, ((6, 11),))

        second = self.apply(first.text, list(first.selections), "custom", options)
        self.assertEqual(second.text, "value")
        self.assertEqual(second.selections, ((0, 5),))

    def test_static_wrapper_does_not_pair_across_a_blank_paragraph(self) -> None:
        options = {"prefix": "<mark>", "suffix": "</mark>", "placeholder": "value"}
        text = "<mark>one\n\ntwo</mark>"
        start = text.index("two")
        first = self.apply(text, [(start, start + 3)], "custom", options)

        self.assertEqual(first.text, "<mark>one\n\n<mark>two</mark></mark>")

        second = self.apply(first.text, list(first.selections), "custom", options)
        self.assertEqual(second.text, text)

    def test_static_wrapper_ignores_escaped_emphasis_delimiters(self) -> None:
        text = r"\*literal\*"
        start = text.index("literal")
        first = self.apply(text, [(start, start + len("literal"))], "italic")

        self.assertEqual(first.text, r"\**literal*\*")
        self.assertEqual(first.text[slice(*first.selections[0])], "literal")

        second = self.apply(first.text, list(first.selections), "italic")
        self.assertEqual(second.text, text)

    def test_custom_format_accepts_literal_multiline_wrappers_and_toggles(self) -> None:
        options = {
            "prefix": ":::note\n",
            "suffix": "\n:::",
            "placeholder": "value",
        }
        first = self.apply("body", [(0, 4)], "custom", options)

        self.assertEqual(first.text, ":::note\nbody\n:::")
        self.assertEqual(first.selections, ((8, 12),))

        second = self.apply(first.text, list(first.selections), "custom", options)
        self.assertEqual(second.text, "body")
        self.assertEqual(second.selections, ((0, 4),))

    def test_custom_literal_suffix_toggles_when_content_ends_with_backslash(self) -> None:
        options = {"prefix": "<mark>", "suffix": "</mark>", "placeholder": "value"}
        first = self.apply("abc\\", [(0, 4)], "custom", options)

        self.assertEqual(first.text, "<mark>abc\\</mark>")

        second = self.apply(first.text, list(first.selections), "custom", options)
        self.assertEqual(second.text, "abc\\")
        self.assertEqual(second.selections, ((0, 4),))

    def test_inline_code_chooses_delimiter_longer_than_content_collision(self) -> None:
        result = self.apply("a`b", [(0, 3)], "inline_code")

        self.assertEqual(result.text, "``a`b``")
        self.assertEqual(result.selections, ((2, 5),))

        repeated = self.apply(result.text, list(result.selections), "inline_code")
        self.assertEqual(repeated.text, "a`b")
        self.assertEqual(repeated.selections, ((0, 3),))

    def test_inline_code_pads_boundary_backticks_without_selecting_padding(self) -> None:
        result = self.apply("`x``", [(0, 4)], "inline_code")

        self.assertEqual(result.text, "``` `x`` ```")
        self.assertEqual(result.selections, ((4, 8),))

        repeated = self.apply(result.text, list(result.selections), "inline_code")
        self.assertEqual(repeated.text, "`x``")

    def test_link_escapes_label_and_destination_and_toggles(self) -> None:
        options = {"link_url": "https://e.test/a(b) c"}
        first = self.apply("a[b]", [(0, 4)], "link", options)

        self.assertEqual(first.text, r"[a\[b\]](https://e.test/a\(b\)%20c)")
        self.assertEqual(first.text[slice(*first.selections[0])], r"a\[b\]")

        second = self.apply(first.text, list(first.selections), "link", options)
        self.assertEqual(second.text, "a[b]")
        self.assertEqual(second.selections, ((0, 4),))

    def test_image_uses_alt_text_and_configured_destination(self) -> None:
        result = self.apply(
            "logo",
            [(0, 4)],
            "image",
            {"link_url": "assets/logo(2).png"},
        )

        self.assertEqual(result.text, r"![logo](assets/logo\(2\).png)")
        self.assertEqual(result.selections, ((2, 6),))

    def test_critic_substitution_preserves_old_text_and_selects_new_placeholder(self) -> None:
        result = self.apply("old", [(0, 3)], "critic_substitution")

        self.assertEqual(result.text, "{~~old~>new~~}")
        self.assertEqual(result.selections, ((8, 11),))


class BlockFormattingTests(EngineTestCase):
    def test_heading_adds_replaces_and_same_level_toggles(self) -> None:
        added = self.apply("Title", [(0, 5)], "heading_2")
        self.assertEqual(added.text, "## Title")

        replaced = self.apply("# Title", [(0, 7)], "heading_2")
        self.assertEqual(replaced.text, "## Title")

        toggled = self.apply(replaced.text, list(replaced.selections), "heading_2")
        self.assertEqual(toggled.text, "Title")

    def test_heading_applies_uniformly_to_mixed_selected_lines(self) -> None:
        first = self.apply("# a\nb", [(0, 5)], "heading_1")
        self.assertEqual(first.text, "# a\n# b")

        second = self.apply(first.text, [(0, len(first.text))], "heading_1")
        self.assertEqual(second.text, "a\nb")

    def test_heading_blank_line_inserts_selected_placeholder(self) -> None:
        result = self.apply("", [(0, 0)], "heading_3")

        self.assertEqual(result.text, "### Heading")
        self.assertEqual(result.selections, ((4, 11),))

    def test_nonempty_selection_ending_at_next_line_start_excludes_that_line(self) -> None:
        result = self.apply("one\ntwo\n", [(0, 4)], "blockquote")

        self.assertEqual(result.text, "> one\ntwo\n")
        self.assertEqual(result.edits, (Replacement(0, 3, "> one"),))

    def test_empty_caret_at_exact_trailing_line_targets_empty_last_line(self) -> None:
        result = self.apply("one\n", [(4, 4)], "blockquote")

        self.assertEqual(result.text, "one\n> ")
        self.assertEqual(result.selections, ((6, 6),))

    def test_overlapping_line_selections_are_deduplicated(self) -> None:
        result = self.apply("a\nb\nc", [(0, 3), (2, 5)], "unordered_list")

        self.assertEqual(result.text, "- a\n- b\n- c")
        self.assertEqual(len(result.edits), 1)

    def test_blockquote_toggles_and_preserves_indentation(self) -> None:
        text = "  alpha\n\tbeta"
        first = self.apply(text, [(0, len(text))], "blockquote")
        self.assertEqual(first.text, "  > alpha\n\t> beta")

        second = self.apply(first.text, [(0, len(first.text))], "blockquote")
        self.assertEqual(second.text, text)

    def test_unordered_list_uniformly_applies_then_toggles_and_preserves_indent(self) -> None:
        first = self.apply("- a\n  b", [(0, 7)], "unordered_list")
        self.assertEqual(first.text, "- a\n  - b")

        second = self.apply(first.text, [(0, len(first.text))], "unordered_list")
        self.assertEqual(second.text, "a\n  b")

    def test_ordered_list_numbers_selected_lines_and_toggles(self) -> None:
        first = self.apply("a\nb", [(0, 3)], "ordered_list")
        self.assertEqual(first.text, "1. a\n2. b")

        second = self.apply(first.text, [(0, len(first.text))], "ordered_list")
        self.assertEqual(second.text, "a\nb")

    def test_task_list_adds_and_removes_checkboxes_without_losing_list_markers(self) -> None:
        first = self.apply("- a\n  1. b", [(0, 10)], "task_list")
        self.assertEqual(first.text, "- [ ] a\n  1. [ ] b")

        second = self.apply(first.text, [(0, len(first.text))], "task_list")
        self.assertEqual(second.text, "- a\n  1. b")

    def test_toggle_task_flips_checked_and_unchecked_items(self) -> None:
        result = self.apply("- [ ] a\n- [x] b", [(0, 15)], "toggle_task")

        self.assertEqual(result.text, "- [x] a\n- [ ] b")

    def test_fenced_code_wraps_whole_lines_and_repeat_unwraps(self) -> None:
        first = self.apply("code", [(1, 3)], "fenced_code")

        self.assertEqual(first.text, "```\ncode\n```")
        self.assertEqual(first.selections, ((5, 7),))

        second = self.apply(first.text, list(first.selections), "fenced_code")
        self.assertEqual(second.text, "code")
        self.assertEqual(second.selections, ((1, 3),))

    def test_fenced_code_uses_longer_fence_and_language(self) -> None:
        text = "```\nvalue"
        result = self.apply(
            text,
            [(0, len(text))],
            "fenced_code",
            {"fence_language": "python"},
        )

        self.assertEqual(result.text, "````python\n```\nvalue\n````")

    def test_fenced_code_preserves_following_line_and_trailing_newline_boundary(self) -> None:
        result = self.apply("code\nnext\n", [(0, 5)], "fenced_code")

        self.assertEqual(result.text, "```\ncode\n```\nnext\n")

    def test_horizontal_rule_inserts_on_blank_line_and_toggles_off(self) -> None:
        first = self.apply("", [(0, 0)], "horizontal_rule")
        self.assertEqual(first.text, "---")

        second = self.apply(first.text, [(0, 3)], "horizontal_rule")
        self.assertEqual(second.text, "")

    def test_horizontal_rule_after_nonblank_line_preserves_text_and_is_isolated(self) -> None:
        result = self.apply("alpha\nbeta", [(2, 2)], "horizontal_rule")

        self.assertEqual(result.text, "alpha\n\n---\n\nbeta")
        self.assertEqual(result.selections, ((2, 2),))
        self.assertEqual(result.edits, (Replacement(0, 5, "alpha\n\n---\n"),))


class TableAndFootnoteTests(EngineTestCase):
    def test_table_inserts_a_padded_two_by_two_placeholder(self) -> None:
        result = self.apply("", [(0, 0)], "table")

        self.assertEqual(
            result.text,
            "| Header 1 | Header 2 |\n"
            "| -------- | -------- |\n"
            "| Cell 1   | Cell 2   |\n"
            "| Cell 3   | Cell 4   |",
        )
        self.assertEqual(result.selections, ((2, 10),))

    def test_table_converts_tab_separated_text_escapes_pipes_and_pads_columns(self) -> None:
        text = "Name\tNote\nAda\ta|b"
        result = self.apply(text, [(0, len(text))], "table")

        self.assertEqual(
            result.text,
            "| Name | Note |\n"
            "| ---- | ---- |\n"
            "| Ada  | a\\|b |",
        )

    def test_table_converts_nonblank_plain_text_to_one_column_without_losing_rows(self) -> None:
        text = "Name\nAda"
        result = self.apply(text, [(0, len(text))], "table")

        self.assertEqual(
            result.text,
            "| Name |\n"
            "| ---- |\n"
            "| Ada  |",
        )

    def test_table_at_nonblank_caret_preserves_line_and_inserts_template_after_it(self) -> None:
        table = (
            "| Header 1 | Header 2 |\n"
            "| -------- | -------- |\n"
            "| Cell 1   | Cell 2   |\n"
            "| Cell 3   | Cell 4   |"
        )
        result = self.apply("intro\nnext", [(2, 2)], "table")

        self.assertEqual(result.text, "intro\n\n" + table + "\n\nnext")
        self.assertEqual(result.selections, ((9, 17),))
        self.assertEqual(result.edits, (Replacement(0, 5, "intro\n\n" + table + "\n"),))

    def test_table_preserves_one_existing_trailing_newline(self) -> None:
        text = "A\tB\n1\t2\n"
        result = self.apply(text, [(0, len(text))], "table")

        self.assertTrue(result.text.endswith("\n"))
        self.assertFalse(result.text.endswith("\n\n"))

    def test_footnote_replaces_selection_and_appends_definition(self) -> None:
        text = "See detail."
        result = self.apply(text, [(4, 10)], "footnote")

        self.assertEqual(result.text, "See [^note].\n\n[^note]: detail")
        definition_start = result.text.rindex("detail")
        self.assertEqual(result.selections, ((definition_start, definition_start + 6),))
        self.assertEqual(len(result.edits), 2)

    def test_footnote_avoids_existing_reference_and_definition_labels(self) -> None:
        text = "Ref.\n\n[^note]: existing"
        result = self.apply(
            text,
            [(4, 4)],
            "footnote",
            {"select_word_on_empty": False},
        )

        self.assertIn("[^note2]", result.text)
        self.assertIn("[^note]: existing", result.text)
        self.assertIn("[^note2]: Footnote text", result.text)
        self.assertEqual(result.text.count("[^note]: existing"), 1)

    def test_multiple_footnotes_get_unique_labels_and_definition_selections(self) -> None:
        text = "one two"
        result = self.apply(text, [(0, 3), (4, 7)], "footnote")

        self.assertEqual(
            result.text,
            "[^note] [^note2]\n\n[^note]: one\n[^note2]: two",
        )
        self.assertEqual(result.text[slice(*result.selections[0])], "one")
        self.assertEqual(result.text[slice(*result.selections[1])], "two")

    def test_footnote_respects_existing_trailing_newline(self) -> None:
        text = "See\n"
        result = self.apply(
            text,
            [(3, 3)],
            "footnote",
            {"select_word_on_empty": False},
        )

        self.assertEqual(result.text, "See[^note]\n\n[^note]: Footnote text")


class WrapperBoundaryRegressions(EngineTestCase):
    def test_custom_wrapper_toggles_across_blank_paragraphs(self):
        original = "one\n\ntwo"
        options = {"prefix": "<div>", "suffix": "</div>"}
        first = self.apply(original, [(0, len(original))], "custom", options)
        second = self.apply(first.text, list(first.selections), "custom", options)
        self.assertEqual(second.text, original)

    def test_emphasis_search_is_local_to_selected_paragraph(self):
        from unittest.mock import patch
        from mdformat import engine
        before = "*item*\n\n" * 80
        after = "\n\n*item*" * 80
        text = before + "target" + after
        original = engine._valid_static_wrapper
        calls = []
        def observe(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        with patch.object(engine, '_valid_static_wrapper', side_effect=observe):
            result = self.apply(text, [(len(before), len(before) + 6)], 'italic')
        self.assertEqual(result.text, before + '*target*' + after)
        self.assertLess(len(calls), 10, 'Unrelated paragraph delimiters must not be paired')


class ValidationTests(EngineTestCase):
    def test_empty_selection_collection_is_a_noop(self) -> None:
        result = self.apply("unchanged", [], "bold")
        self.assertEqual(result, FormatResult("unchanged", (), ()))

    def test_unsupported_action_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            format_document("x", [(0, 1)], "not_an_action")

    def test_invalid_selection_shapes_types_and_bounds_raise_value_error(self) -> None:
        invalid = [
            None,
            [(0,)],
            [(0, 1, 2)],
            [(0.0, 1)],
            [(True, 1)],
            [(-1, 0)],
            [(0, 2)],
        ]
        for selections in invalid:
            with self.subTest(selections=selections):
                with self.assertRaises(ValueError):
                    format_document("x", selections, "bold")

    def test_invalid_options_raise_value_error(self) -> None:
        cases = [
            "not a dict",
            {"select_word_on_empty": "yes"},
            {"emphasis_marker": ""},
            {"fence_language": "python\ntext"},
        ]
        for options in cases:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    format_document("x", [(0, 1)], "italic", options)

    def test_custom_requires_valid_prefix_suffix_and_placeholder(self) -> None:
        invalid = [
            {},
            {"prefix": "", "suffix": "", "placeholder": "x"},
            {"prefix": 1, "suffix": "!", "placeholder": "x"},
            {"prefix": "!", "suffix": "!", "placeholder": None},
        ]
        for options in invalid:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    format_document("x", [(0, 1)], "custom", options)


class EnginePerformanceTests(EngineTestCase):
    def test_large_repeated_block_selection_mapping_has_bounded_runtime(self) -> None:
        text = "\n".join(["repeat"] * 200)

        started = time.perf_counter()
        result = format_document(text, [(0, len(text))], "blockquote")
        elapsed = time.perf_counter() - started

        self.assert_invariants(text, result)
        self.assertEqual(result.text.count("> repeat"), 200)
        self.assertEqual(result.selections, ((2, len(result.text)),))
        self.assertLess(elapsed, 1.0, "formatting took {0:.3f}s".format(elapsed))


if __name__ == "__main__":
    unittest.main()
