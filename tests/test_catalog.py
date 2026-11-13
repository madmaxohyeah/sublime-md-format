import json
import unittest
from collections import Counter
from pathlib import Path

from mdformat.catalog import (
    ACTIONS,
    available_actions,
    custom_formats,
    label_for,
    merge_settings,
    resolve_settings,
)


ROOT = Path(__file__).resolve().parents[1]

ACTION_IDS = [
    "heading_1",
    "heading_2",
    "heading_3",
    "heading_4",
    "heading_5",
    "heading_6",
    "bold",
    "italic",
    "bold_italic",
    "strikethrough",
    "inline_code",
    "fenced_code",
    "link",
    "image",
    "blockquote",
    "unordered_list",
    "ordered_list",
    "task_list",
    "toggle_task",
    "horizontal_rule",
    "table",
    "html_comment",
    "insertion",
    "footnote",
    "critic_addition",
    "critic_deletion",
    "critic_substitution",
    "critic_highlight",
    "critic_comment",
]

CRITIC_IDS = {
    "critic_addition",
    "critic_deletion",
    "critic_substitution",
    "critic_highlight",
    "critic_comment",
}


def load_json(name):
    with (ROOT / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def walk_menu(items):
    for item in items:
        yield item
        children = item.get("children")
        if isinstance(children, list):
            for child in walk_menu(children):
                yield child


class ActionCatalogTests(unittest.TestCase):
    def test_registry_has_stable_order_and_required_metadata(self):
        self.assertEqual(list(ACTIONS), ACTION_IDS)
        for action_id, metadata in ACTIONS.items():
            with self.subTest(action=action_id):
                self.assertIsInstance(metadata, dict)
                self.assertIsInstance(metadata["label"], str)
                self.assertTrue(metadata["label"])
                self.assertIsInstance(metadata["group"], str)
                self.assertTrue(metadata["group"])
                self.assertIsInstance(metadata["profiles"], tuple)
                self.assertTrue(metadata["profiles"])
                self.assertLessEqual(
                    set(metadata["profiles"]),
                    {"gfm", "commonmark", "multimarkdown"},
                )

    def test_profile_capability_matrix_is_explicit(self):
        gfm = set(available_actions({"profile": "gfm"}))
        commonmark = set(available_actions({"profile": "commonmark"}))
        multimarkdown = set(available_actions({"profile": "multimarkdown"}))

        self.assertTrue({"strikethrough", "table", "task_list", "toggle_task"} <= gfm)
        self.assertNotIn("footnote", gfm)

        self.assertTrue(
            {"strikethrough", "table", "task_list", "toggle_task", "footnote"}
            .isdisjoint(commonmark)
        )

        self.assertTrue({"table", "footnote"} <= multimarkdown)
        self.assertTrue(
            {"strikethrough", "task_list", "toggle_task"}.isdisjoint(multimarkdown)
        )

        for actions in (gfm, commonmark, multimarkdown):
            self.assertTrue(CRITIC_IDS <= actions)

    def test_critic_markup_can_be_disabled_for_every_profile(self):
        for profile in ("gfm", "commonmark", "multimarkdown"):
            with self.subTest(profile=profile):
                actions = set(
                    available_actions(
                        {"profile": profile, "enable_critic_markup": False}
                    )
                )
                self.assertTrue(CRITIC_IDS.isdisjoint(actions))

    def test_hidden_actions_and_picker_order_are_applied_after_profile_gating(self):
        settings = {
            "profile": "multimarkdown",
            "enable_critic_markup": True,
            "hidden_actions": ["bold", "critic_comment", "bold", "unknown", 7],
            "picker_order": [
                "footnote",
                "italic",
                "task_list",
                "footnote",
                "unknown",
            ],
        }
        actions = available_actions(settings)

        self.assertEqual(actions[:2], ["footnote", "italic"])
        self.assertNotIn("bold", actions)
        self.assertNotIn("critic_comment", actions)
        self.assertNotIn("task_list", actions)
        self.assertEqual(len(actions), len(set(actions)))

    def test_whole_malformed_settings_values_fall_back_to_fresh_defaults(self):
        for raw in (None, [], "bad", 5, True):
            with self.subTest(raw=raw):
                settings = resolve_settings(raw)
                self.assertEqual(settings["profile"], "gfm")
                self.assertIs(settings["markdown_only"], True)
                self.assertEqual(settings["hidden_actions"], [])
                self.assertEqual(settings["labels"], {})
                self.assertEqual(settings["styles"], {})
                self.assertEqual(settings["custom_formats"], [])
                self.assertIs(settings["enable_critic_markup"], True)

        first = resolve_settings(None)
        second = resolve_settings(None)
        first["hidden_actions"].append("bold")
        first["labels"]["bold"] = "Changed"
        self.assertEqual(second["hidden_actions"], [])
        self.assertEqual(second["labels"], {})

    def test_settings_are_validated_field_by_field_without_bool_as_int_coercion(self):
        oversized_label = "x" * 121
        settings = resolve_settings(
            {
                "profile": "commonmark",
                "markdown_only": False,
                "hidden_actions": ["bold", "unknown", True, "bold"],
                "labels": {
                    "bold": "Strong",
                    "italic": 9,
                    "link": "<Link & More>",
                    "image": oversized_label,
                    "unknown": "Nope",
                },
                "picker_order": ["link", "bold", "link", False, "unknown"],
                "styles": {
                    "bold": {
                        "color": "#aBc",
                        "bold": True,
                        "italic": False,
                        "background": "url(evil)",
                    },
                    "italic": {"color": "red", "bold": 1, "italic": True},
                    "link": "not-a-style",
                    "unknown": {"color": "#fff"},
                },
                "enable_critic_markup": True,
                "select_word_on_empty": False,
                "bullet_marker": "+",
                "emphasis_marker": "_",
                "strong_marker": "__",
                "fence_language": "python-3.14",
                "link_url": "/documentation",
            }
        )

        self.assertEqual(settings["profile"], "commonmark")
        self.assertIs(settings["markdown_only"], False)
        self.assertEqual(settings["hidden_actions"], ["bold"])
        self.assertEqual(
            settings["labels"],
            {"bold": "Strong", "link": "<Link & More>"},
        )
        self.assertEqual(settings["picker_order"], ["link", "bold"])
        self.assertEqual(
            settings["styles"],
            {
                "bold": {"color": "#aBc", "bold": True, "italic": False},
                "italic": {"italic": True},
            },
        )
        self.assertIs(settings["enable_critic_markup"], True)
        self.assertIs(settings["select_word_on_empty"], False)
        self.assertEqual(settings["bullet_marker"], "+")
        self.assertEqual(settings["emphasis_marker"], "_")
        self.assertEqual(settings["strong_marker"], "__")
        self.assertEqual(settings["fence_language"], "python-3.14")
        self.assertEqual(settings["link_url"], "/documentation")

        malformed = resolve_settings(
            {
                "profile": "GFM",
                "markdown_only": 0,
                "enable_critic_markup": 1,
                "select_word_on_empty": 1,
                "bullet_marker": True,
                "emphasis_marker": "**",
                "strong_marker": "*",
                "fence_language": "python\nhtml",
                "link_url": "https://example.test/\nnext",
            }
        )
        self.assertEqual(malformed["profile"], "gfm")
        self.assertIs(malformed["markdown_only"], True)
        self.assertIs(malformed["enable_critic_markup"], True)
        self.assertIs(malformed["select_word_on_empty"], True)
        self.assertEqual(malformed["bullet_marker"], "-")
        self.assertEqual(malformed["emphasis_marker"], "*")
        self.assertEqual(malformed["strong_marker"], "**")
        self.assertEqual(malformed["fence_language"], "")
        self.assertEqual(malformed["link_url"], "https://example.com")

    def test_action_lists_ignore_unhashable_values(self):
        settings = resolve_settings(
            {
                "hidden_actions": [{}, [], "bold"],
                "picker_order": [["italic"], {"action": "link"}, "italic"],
            }
        )
        self.assertEqual(settings["hidden_actions"], ["bold"])
        self.assertEqual(settings["picker_order"], ["italic"])

    def test_merge_settings_ignores_invalid_present_fields(self):
        base = {
            "profile": "commonmark",
            "markdown_only": False,
            "hidden_actions": ["bold"],
            "labels": {"bold": "Strong"},
            "picker_order": ["italic"],
            "styles": {"bold": {"color": "#abc"}},
            "custom_formats": [
                {"label": "Mark", "prefix": "<mark>", "suffix": "</mark>"}
            ],
            "enable_critic_markup": True,
            "select_word_on_empty": False,
            "bullet_marker": "+",
            "emphasis_marker": "_",
            "strong_marker": "__",
            "fence_language": "python",
            "link_url": "/documentation",
        }
        invalid = {
            "profile": "invalid",
            "markdown_only": 0,
            "hidden_actions": "bold",
            "labels": ["Strong"],
            "picker_order": {"first": "italic"},
            "styles": ["bold"],
            "custom_formats": {"label": "Mark"},
            "enable_critic_markup": 1,
            "select_word_on_empty": None,
            "bullet_marker": True,
            "emphasis_marker": "**",
            "strong_marker": "*",
            "fence_language": "python\nhtml",
            "link_url": "https://example.test/\nnext",
        }

        self.assertEqual(merge_settings(base, invalid), resolve_settings(base))

    def test_nonempty_invalid_container_does_not_act_as_an_explicit_reset(self):
        base = {
            "hidden_actions": ["bold"],
            "picker_order": ["italic"],
            "labels": {"bold": "Strong"},
            "styles": {"bold": {"color": "#abc"}},
            "custom_formats": [{"label": "Mark", "prefix": "<mark>", "suffix": "</mark>"}],
        }
        malformed = {
            "hidden_actions": [None, "unknown"],
            "picker_order": [True],
            "labels": {"bold": ""},
            "styles": {"bold": {"color": "not-a-color"}},
            "custom_formats": [{"label": "missing required template"}],
        }
        self.assertEqual(merge_settings(base, malformed), resolve_settings(base))

    def test_merge_settings_accepts_explicit_default_and_empty_resets(self):
        base = {
            "profile": "commonmark",
            "markdown_only": False,
            "hidden_actions": ["bold"],
            "labels": {"bold": "Strong"},
            "picker_order": ["italic"],
            "styles": {"bold": {"color": "#abc"}},
            "custom_formats": [
                {"label": "Mark", "prefix": "<mark>", "suffix": "</mark>"}
            ],
            "enable_critic_markup": True,
            "select_word_on_empty": False,
            "bullet_marker": "+",
            "emphasis_marker": "_",
            "strong_marker": "__",
            "fence_language": "python",
            "link_url": "/documentation",
        }
        resets = {
            "profile": "gfm",
            "markdown_only": True,
            "hidden_actions": [],
            "labels": {},
            "picker_order": [],
            "styles": {},
            "custom_formats": [],
            "enable_critic_markup": False,
            "select_word_on_empty": True,
            "bullet_marker": "-",
            "emphasis_marker": "*",
            "strong_marker": "**",
            "fence_language": "",
            "link_url": "https://example.com",
        }

        self.assertEqual(merge_settings(base, resets), resolve_settings(resets))
        self.assertIs(merge_settings(base, resets)["enable_critic_markup"], False)

    def test_merge_settings_replaces_valid_container_fields_without_deep_merging(self):
        base = {
            "hidden_actions": ["bold"],
            "labels": {"bold": "Strong", "italic": "Slant"},
            "styles": {
                "bold": {"bold": True},
                "italic": {"italic": True},
            },
        }
        override = {
            "hidden_actions": ["italic"],
            "labels": {"link": "Reference"},
            "styles": {"link": {"color": "#abc"}},
        }

        merged = merge_settings(base, override)

        self.assertEqual(merged["hidden_actions"], ["italic"])
        self.assertEqual(merged["labels"], {"link": "Reference"})
        self.assertEqual(merged["styles"], {"link": {"color": "#abc"}})

    def test_labels_fall_back_and_unknown_actions_raise(self):
        settings = resolve_settings({"labels": {"bold": "Heavy", "italic": ""}})
        self.assertEqual(label_for("bold", settings), "Heavy")
        self.assertEqual(label_for("italic", settings), ACTIONS["italic"]["label"])
        with self.assertRaises(KeyError):
            label_for("not_an_action", settings)

    def test_custom_format_placeholder_defaults_to_text_when_omitted(self):
        formats = custom_formats(
            {
                "custom_formats": [
                    {"label": "Keyboard", "prefix": "<kbd>", "suffix": "</kbd>"}
                ]
            }
        )
        self.assertEqual(
            formats,
            [
                {
                    "label": "Keyboard",
                    "prefix": "<kbd>",
                    "suffix": "</kbd>",
                    "placeholder": "text",
                }
            ],
        )

    def test_custom_formats_are_bounded_and_never_expose_commands_or_snippets(self):
        valid = {
            "label": "Keyboard",
            "prefix": "<kbd>",
            "suffix": "</kbd>",
            "placeholder": "key",
            "color": "#12aBCf",
            "command": "exec",
            "snippet": "${1:danger}",
        }
        invalid_color = {
            "label": "Highlight",
            "prefix": "==",
            "suffix": "==",
            "placeholder": "text",
            "color": "#fff; background:url(evil)",
        }
        malformed = [
            None,
            {"label": "Missing suffix", "prefix": "[", "placeholder": "text"},
            {"label": "No-op", "prefix": "", "suffix": "", "placeholder": "x"},
            {"label": True, "prefix": "<", "suffix": ">", "placeholder": "x"},
            {
                "label": "Too long",
                "prefix": "x" * 257,
                "suffix": "",
                "placeholder": "x",
            },
        ]
        many = [
            {
                "label": "Format {0}".format(index),
                "prefix": "[",
                "suffix": "]",
                "placeholder": "text",
            }
            for index in range(40)
        ]

        formats = custom_formats(
            {"custom_formats": [valid, invalid_color] + malformed + many}
        )

        self.assertEqual(len(formats), 32)
        self.assertEqual(
            formats[0],
            {
                "label": "Keyboard",
                "prefix": "<kbd>",
                "suffix": "</kbd>",
                "placeholder": "key",
            },
        )
        self.assertEqual(
            formats[1],
            {
                "label": "Highlight",
                "prefix": "==",
                "suffix": "==",
                "placeholder": "text",
            },
        )
        for item in formats:
            self.assertEqual(set(item), {"label", "prefix", "suffix", "placeholder"})

    def test_default_settings_resource_is_strict_json_and_resolves(self):
        raw = load_json("MarkdownFormatting.sublime-settings")
        settings = resolve_settings(raw)

        self.assertEqual(settings["profile"], "gfm")
        self.assertIs(settings["markdown_only"], True)
        self.assertIs(settings["enable_critic_markup"], True)
        self.assertEqual(settings["bullet_marker"], "-")
        self.assertEqual(settings["emphasis_marker"], "*")
        self.assertEqual(settings["strong_marker"], "**")
        self.assertEqual(settings["link_url"], "https://example.com")
        self.assertNotIn("styles", raw)
        self.assertEqual(settings["styles"], {})
        self.assertIn("automatically", raw["_documentation"]["styled_picker"])

    def test_context_menu_registers_every_action_once_without_static_captions(self):
        menu = load_json("Context.sublime-menu")
        self.assertEqual(len(menu), 1)
        root = menu[0]
        self.assertEqual(root["caption"], "Markdown Formatting")
        self.assertEqual(root["command"], "md_format_menu")

        action_items = [
            item for item in walk_menu(root["children"])
            if item.get("command") == "md_format"
        ]
        actions = [item.get("args", {}).get("action") for item in action_items]
        self.assertEqual(Counter(actions), Counter(ACTION_IDS))
        for item in action_items:
            self.assertNotIn("caption", item)
            self.assertEqual(item["args"], {"action": item["args"]["action"], "context": True})

        submenu_captions = {
            item.get("caption")
            for item in root["children"]
            if isinstance(item.get("children"), list)
        }
        self.assertTrue({"Headings", "Lists", "Insert", "Review"} <= submenu_captions)

        utility_commands = {
            item.get("command") for item in walk_menu(root["children"])
        }
        self.assertTrue(
            {
                "md_format_picker",
                "md_format_profile",
                "md_format_repeat",
                "md_format_settings",
            }
            <= utility_commands
        )

    def test_command_palette_has_the_five_default_utility_entries(self):
        commands = load_json("Default.sublime-commands")
        self.assertEqual(
            [item["command"] for item in commands],
            [
                "md_format_picker",
                "md_format_picker",
                "md_format_settings",
                "md_format_profile",
                "md_format_repeat",
            ],
        )
        self.assertEqual(commands[0]["args"], {"mode": "search"})
        self.assertEqual(commands[1]["args"], {"mode": "styled"})
        # The context-menu opt-out must never hide Command Palette entries.
        self.assertFalse(any("context" in item.get("args", {}) for item in commands))
        self.assertTrue(
            all(item["caption"].startswith("Markdown Formatting:") for item in commands)
        )

    def test_every_context_leaf_but_settings_is_marked_as_a_context_entry(self):
        root = load_json("Context.sublime-menu")[0]
        leaves = [
            item for item in walk_menu(root["children"])
            if "command" in item and "children" not in item
        ]
        self.assertTrue(leaves)
        for item in leaves:
            with self.subTest(item=item):
                if item["command"] == "md_format_settings":
                    # Keeps the Windows/macOS heading usable after opting out.
                    self.assertNotIn("args", item)
                else:
                    self.assertIs(item["args"]["context"], True)
        parents = [item for item in walk_menu([root]) if "children" in item]
        for item in parents:
            self.assertEqual(item["command"], "md_format_menu")
            self.assertNotIn("context", item.get("args", {}))

    def test_custom_format_text_admits_only_newline_and_tab_controls(self):
        base = {"label": "Wrap", "prefix": "<", "suffix": ">", "placeholder": "x"}
        accepted = custom_formats({"custom_formats": [
            dict(base, prefix="<div>\n\t", suffix="\n</div>", placeholder="a\nb\tc"),
        ]})
        self.assertEqual(accepted[0]["prefix"], "<div>\n\t")
        self.assertEqual(accepted[0]["placeholder"], "a\nb\tc")
        for field in ("prefix", "suffix", "placeholder"):
            for value in ("a\rb", "a\r\nb", "a\x0bb", "a\x0cb", "a\x00b", "a\x7fb"):
                with self.subTest(field=field, value=value):
                    self.assertEqual(
                        custom_formats({"custom_formats": [dict(base, **{field: value})]}), [])

    def test_empty_link_url_is_accepted_like_empty_fence_language(self):
        from mdformat.engine import format_document

        settings = resolve_settings({"link_url": "", "fence_language": ""})
        self.assertEqual(settings["link_url"], "")
        self.assertEqual(merge_settings({"link_url": "/docs"}, {"link_url": ""})["link_url"], "")
        self.assertEqual(resolve_settings({"link_url": None})["link_url"], "https://example.com")
        result = format_document("site", [(0, 4)], "link", settings)
        self.assertEqual(result.text, "[site]()")

    def test_action_metadata_has_only_consumed_fields(self):
        for action, metadata in ACTIONS.items():
            with self.subTest(action=action):
                self.assertEqual(set(metadata), {"label", "group", "profiles"})

    def test_profile_display_names_cover_every_profile(self):
        from mdformat.catalog import PROFILE_NAMES, PROFILES, profile_name

        self.assertEqual(tuple(PROFILE_NAMES), PROFILES)
        self.assertEqual(profile_name("gfm"), "GitHub Flavored Markdown")
        self.assertEqual(profile_name("commonmark"), "CommonMark")
        self.assertEqual(profile_name("multimarkdown"), "MultiMarkdown")

    def test_main_menu_exposes_plugin_owned_settings_command(self):
        menu = load_json("Main.sublime-menu")
        nodes = list(walk_menu(menu))
        settings_items = [
            item for item in nodes if item.get("command") == "md_format_settings"
        ]
        self.assertEqual(settings_items, [{"caption": "Settings", "command": "md_format_settings"}])
        captions = [item.get("caption") for item in nodes]
        self.assertIn("Package Settings", captions)
        self.assertIn("Markdown Formatting", captions)


if __name__ == "__main__":
    unittest.main()
