# Markdown Formatting for Sublime Text

Select text. Right-click. **Markdown Formatting → Bold**, a heading, a list,
or another format. No shortcuts to memorize and no external tools to install.

Requires **Sublime Text 4** and is tested with build 4215.

## Install

**Package Control:** open the Command Palette, run **Package Control: Install
Package** and choose **MarkdownFormatting**. Updates install automatically.

**Manually:**

1. Download `MarkdownFormatting.sublime-package` from the package website or
   this repository's `dist/` directory. Keep that exact filename.
2. In Sublime Text, choose **Preferences → Browse Packages…**.
3. Go up one directory and open **Installed Packages**. Create it if absent.
4. Copy the archive there **without unzipping it**, then restart Sublime Text.

Then open a `.md` file (syntax: Markdown), select text, and right-click.

Windows data is normally under `%APPDATA%/Sublime Text`, macOS under
`~/Library/Application Support/Sublime Text`, Linux under
`~/.config/sublime-text`. **Browse Packages** also works for portable/custom
installations and is the preferred way to locate the right data directory.

Update a manual install by replacing that same archive and restarting.
Uninstall by removing it (or with **Package Control: Remove Package**);
optionally remove `Packages/User/MarkdownFormatting.sublime-settings`. No
generated menus or extra packages are left behind.

## Everyday formatting

- Headings 1–6; bold, italic, bold + italic; inline code.
- Links, images, fenced code, blockquotes, ordered and unordered lists.
- GFM strikethrough, tables, task lists and checkbox toggling.
- HTML comments and additions via `<ins>…</ins>`.
- MultiMarkdown footnotes; optional CriticMarkup review annotations.
- Multiple selections, useful selected placeholders, single-command undo,
  repeat-last-format, and toggle behavior for supported markers.

The menu follows the active Markdown profile. **GFM** is the default;
**CommonMark** and **MultiMarkdown** are available. CriticMarkup review actions
are enabled by default in a separate **Review** group; they are an annotation
extension, not GitHub Flavored Markdown. Set `enable_critic_markup` to `false`
to disable them. Existing explicit `false` overrides remain respected on update.
On Windows, Sublime may leave an empty submenu heading when all its actions
are hidden; hover-to-open menus are preserved. See the
[native-menu limitation](docs/compatibility.md#empty-submenu-headings-on-windows).
This is a source-editing helper, not a full Markdown parser or renderer.

## Choose your menu

Open **Preferences → Package Settings → Markdown Formatting → Settings**
or run **Markdown Formatting: Settings** from the command palette.

```json
{
    "profile": "gfm",
    "hidden_actions": ["image", "insertion"],
    "labels": {"bold": "Strong emphasis"},
    "picker_order": ["bold", "italic", "heading_2"],
    "custom_formats": [
        {"label": "Highlight (HTML)", "prefix": "<mark>",
         "suffix": "</mark>", "placeholder": "highlighted text"}
    ]
}
```

Hide/show built-ins and rename them in both native menu and pickers.
The native menu retains a compact, predictable grouping. `picker_order`
reorders the pickers, not native menu groups.

**The Styled Picker follows your active color scheme automatically.** Each
clickable row is just a syntax-highlighted example: `# Heading 1`, `**Bold**`,
or `[Link](https://example.com)`. The action name becomes the example text;
there is no separate label followed by `text`. Punctuation and text use
Sublime's Markdown highlighting, including your installed Markdown syntax.
Open pickers refresh when theme/color-scheme settings change; reopening also
uses the current appearance. No manual `styles` configuration is needed.

Sublime's native context menu still uses normal native captions and does not
expose per-item colors/fonts. This package never modifies your color scheme,
document, selection or undo history just to display a preview. Legacy `styles`
and custom-format `color` values are ignored by the Styled Picker.

The searchable chooser is accessible from the same menu and command palette.
Custom templates are available through **Custom Formats…** and both pickers.
No default key bindings are installed. Example bindings, all settings,
project overrides and custom formats: [configuration guide](docs/configuration.md).

## Scope and safety

- By default formatting is restricted to Markdown buffers, and the
  right-click submenu only appears there (on Windows and macOS, Sublime Text
  always shows the submenu heading, with **Settings…** inside). Set `markdown_only` to `false` to
  format elsewhere, including an unsaved Plain Text buffer. Set
  `show_in_context_menu` to `false` to remove the right-click submenu (on
  Windows and macOS every action is removed, but the heading stays with
  **Settings…** inside); all actions stay available from the pickers, the
  Command Palette and your key bindings. Settings are always under
  **Preferences → Package Settings → Markdown Formatting**, even with no file open.
- Commands re-check profile, visibility, read-only state and custom templates
  when executed. Stale picker selections do not edit a changed document.
- Uses only Sublime's API and Python's standard library: no telemetry, network
  access, external programs or extra dependencies.
- Native menu limits and Markdown flavor differences:
  [compatibility](docs/compatibility.md).

## Development

```sh
python3 scripts/build_package.py
python3 scripts/check.py
```

`build_package.py` writes `dist/MarkdownFormatting.sublime-package`; `check.py`
runs the tests and fails if that file is out of date. See
[development](docs/development.md) and [architecture](docs/architecture.md).

MIT licensed; see [LICENSE](LICENSE).
