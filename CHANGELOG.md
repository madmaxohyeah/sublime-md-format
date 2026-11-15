# Changelog

## 1.0.1 — 2026-11-15

- The README explains how to remove or customize the right-click menu by
  replacing the package's `Context.sublime-menu`.
- The Command Palette entry for the settings is now called **Preferences:
  Markdown Formatting Settings**, like in most packages. It and the main menu
  entry now use Sublime's standard `edit_settings` command.

## 1.0.0 — 2026-11-13

First public release.

- Headings, bold, italic, strikethrough, code, links, images, quotes, lists,
  task lists, tables, footnotes, HTML comments and insertions, and
  CriticMarkup review annotations, from the right-click menu, two pickers
  (searchable and styled) and the Command Palette.
- Toggles: applying a format again removes it. Works with multiple selections,
  and every action is a single undo step.
- GFM, CommonMark and MultiMarkdown profiles decide which actions are offered.
- Settings to hide, rename and reorder actions, add custom formats, choose
  markers and hide the context menu. No default key bindings.
