"""Test-only Sublime plugin. Copy to an isolated profile's Packages/User.

Never included in the release archive. Uses real Sublime APIs, not API fakes.
Set MD_FORMAT_EVIDENCE to the output directory before launching the editor.
"""
import hashlib
from html.parser import HTMLParser
import json
import os
import sys
import traceback
from pathlib import Path

import sublime
import sublime_plugin


OUTPUT = Path(os.environ.get("MD_FORMAT_EVIDENCE", "."))


def write_json(name, data):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class MarkdownFormattingSmokeCommand(sublime_plugin.WindowCommand):
    def run(self):
        from MarkdownFormatting import markdown_formatting as plugin
        from MarkdownFormatting.mdformat.catalog import ACTIONS, available_actions

        results = []
        views = []

        def case(name, text, selections, action, expected=None, settings=None, undo=False):
            view = self.window.new_file()
            views.append(view)
            view.set_scratch(True)
            view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")
            view.settings().set("markdown_formatting", settings or {})
            view.run_command("append", {"characters": text})
            view.sel().clear()
            for a, b in selections:
                view.sel().add(sublime.Region(a, b))
            before = view.substr(sublime.Region(0, view.size()))
            arguments = {"action": action}
            if action == "custom":
                arguments["custom_index"] = 0
            view.run_command("md_format", arguments)
            actual = view.substr(sublime.Region(0, view.size()))
            if expected is not None:
                assert actual == expected, (name, expected, actual)
            else:
                assert actual != before, (name, "action did not change text")
            after_selections = [[r.a, r.b] for r in view.sel()]
            if undo:
                view.run_command("undo")
                assert view.substr(sublime.Region(0, view.size())) == before, (name, "single undo")
                view.run_command("redo")
                assert view.substr(sublime.Region(0, view.size())) == actual, (name, "redo")
            results.append({"name": name, "action": action, "output": actual,
                            "selections": after_selections, "undo_redo": undo, "passed": True})
            return view

        try:
            case("bold and single undo", "hello world", [(0, 5)], "bold", "**hello** world", undo=True)
            case("multiple selections", "one two", [(0, 3), (4, 7)], "italic", "*one* *two*", undo=True)
            case("Unicode", "Grüße 👋", [(0, 7)], "bold", "**Grüße 👋**", undo=True)
            case("heading", "hello\nworld", [(0, 5)], "heading_2", "## hello\nworld")
            case("boundary whitespace", " hello ", [(0, 7)], "bold", " **hello** ", undo=True)
            rule = case("rule preserves nonblank content", "keep\nnext", [(2, 2)], "horizontal_rule")
            rule_text = rule.substr(sublime.Region(0, rule.size()))
            assert "keep" in rule_text and "next" in rule_text and "\n\n---\n\n" in rule_text
            table = case("table caret preserves line", "keep\nnext", [(2, 2)], "table")
            table_text = table.substr(sublime.Region(0, table.size()))
            assert "keep" in table_text and "next" in table_text and "Header 1" in table_text
            case("commonmark blocks GFM", "hello", [(0, 5)], "strikethrough", "hello",
                 {"profile": "commonmark"})
            case("hidden action", "hello", [(0, 5)], "bold", "hello", {"hidden_actions": ["bold"]})
            case("CriticMarkup enabled by default", "hello", [(0, 5)],
                 "critic_addition", "{++hello++}", undo=True)
            case("CriticMarkup explicit false blocks execution", "hello", [(0, 5)],
                 "critic_addition", "hello", {"enable_critic_markup": False})
            for action in ACTIONS:
                if action == "toggle_task":
                    text = "- [ ] todo"
                elif action == "table":
                    text = "Name\tValue\nAlpha\tOne"
                else:
                    text = "sample text"
                case("builtin " + action, text, [(0, len(text))], action,
                     settings={"profile": "multimarkdown" if action == "footnote" else "gfm",
                               "enable_critic_markup": True})
            view = case("repeat setup", "hello", [(0, 5)], "bold", "**hello**")
            view.run_command("md_format_repeat")
            assert view.substr(sublime.Region(0, view.size())) == "hello"
            results.append({"name": "repeat toggles", "passed": True})
            view.set_read_only(True)
            view.run_command("md_format", {"action": "italic"})
            assert view.substr(sublime.Region(0, view.size())) == "hello"
            results.append({"name": "read-only direct execution", "passed": True})
            view.set_read_only(False)
            view.settings().set("markdown_formatting", {"custom_formats": [
                {"label": "Highlight", "prefix": "<mark>", "suffix": "</mark>", "placeholder": "text"}
            ]})
            view.run_command("md_format", {"action": "custom", "custom_index": 0})
            assert view.substr(sublime.Region(0, view.size())) == "<mark>hello</mark>"
            results.append({"name": "configured custom format", "passed": True})
            for profile in ("commonmark", "gfm", "multimarkdown"):
                view.settings().set("markdown_formatting", {"profile": profile})
                resolved = plugin.settings_for(view)
                enabled = available_actions(resolved)
                assert ("table" in enabled) == (profile != "commonmark")
                assert ("footnote" in enabled) == (profile == "multimarkdown")
                assert ("task_list" in enabled) == (profile == "gfm")
                results.append({"name": "profile " + profile, "passed": True, "enabled": enabled})
            for action, prefix, suffix in (
                ("italic", "*", "*"), ("bold", "**", "**"),
                ("bold_italic", "***", "***"), ("strikethrough", "~~", "~~"),
                ("inline_code", "`", "`"), ("html_comment", "<!-- ", " -->"),
                ("insertion", "<ins>", "</ins>"),
            ):
                left, right = prefix + "one" + suffix + " ", " " + prefix + "two" + suffix
                case("sibling preservation " + action, left + "middle" + right,
                     [(len(left), len(left) + len("middle"))], action,
                     left + prefix + "middle" + suffix + right, undo=True)
            left, right = "```\none\n```\n", "\n```\ntwo\n```"
            case("sibling fenced block preservation", left + "middle" + right,
                 [(len(left), len(left) + len("middle"))], "fenced_code",
                 left + "```\nmiddle\n```" + right, undo=True)
            for prefix, suffix in (("ab", "a"), ("<<", "<"), ("xyx", "x"),
                                   ("a", "ab"), ("<", "<<"), ("abab", "ab"), ("aaa", "aa")):
                view = case("overlapping custom template " + prefix + "/" + suffix,
                            "middle", [(0, 6)], "custom", prefix + "middle" + suffix,
                            {"custom_formats": [{"label": "Overlap", "prefix": prefix, "suffix": suffix}]},
                            undo=True)
                view.run_command("md_format_repeat")
                assert view.substr(sublime.Region(0, view.size())) == "middle"
                results.append({"name": "overlapping custom repeat " + prefix + "/" + suffix, "passed": True})
            global_settings = sublime.load_settings("MarkdownFormatting.sublime-settings")
            keys = ("profile", "hidden_actions", "styles")
            saved = {key: global_settings.get(key) for key in keys}
            saved_project = self.window.project_data()
            try:
                global_settings.set("profile", "commonmark")
                global_settings.set("hidden_actions", ["bold"])
                global_settings.set("styles", {"bold": {"color": "#abc"}})
                invalid = {"profile": "invalid", "hidden_actions": "invalid", "styles": "invalid"}
                self.window.set_project_data({"settings": {"markdown_formatting": invalid}})
                view.settings().set("markdown_formatting", invalid)
                resolved = plugin.settings_for(view)
                assert resolved["profile"] == "commonmark"
                assert resolved["hidden_actions"] == ["bold"]
                assert resolved["styles"] == {"bold": {"color": "#abc"}}
                results.append({"name": "invalid project and view fields retain global settings", "passed": True})
                self.window.set_project_data({"settings": {"markdown_formatting": {
                    "profile": "multimarkdown", "hidden_actions": ["italic"]}}})
                resolved = plugin.settings_for(view)
                assert resolved["profile"] == "multimarkdown"
                assert resolved["hidden_actions"] == ["italic"]
                results.append({"name": "invalid view fields retain project settings", "passed": True})
            finally:
                self.window.set_project_data(saved_project or {})
                for key, value in saved.items():
                    if value is None:
                        global_settings.erase(key)
                    else:
                        global_settings.set(key, value)
            archive = Path(sublime.installed_packages_path()) / "MarkdownFormatting.sublime-package"
            assert archive.is_file(), "Must test installed archive, not source checkout"
            assert not (Path(sublime.packages_path()) / "MarkdownFormatting").exists(), "Unpacked package masks archive"
            report = {"passed": True, "build": sublime.version(), "python": sys.version,
                      "platform": sublime.platform(), "module": plugin.__file__,
                      "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "cases": results}
        except Exception:
            report = {"passed": False, "build": sublime.version(), "python": sys.version,
                      "error": traceback.format_exc(), "cases": results}
        for view in views:
            view.close()
        view = self.window.new_file()
        view.set_scratch(True)
        view.set_name("Markdown Formatting — mouse acceptance.md")
        view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")
        view.settings().set("font_size", 15)
        view.settings().set("markdown_formatting", {})
        view.run_command("append", {"characters": "Mouse formatting\n\nSelect text, right-click, then choose Markdown Formatting.\n\nNo shortcuts to memorize. No external tools.\n"})
        view.sel().clear()
        view.sel().add(sublime.Region(0, 16))
        self.window.focus_view(view)
        if report["passed"]:
            PickerRuntimeChecks(view, report).start()
        else:
            write_json("runtime.json", report)


class PickerRows(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.rows = {}
        self.target = None
        self.colors = []
        self.heading_color = None
        self.tags = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.add(tag)
        if tag == "a":
            self.target = attrs.get("href")
            self.rows[self.target] = ""
        elif tag == "span":
            declarations = dict(part.split(":", 1) for part in attrs.get("style", "").split(";") if ":" in part)
            self.colors.append(declarations.get("color"))
        elif tag == "br" and self.target:
            self.rows[self.target] += "\n"

    def handle_endtag(self, tag):
        if tag == "a":
            self.target = None
        elif tag == "span" and self.colors:
            self.colors.pop()

    def handle_data(self, data):
        if self.target:
            self.rows[self.target] += data.replace("\xa0", " ")
        if self.target == "action:heading_1" and data == "#" and self.colors:
            self.heading_color = self.colors[-1]


class PickerRuntimeChecks:
    DARK = "Packages/Color Scheme - Default/Mariana.sublime-color-scheme"
    LIGHT = "Packages/Color Scheme - Default/Celeste.sublime-color-scheme"

    def __init__(self, view, report):
        from MarkdownFormatting import markdown_formatting as plugin
        self.plugin = plugin
        self.view = view
        self.report = report
        self.prefs = sublime.load_settings("Preferences.sublime-settings")
        self.saved = {key: self.prefs.get(key) for key in ("theme", "color_scheme")}
        self.saved_scheme = view.settings().get("color_scheme")
        self.before = self.snapshot()
        self.report["picker_appearance"] = {}

    def snapshot(self):
        view = self.view
        return {"text": view.substr(sublime.Region(0, view.size())),
                "selections": [(r.a, r.b) for r in view.sel()],
                "change_count": view.change_count(), "dirty": view.is_dirty(),
                "history": view.command_history(0, True),
                "focused": view.window().active_view().id() == view.id()}

    def case(self, name):
        self.report["cases"].append({"name": name, "passed": True})

    def later(self, callback):
        def guarded():
            try:
                callback()
            except Exception:
                self.report.update(passed=False, error=traceback.format_exc())
                self.finish()
        sublime.set_timeout(guarded, 300)

    def session(self):
        return self.plugin.sublime_picker._SESSIONS[self.view.id()]

    def assert_preview(self, name):
        assert self.view.is_popup_visible(), (name, "popup closed")
        session = self.session()
        assert not session.failed_notice, (name, "unexpected plain fallback")
        rows = PickerRows(session.html)
        assert rows.rows["action:heading_1"] == "# Heading 1", rows.rows
        assert rows.rows["action:bold"] == "**Bold**", rows.rows
        scope = "text.html.markdown markup.heading.1.markdown punctuation.definition.heading.begin.markdown"
        expected = self.view.style_for_scope(scope)["foreground"]
        assert rows.heading_color == expected, (name, rows.heading_color, expected)
        assert self.snapshot() == self.before, (name, "preview mutated source", self.snapshot(), self.before)
        assert self.view.window().find_output_panel(session.tag + "_preview") is None
        assert self.view.window().active_panel() is None
        self.report["picker_appearance"][name] = {
            "scheme": self.view.settings().get("color_scheme"), "style": self.view.style(),
            "heading_punctuation_color": rows.heading_color,
            "expected_heading_punctuation_color": expected,
            "html_sha256": hashlib.sha256(session.html.encode()).hexdigest(),
            "rows": rows.rows, "source_unchanged": True, "preview_panel_removed": True,
        }
        (OUTPUT / ("picker-" + name + ".html")).write_text(session.html, encoding="utf-8")
        self.case("styled picker " + name + " matches actual syntax/scheme and preserves source")

    def start(self):
        try:
            self.view.settings().set("color_scheme", self.DARK)
            self.view.run_command("md_format_picker")
            self.assert_preview("dark")
            self.old_session = self.session()
            self.view.settings().set("color_scheme", self.LIGHT)
            self.later(self.after_view_scheme)
        except Exception:
            self.report.update(passed=False, error=traceback.format_exc())
            self.finish()

    def after_view_scheme(self):
        assert self.session() is self.old_session, "scheme change recreated picker"
        self.assert_preview("light-live")
        self.view.settings().erase("color_scheme")
        self.prefs.set("color_scheme", self.DARK)
        self.later(self.after_global_scheme)

    def after_global_scheme(self):
        self.assert_preview("global-scheme-live")
        self.theme_session = self.session()
        self.theme_render = self.theme_session._render
        self.theme_render_calls = 0

        def count_theme_render():
            self.theme_render_calls += 1
            return self.theme_render()

        self.theme_session._render = count_theme_render
        self.prefs.set("theme", "Adaptive.sublime-theme")
        self.later(self.after_theme)

    def after_theme(self):
        dismissed = not self.view.is_popup_visible()
        self.theme_session._render = self.theme_render
        if dismissed:
            self.view.run_command("md_format_picker")
            self.report["picker_appearance"]["theme_dismissed_by_editor"] = True
        else:
            assert self.theme_render_calls > 0, "theme change did not render the visible picker"
        self.report["picker_theme_refresh"] = {
            "automatic_render_calls": self.theme_render_calls,
            "dismissed_by_editor": dismissed,
        }
        self.assert_preview("theme-changed")
        session = self.session()
        session.navigate("https://example.invalid/not-an-action")
        assert self.snapshot() == self.before
        self.case("styled picker rejects external-looking navigation")
        self.view.hide_popup()
        assert session.closed and self.view.id() not in self.plugin.sublime_picker._SESSIONS
        session.navigate("action:bold")
        assert self.snapshot() == self.before
        self.case("styled picker cancel retires callbacks and stale navigation")
        self.view.settings().set("color_scheme", self.LIGHT)
        self.view.run_command("md_format_picker")
        self.assert_preview("reopened-light")
        self.view.hide_popup()
        self.view.settings().set("markdown_formatting", {
            "labels": {"bold": '<script>Caption & "text"</script>'},
            "styles": {"heading_1": {"color": "#010203"}},
            "custom_formats": [{"label": "Keyboard", "prefix": "<kbd>", "suffix": "</kbd>",
                                "placeholder": "key", "color": "#010203"}],
        })
        self.view.run_command("md_format_picker")
        html = self.session().html
        rows = PickerRows(html)
        assert rows.rows["action:bold"] == '**<script>Caption & "text"</script>**'
        assert rows.rows["custom:0"] == "<kbd>Keyboard</kbd>"
        assert "script" not in rows.tags and "kbd" not in rows.tags and "#010203" not in html
        assert all(key.startswith(("action:", "custom:")) or key == "settings" for key in rows.rows)
        assert self.snapshot() == self.before
        self.case("styled picker safely exports custom labels and ignores legacy colors")
        self.session().navigate("action:bold")
        actual = self.view.substr(sublime.Region(0, self.view.size()))
        assert actual.startswith("**Mouse formatting**\n"), actual
        self.view.run_command("undo")
        assert self.view.substr(sublime.Region(0, self.view.size())) == self.before["text"]
        assert [(r.a, r.b) for r in self.view.sel()] == self.before["selections"]
        self.case("styled picker real navigation edits selection with single undo")
        self.finish()

    def finish(self):
        self.view.hide_popup()
        self.plugin.sublime_picker.close_view(self.view)
        for key, value in self.saved.items():
            if value is None:
                self.prefs.erase(key)
            else:
                self.prefs.set(key, value)
        self.view.settings().set("color_scheme", self.saved_scheme)
        self.view.settings().set("markdown_formatting", {})
        self.report["picker_cleanup"] = {
            "owned_sessions_remaining": len(self.plugin.sublime_picker._SESSIONS),
            "popup_visible": self.view.is_popup_visible(),
        }
        if self.report["picker_cleanup"] != {"owned_sessions_remaining": 0, "popup_visible": False}:
            self.report.update(passed=False, error="Picker cleanup failed")
        write_json("runtime.json", self.report)


class MarkdownFormattingSnapshotCommand(sublime_plugin.WindowCommand):
    def run(self, name="mouse-state.json"):
        view = self.window.active_view()
        write_json(name, {"text": view.substr(sublime.Region(0, view.size())),
                          "selections": [[r.a, r.b] for r in view.sel()],
                          "popup_visible": view.is_popup_visible(),
                          "build": sublime.version()})


def plugin_loaded():
    if os.environ.get("MD_FORMAT_EVIDENCE"):
        sublime.set_timeout(lambda: sublime.active_window().run_command("markdown_formatting_smoke"), 2000)
