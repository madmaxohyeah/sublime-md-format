# Architecture

## Modules

- `markdown_formatting.py`: the Sublime commands, settings layering, menu visibility, picker callbacks, Repeat Last Format, and applying edits.
- `mdformat/engine.py`: the formatting itself, as pure functions on text and selections. It returns sorted, non-overlapping replacements plus the new selections, so it can be tested without Sublime.
- `mdformat/catalog.py`: the list of actions, which profile offers which action, and settings validation. Menus, pickers and commands all read from it.
- `mdformat/picker.py`: builds the Styled Picker's minihtml from examples produced by the real engine.
- `mdformat/sublime_picker.py`: shows the Styled Picker and redraws it when the theme or color scheme changes. Each example is highlighted by rendering it in a hidden scratch panel with the Markdown syntax and the view's color scheme, then exporting it with `export_to_html`. The panel is removed after every render.
- `Context.sublime-menu`: a static menu. Captions come from the command descriptions (so `labels` can rename them) and visibility from the catalog.

## Context menu and Command Palette

Every context menu entry passes `"context": true`. The commands accept a `context` argument, and when it is true they are also hidden if `show_in_context_menu` is false. The Command Palette, key bindings, pickers and Repeat Last Format never pass it, so turning off the context menu doesn't affect them. `context` only decides where an entry shows up; `run` always re-checks whether the action is available.

Submenus use the `md_format_menu` command for their visibility. Linux respects it; Windows and macOS always draw submenu headings. That's why the root submenu always contains **Settings…** and is never empty. `md_format_settings` is a WindowCommand, so Settings also opens from the main menu and the Command Palette when no file is open.

Settings are layered: package settings, then the project's `markdown_formatting` object, then a `markdown_formatting` object found through the view's settings, then the profile chosen for the view (`markdown_formatting_profile`).

## Applying edits

The adapter plans the whole operation first and then applies the replacements from right to left in a single TextCommand, so one undo reverts it. It never replaces the whole document to change a word. Read-only state, syntax, profile and action availability are checked again when the command runs.

## Design decisions

- **No dependencies.** Only Sublime's API and the Python standard library: no Markdown renderer, external processes or network access.
- **Static menu, dynamic visibility.** Hiding an action never generates menu files, so uninstalling leaves nothing behind. Custom formats live in a picker for the same reason.
- **Profiles only filter.** CommonMark, GFM and MultiMarkdown decide which actions are offered. They don't convert existing Markdown.
- **Callbacks are tied to a document.** A picker remembers its view, change count and selection, and does nothing if any of them changed. Closing or replacing a picker, closing the view or unloading the plugin cancels its callbacks.
- **Settings are data.** Custom formats are literal text and can't run commands, labels are escaped, and the picker never opens external links.
- **Reproducible package.** `scripts/build_package.py` has an explicit file list and fixed archive metadata, and the same archive is committed in `dist/` and released.
- **Python host.** `.python-version` contains `3.8`, which selects the modern plugin host both before and after Sublime's switch to Python 3.14.
