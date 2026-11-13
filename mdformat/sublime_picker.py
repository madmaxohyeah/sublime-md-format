"""Owned, theme-following popups using Sublime's actual syntax highlighter."""

from itertools import count

import sublime


_MARKDOWN_SYNTAX = "Packages/Markdown/Markdown.sublime-syntax"
_SESSIONS = {}
_SERIAL = count()
# Only these settings can change what an open picker looks like. Any other
# view setting (git gutter, LSP, this package's repeat state...) is ignored,
# so unrelated plugins cannot make the picker recreate preview panels.
_VIEW_APPEARANCE = ("color_scheme", "syntax", "font_face", "font_size")
_GLOBAL_APPEARANCE = ("color_scheme", "theme", "light_color_scheme", "dark_color_scheme",
                      "light_theme", "dark_theme")


class _Session:
    def __init__(self, view, render, on_navigate, location):
        self.view = view
        self.view_id = view.id()
        self.render = render
        self.on_navigate = on_navigate
        self.location = location
        self.tag = "markdown_formatting_picker_{}_{}".format(self.view_id, next(_SERIAL))
        self.watchers = [view.settings(), sublime.load_settings("Preferences.sublime-settings")]
        self.closed = False
        self.pending = False
        self.shown = False
        self.failed_notice = False
        self.html = ""
        self.appearance = None

    def _appearance(self):
        try:
            view, preferences = self.watchers
            return ([view.get(key) for key in _VIEW_APPEARANCE]
                    + [preferences.get(key) for key in _GLOBAL_APPEARANCE])
        except Exception:
            return None  # Unknown state: treat as changed; refresh() rechecks liveness.

    def _live(self):
        return (not self.closed and _SESSIONS.get(self.view_id) is self
                and self.view.is_valid() and self.view.is_popup_visible())

    def _render(self):
        window = self.view.window()
        panel_name = self.tag + "_preview"
        try:
            panel = window.create_output_panel(panel_name, unlisted=True)
            panel.set_scratch(True)
            panel.set_read_only(False)
            panel.settings().set("is_widget", True)
            panel.settings().set("auto_indent", False)
            scheme = self.view.settings().get("color_scheme")
            if scheme is not None:
                panel.settings().set("color_scheme", scheme)
            syntax = self.view.syntax()
            if syntax is None or not syntax.scope.startswith("text.html.markdown"):
                syntax = _MARKDOWN_SYNTAX
            panel.assign_syntax(syntax)

            def highlight(example):
                # A fresh document per row prevents an unfinished custom fence or
                # HTML tag from changing the scopes of subsequent menu entries.
                panel.run_command("select_all")
                panel.run_command("insert", {"characters": example})
                return panel.export_to_html(minihtml=True, enclosing_tags=False,
                                            font_size=False, font_family=False)

            html = self.render(highlight)
            self.failed_notice = False
            return html
        except Exception:
            # Any highlighting failure degrades to escaped plain examples. If
            # that also fails, the caller closes and unregisters the session.
            if not self.failed_notice:
                sublime.status_message(
                    "Markdown Formatting: syntax preview unavailable; showing plain examples.")
                self.failed_notice = True
            return self.render(None)
        finally:
            if window:
                try:
                    window.destroy_output_panel(panel_name)
                except (RuntimeError, ReferenceError):
                    pass  # Closing the window also destroys its output panels.

    def start(self):
        try:
            self.appearance = self._appearance()
            self.html = self._render()
            self.view.show_popup(self.html, location=self.location, max_width=680,
                                 max_height=540, on_navigate=self.navigate,
                                 on_hide=self.close)
            self.shown = True
            if self._live():
                for settings in self.watchers:
                    settings.add_on_change(self.tag, self.settings_changed)
            else:
                self.close()
        except Exception:
            # Never leave a registered, unclosed session behind: a later show()
            # would otherwise hide whatever popup is visible at that time.
            self.close(hide=True)
            sublime.status_message("Markdown Formatting: the picker could not be opened.")

    def navigate(self, target):
        if self._live():
            self.on_navigate(target)

    def settings_changed(self):
        if self.closed:
            return
        appearance = self._appearance()
        if appearance is not None and appearance == self.appearance:
            return
        self.appearance = appearance
        self.request_refresh()

    def request_refresh(self):
        # Settings callbacks may arrive in a burst; all editor work belongs on
        # the UI thread, after the editor has applied the appearance change.
        if not self.closed and not self.pending:
            self.pending = True
            sublime.set_timeout(self.refresh, 75)

    def refresh(self):
        self.pending = False
        try:
            if not self._live():
                self.close()
                return
            html = self._render()
            if self._live():
                self.html = html
                self.view.update_popup(html)
        except Exception:
            self.close(hide=True)
            sublime.status_message("Markdown Formatting: reopen the picker to refresh its appearance.")

    def close(self, hide=False):
        if self.closed:
            return
        self.closed = True
        owned = _SESSIONS.get(self.view_id) is self
        if owned:
            del _SESSIONS[self.view_id]
        for settings in self.watchers:
            try:
                settings.clear_on_change(self.tag)
            except Exception:
                pass  # The source view may already have been destroyed.
        # Only hide a popup this session actually showed; never someone else's.
        if hide and owned and self.shown:
            try:
                if self.view.is_valid():
                    self.view.hide_popup()
            except Exception:
                pass  # The view can disappear between the validity check and hide.


def show(view, render, on_navigate, location):
    """Show a new owned picker; superseded callbacks can never act on it."""
    close_view(view, hide=True)
    session = _Session(view, render, on_navigate, location)
    _SESSIONS[view.id()] = session
    session.start()


def close_view(view, hide=False):
    session = _SESSIONS.get(view.id())
    if session is not None:
        session.close(hide=hide)


def refresh_all():
    """Re-render open pickers unconditionally (e.g. a scheme file was saved)."""
    for session in list(_SESSIONS.values()):
        session.request_refresh()


def close_all():
    for session in list(_SESSIONS.values()):
        session.close(hide=True)
