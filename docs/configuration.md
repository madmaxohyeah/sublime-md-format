# Configuration

Open **Preferences → Package Settings → Markdown Formatting → Settings**.
The left pane is the shipped reference; save overrides in the right pane.
Formatting settings take effect on the next command/menu opening; no restart
is needed. Appearance changes also refresh an already-open Styled Picker.
Settings use JSON (Sublime also accepts comments in your user settings).

## Settings reference

- `profile`: `"gfm"` (default), `"commonmark"`, or `"multimarkdown"`.
- `markdown_only`: `true`. Restricts formatting to `text.html.markdown` syntax.
  The right-click submenu is hidden in other syntaxes (on Windows and macOS only
  its contents are; Sublime Text always shows submenu headings there). Set `false` to enable
  formatting in other syntaxes or Plain Text. Windows may retain empty submenu
  headings; see the [native-menu limitation](compatibility.md#empty-submenu-headings-on-windows).
- `show_in_context_menu`: `true`. Shows the **Markdown Formatting** submenu in
  the right-click menu wherever formatting is available (see `markdown_only`).
  Set `false` to remove it. Linux removes the whole submenu; Windows and macOS
  hide every action, picker, repeat and profile entry but always draw submenu
  headings, so a **Markdown Formatting** heading with **Settings…** (and
  possibly empty group headings) remains. The pickers, Command Palette commands
  and key bindings keep working.
- `hidden_actions`: action IDs to remove from native menu and pickers.
  These actions are also refused when invoked directly.
- `labels`: object mapping action IDs to replacement captions. Plain text only.
- `picker_order`: action IDs to put first in the pickers; unspecified actions
  follow in their normal order. Does not reorder native menu groups.
- `custom_formats`: up to 32 objects with `label`, `prefix`, `suffix` and
  optional `placeholder` (defaults to `"text"`). Labels are at most 120
  characters; each delimiter is at
  most 256 characters and a placeholder at most 120. Literal newlines (`\n`)
  and tabs (`\t`) are supported; any other control character, including a
  carriage return (`\r`), makes the format invalid and it is skipped.
  Wraps selected text (or inserts a placeholder).
  These are literal strings, **not** Sublime snippets, commands or Python.
  Custom formats are your responsibility for renderer compatibility.
- `enable_critic_markup`: `true`. Enables the five CriticMarkup review
  actions, independently of the selected base profile. Set `false` to disable
  them. Explicit user, project or view overrides still take precedence after
  updating; an existing `false` is not overwritten by the new default.
  Windows hides the review actions but may retain their empty submenu heading.
- `select_word_on_empty`: `true`. Inline formatting uses the word at a caret;
  otherwise inserts selected placeholder text. Block actions use whole lines.
- `bullet_marker`: `"-"` (default), `"*"` or `"+"`.
- `emphasis_marker`: `"*"` (default) or `"_"`.
- `strong_marker`: `"**"` (default) or `"__"`.
- `fence_language`: `""` (default), e.g. `"python"` or `"javascript"`.
- `link_url`: `"https://example.com"` (default). Initial URL for links/images;
  edit it after insertion. `""` inserts an empty destination, e.g. `[text]()`.
  The package never opens or fetches URLs.

Malformed fields fall back safely; invalid action IDs are ignored. Settings
do not execute code or install themes.

## Styled Picker appearance

No style setup is necessary. Every action is a single syntax-highlighted
Markdown example with its caption as the sample text: `# Heading 1`,
`**Bold**`, or `- [ ] Task List`. Custom captions replace that sample text.
Marker preferences (`strong_marker`, `bullet_marker`, etc.) are reflected in
the examples. Multi-line constructs remain complete examples: fenced code,
tables, footnotes and horizontal rules may occupy more than one line.

Highlighting comes from Sublime's own syntax engine and the source view's
effective `color_scheme`, not hard-coded colors or manually invented token
styles. The active Markdown syntax is reused; outside Markdown (when allowed),
the built-in Markdown syntax is used for examples. Extensions such as
CriticMarkup receive whatever highlighting that syntax and scheme provide;
the picker does not invent unsupported highlighting.

Changing the theme or color scheme refreshes a visible picker automatically.
Saved `.sublime-color-scheme`, `.tmTheme` and `.sublime-theme` files also request
a refresh. If Sublime dismisses the popup while opening another chooser, the
next opening uses the new appearance; a closed picker is never reopened.
The package does not change the editor's theme, preferences, document or undo
history. If the editor cannot export a syntax preview, a status message reports
the failure and safe plain examples remain usable.

Older `styles` objects and custom-format `color` fields are accepted as legacy
settings but are ignored (never an error). They can be removed; editing them
does not invalidate **Repeat Last Format** or an open picker. For a custom
wrapper, `label` supplies the preview text; `placeholder` still controls what
is inserted at an empty caret. The native and Searchable Pickers retain their
normal captions and behavior.

## Action IDs

Headings: `heading_1`, `heading_2`, `heading_3`, `heading_4`, `heading_5`, `heading_6`.

Inline: `bold`, `italic`, `bold_italic`, `strikethrough`, `inline_code`.

Blocks and links: `fenced_code`, `link`, `image`, `blockquote`,
`unordered_list`, `ordered_list`, `task_list`, `toggle_task`,
`horizontal_rule`, `table`.

Annotations: `html_comment`, `insertion`, `footnote`, `critic_addition`,
`critic_deletion`, `critic_substitution`, `critic_highlight`, `critic_comment`.

Profile-unavailable actions stay unavailable even when listed in `picker_order`.

## Per-project and per-view overrides

Place this in a `.sublime-project` file, merging it into existing settings:

```json
{
    "folders": [{"path": "."}],
    "settings": {
        "markdown_formatting": {
            "profile": "commonmark",
            "hidden_actions": ["image"],
            "strong_marker": "**"
        }
    }
}
```

Precedence, lowest to highest:

1. package settings (`MarkdownFormatting.sublime-settings`, default and user);
2. the project's `settings.markdown_formatting` object;
3. a `markdown_formatting` object found through the view's own settings. Sublime
   resolves that key per view, so it is the highest of: a value set on the view
   itself, a syntax-specific settings file (e.g. `Markdown.sublime-settings`),
   the project, or `Preferences.sublime-settings`. Whichever layer defines it
   supplies the whole object;
4. the per-view profile choice made with **Markdown profile: …** (context menu)
   or **Select Profile** (command palette).

Each layer is validated before it is applied: malformed fields keep the last
valid lower-layer value. Nested objects and arrays replace the corresponding
field; they are not recursively merged. Explicit `[]` or `{}` clears a field,
while a nonempty container with no valid entries is ignored rather than
silently clearing it.

The profile chooser changes only the current view: it stores the choice under
its own view setting (`markdown_formatting_profile`) and never copies project or
global settings into the view, so later project edits keep applying. Choose
**Default (from settings)** to drop the per-view choice. Use settings for a
durable default. Existing Markdown is not converted when profiles change.

For view-specific settings from Sublime's console:

```python
view.settings().set("markdown_formatting", {"profile": "multimarkdown"})
```

## Optional keyboard bindings

There are no installed bindings, avoiding conflicts. Add chosen entries via
**Preferences → Key Bindings**:

```json
[
    {"keys": ["ctrl+alt+m"], "command": "md_format_picker", "args": {"mode": "search"}},
    {"keys": ["ctrl+alt+b"], "command": "md_format", "args": {"action": "bold"}},
    {"keys": ["ctrl+alt+r"], "command": "md_format_repeat"}
]
```

Use `super` for the Command key on macOS if desired. Each formatting command
checks the same restrictions as the menu. **Repeat last format** is per-view;
a changed/deleted custom template invalidates the stored repeat action.

## Native menu styling and advanced layout

Sublime's native menu API has captions and groups but no per-item foreground,
font or CSS control. The Styled Picker is the intentionally small alternative
when visual emphasis is useful. This package never edits your color scheme.

Advanced users may add their own `Packages/User/Context.sublime-menu` entries
using `md_format` and the IDs above. To move an item rather than duplicate it,
you can override this package's resource at
`Packages/MarkdownFormatting/Context.sublime-menu`; keep that override in sync
with future releases, and remove it when uninstalling. Normal customization
should use settings and does not require resource overrides.
