"""Mouse-first Markdown editing. No network, subprocesses or generated menu files.

Menu versus palette visibility contract:

- Every Context.sublime-menu leaf passes the menu-only argument
  ``"context": true``. Such an entry is hidden when ``show_in_context_menu``
  is false, in addition to the ordinary checks (syntax, profile, hidden
  actions, read-only state).
- The Command Palette, key bindings, the pickers and repeat never pass
  ``context``, so the context-menu opt-out never hides or blocks them.
- Submenu parents (``md_format_menu``) carry the same checks. Linux honors
  them; Windows and macOS always show submenu headings, which is why the
  ``md_format_settings`` leaf has no ``context`` flag and stays visible.
- ``context`` only changes where an entry is shown, never what it does;
  ``run`` re-checks availability for every caller.
"""

import sublime
import sublime_plugin

from .mdformat.catalog import (
    ACTIONS, PROFILE_NAMES, PROFILES, available_actions, custom_formats, label_for,
    merge_settings, profile_name, resolve_settings,
)
from .mdformat.engine import format_document
from .mdformat.picker import render_picker
from .mdformat import sublime_picker

SETTINGS_FILE = "MarkdownFormatting.sublime-settings"
LAST_ACTION_KEY = "markdown_formatting_last_action"
# The per-view profile choice is stored on its own so that the merged settings
# dictionary is never written back into (and frozen in) the view.
PROFILE_KEY = "markdown_formatting_profile"
# A new user settings file must not pin any value: defaults keep following
# the package.
USER_SETTINGS_TEMPLATE = (
    "// Markdown Formatting user settings: copy only the options you want to\n"
    "// change from the left pane. Everything else keeps its default.\n"
    "{\n\t$0\n}\n"
)


def _layered_settings(view):
    """Resolve package < project < view/syntax-specific settings."""
    settings = sublime.load_settings(SETTINGS_FILE)
    raw = {key: settings.get(key, value) for key, value in resolve_settings({}).items()}
    resolved = resolve_settings(raw)
    window = view.window()
    project = window.project_data() if window else None
    if isinstance(project, dict) and isinstance(project.get("settings"), dict):
        override = project["settings"].get("markdown_formatting")
        if isinstance(override, dict):
            resolved = merge_settings(resolved, override)
    # View settings fall back through syntax-specific, project and Preferences
    # settings; the highest layer that defines the key wins as a whole.
    override = view.settings().get("markdown_formatting")
    if isinstance(override, dict):
        resolved = merge_settings(resolved, override)
    return resolved


def settings_for(view):
    """Apply package < project < view/syntax < per-view profile choice.

    Every layer is validated; malformed values never raise.
    """
    resolved = _layered_settings(view)
    choice = view.settings().get(PROFILE_KEY)
    if isinstance(choice, str) and choice in PROFILES:
        resolved["profile"] = choice
    return resolved


def eligible(view, settings):
    """Return whether formatting is available in this view at all.

    Checks a valid view and, with ``markdown_only``, a Markdown scope. It is
    evaluated for visibility and again at execution, including palette calls.
    """
    return bool(view.is_valid() and (
        not settings["markdown_only"] or view.match_selector(0, "text.html.markdown")
    ))


def action_options(action, settings, custom_index=None):
    """Return engine options for an available action, or None if refused.

    Built-ins must be enabled by profile, ``hidden_actions`` and the
    CriticMarkup switch. ``"custom"`` requires an integer index of a currently
    configured custom format, whose template is merged into the options.
    """
    if action == "custom":
        choices = custom_formats(settings)
        if type(custom_index) is not int or not 0 <= custom_index < len(choices):
            return None
        options = dict(settings)
        options.update(choices[custom_index])
        return options
    if action not in available_actions(settings):
        return None
    return settings


def _context_hidden(settings, context):
    """A context-menu entry is hidden when the user opted out of the menu."""
    return bool(context) and not settings["show_in_context_menu"]


class MdFormatMenuCommand(sublime_plugin.TextCommand):
    """Submenu parent of the context menu; ``group`` names a catalog group."""

    def run(self, edit, group=None):
        pass

    def is_visible(self, group=None):
        settings = settings_for(self.view)
        # Package Control review guidelines: context-menu entries should be
        # conditional and configurable. Linux honors this check; Windows and
        # macOS always show submenu headings, so Settings... stays visible inside.
        if not settings["show_in_context_menu"] or not eligible(self.view, settings):
            return False
        if group is None:
            return True
        return any(ACTIONS[action]["group"] == group for action in available_actions(settings)) or (
            group == "Insert" and bool(custom_formats(settings))
        )

    def is_enabled(self, group=None):
        return True


class MdFormatCommand(sublime_plugin.TextCommand):
    """Apply a built-in action, or a custom format by index, to all selections.

    ``context`` is the menu-only flag described in the module docstring.
    """

    def run(self, edit, action="bold", custom_index=None, context=False):
        settings = settings_for(self.view)
        options = action_options(action, settings, custom_index)
        if not eligible(self.view, settings) or self.view.is_read_only() or options is None:
            sublime.status_message("Markdown Formatting: this format is unavailable here.")
            return
        text = self.view.substr(sublime.Region(0, self.view.size()))
        selections = [(region.a, region.b) for region in self.view.sel()]
        try:
            result = format_document(text, selections, action, options)
        except ValueError as error:
            # Engine validation messages never contain document text.
            sublime.status_message("Markdown Formatting: {}".format(error))
            return
        except Exception as error:
            # An internal error must leave the buffer untouched and must not
            # put document text into the console or status bar.
            print("Markdown Formatting: {} while applying {!r}; nothing was changed.".format(
                type(error).__name__, action))
            sublime.status_message("Markdown Formatting: formatting failed; nothing was changed.")
            return
        for replacement in reversed(result.edits):
            self.view.replace(edit, sublime.Region(replacement.start, replacement.end), replacement.text)
        if result.selections:
            self.view.sel().clear()
            for a, b in result.selections:
                self.view.sel().add(sublime.Region(a, b))
            self.view.show(self.view.sel()[0])
        if result.edits:
            last = {"action": action}
            if action == "custom":
                last["custom_index"] = custom_index
                # Refuse stale repeat if settings later reorder or change templates.
                last["template"] = custom_formats(settings)[custom_index]
            self.view.settings().set(LAST_ACTION_KEY, last)

    def is_visible(self, action="bold", custom_index=None, context=False):
        settings = settings_for(self.view)
        return (eligible(self.view, settings) and not _context_hidden(settings, context)
                and action_options(action, settings, custom_index) is not None)

    def is_enabled(self, action="bold", custom_index=None, context=False):
        return not self.view.is_read_only() and self.is_visible(action, custom_index, context)

    def description(self, action="bold", custom_index=None, context=False):
        settings = settings_for(self.view)
        if action == "custom":
            options = action_options(action, settings, custom_index)
            return options["label"] if options else "Custom format"
        return label_for(action, settings) if action in ACTIONS else "Markdown Formatting"


class MdFormatRepeatCommand(sublime_plugin.TextCommand):
    """Re-run this view's last successful format, if it is still available."""

    def _last(self, settings):
        last = self.view.settings().get(LAST_ACTION_KEY)
        if not isinstance(last, dict) or not isinstance(last.get("action"), str):
            return None
        options = action_options(last["action"], settings, last.get("custom_index"))
        if options is None:
            return None
        if last["action"] == "custom":
            if custom_formats(settings)[last["custom_index"]] != last.get("template"):
                return None
        return {key: last[key] for key in ("action", "custom_index") if key in last}

    def run(self, edit, context=False):
        settings = settings_for(self.view)
        if self.view.is_read_only() or not eligible(self.view, settings):
            return
        last = self._last(settings)
        if last:
            self.view.run_command("md_format", last)

    def is_enabled(self, context=False):
        if self.view.is_read_only():
            return False
        settings = settings_for(self.view)
        return bool(eligible(self.view, settings) and not _context_hidden(settings, context)
                    and self._last(settings))

    def is_visible(self, context=False):
        settings = settings_for(self.view)
        return eligible(self.view, settings) and not _context_hidden(settings, context)


class MdFormatPickerCommand(sublime_plugin.TextCommand):
    """Open the searchable (``mode="search"``) or styled chooser for this view.

    ``custom_only`` limits it to custom formats. Choices are bound to the
    current document state and refused once it changes.
    """

    def run(self, edit, mode="styled", custom_only=False, context=False):
        view = self.view
        settings = settings_for(view)
        if not eligible(view, settings) or view.is_read_only() or not view.window():
            return
        choices = []
        if not custom_only:
            choices.extend((label_for(action, settings), {"action": action})
                           for action in available_actions(settings))
        templates = custom_formats(settings)
        choices.extend((item["label"], {"action": "custom", "custom_index": index})
                       for index, item in enumerate(templates))
        if not choices:
            sublime.status_message("Markdown Formatting: no formats enabled. Open package settings to add some.")
            return
        count = view.change_count()
        regions = [(r.a, r.b) for r in view.sel()]
        consumed = [False]

        def apply(args):
            if consumed[0]:
                return
            if not view.is_valid() or view.change_count() != count or [(r.a, r.b) for r in view.sel()] != regions:
                sublime.status_message("Markdown Formatting: selection changed; reopen the picker.")
                return
            if args.get("action") == "custom" and custom_formats(settings_for(view)) != templates:
                sublime.status_message("Markdown Formatting: custom formats changed; reopen the picker.")
                return
            consumed[0] = True
            view.hide_popup()
            view.run_command("md_format", args)

        if mode == "search":
            def on_done(index):
                if 0 <= index < len(choices):
                    apply(choices[index][1])
            view.window().show_quick_panel([label for label, _ in choices], on_done)
            return

        targets = {"action:" + args["action"]: args for _, args in choices if args["action"] != "custom"}
        targets.update({"custom:" + str(args["custom_index"]): args
                        for _, args in choices if args["action"] == "custom"})

        def on_navigate(target):
            if target == "settings":
                if not view.is_valid():
                    return
                window = view.window()
                view.hide_popup()
                if window:
                    window.run_command("md_format_settings")
            elif target in targets:
                apply(targets[target])

        location = view.sel()[0].begin() if view.sel() else -1
        sublime_picker.show(
            view, lambda highlight: render_picker(settings, custom_only=custom_only,
                                                   highlight=highlight),
            on_navigate, location,
        )

    def is_visible(self, mode="styled", custom_only=False, context=False):
        settings = settings_for(self.view)
        return (eligible(self.view, settings) and not _context_hidden(settings, context)
                and (not custom_only or bool(custom_formats(settings))))

    def is_enabled(self, mode="styled", custom_only=False, context=False):
        return not self.view.is_read_only() and self.is_visible(mode, custom_only, context)


class MdFormatPickerListener(sublime_plugin.EventListener):
    """Retire pickers of closed views; refresh them when scheme files are saved."""

    def on_close(self, view):
        sublime_picker.close_view(view)

    def on_post_save(self, view):
        filename = view.file_name() or ""
        if filename.endswith((".sublime-color-scheme", ".tmTheme", ".sublime-theme")):
            sublime_picker.refresh_all()


def plugin_unloaded():
    sublime_picker.close_all()


class MdFormatProfileCommand(sublime_plugin.TextCommand):
    """Choose the Markdown profile for this view only, or return to settings.

    The choice is stored under ``PROFILE_KEY`` and applied last; project and
    global settings keep applying to everything else.
    """

    def run(self, edit, context=False):
        view = self.view
        window = view.window()
        if not window:
            return
        current = settings_for(view)["profile"]
        default = _layered_settings(view)["profile"]
        profiles = list(PROFILE_NAMES.items())
        items = [name + (" (current)" if value == current else "") for value, name in profiles]
        items.append("Default (from settings): {}".format(profile_name(default)))
        selected = [value for value, _ in profiles].index(current)

        def choose(index):
            if not view.is_valid():
                return
            if 0 <= index < len(profiles):
                view.settings().set(PROFILE_KEY, profiles[index][0])
                sublime.status_message("Markdown Formatting: {} (this view).".format(profiles[index][1]))
            elif index == len(profiles):
                view.settings().erase(PROFILE_KEY)
                sublime.status_message("Markdown Formatting: {} (from settings).".format(
                    profile_name(_layered_settings(view)["profile"])))
        window.show_quick_panel(items, choose, selected_index=selected)

    def is_visible(self, context=False):
        settings = settings_for(self.view)
        return eligible(self.view, settings) and not _context_hidden(settings, context)

    def description(self, context=False):
        return "Markdown profile: {}…".format(profile_name(settings_for(self.view)["profile"]))


class MdFormatSettingsCommand(sublime_plugin.WindowCommand):
    """Open the package settings beside the user's overrides.

    A WindowCommand, so it works from the main menu and the Command Palette
    even when no file is open. Always visible in the context menu.
    """

    def run(self):
        package = __package__.split(".")[0]
        self.window.run_command("edit_settings", {
            "base_file": "${packages}/" + package + "/" + SETTINGS_FILE,
            "default": USER_SETTINGS_TEMPLATE,
        })
