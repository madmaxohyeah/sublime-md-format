"""Safe, example-only minihtml for the Markdown Formatting picker."""

from html import escape

from .catalog import (
    ACTIONS, available_actions, custom_formats, label_for, profile_name, resolve_settings,
)
from .engine import format_document

_CSS = """
<style>
html, body {
    margin: 0;
    padding: 0;
    color: var(--foreground);
    background-color: var(--background);
}
body {
    padding: 0.75rem;
}
h1 {
    margin: 0 0 0.25rem 0;
    font-size: 1.15rem;
}
h2 {
    margin: 0.8rem 0 0.2rem 0;
    font-size: 0.9rem;
}
.profile {
    color: var(--foreground);
    font-size: 0.82rem;
}
a {
    color: inherit;
    text-decoration: none;
}
.action {
    display: block;
    padding: 0.28rem 0.4rem;
    font-family: monospace;
    font-size: 0.95rem;
}
.footer {
    margin-top: 0.9rem;
    padding-top: 0.4rem;
}
.settings {
    font-size: 0.85rem;
}
</style>
""".strip()


def _example(action, settings):
    """Use the real formatter and preferences, with a label as example content."""
    label = label_for(action, settings)
    if action == "table":
        # Tables are not toggles; keep their separator width tied to the caption.
        return format_document(label, [(0, len(label))], action, settings).text

    # Prevent a caption such as **Bold** from being interpreted as a request to
    # remove existing formatting. This marker must not collide with any input.
    guard = "MDFORMATPREVIEWGUARD"
    while guard in str(settings) or guard in label:
        guard += "x"
    seed = guard + label + guard
    if action == "toggle_task":
        seed = settings["bullet_marker"] + " [ ] " + seed
    result = format_document(seed, [(0, len(seed))], action, settings).text
    padding = ""
    if action == "inline_code" and (
        label.startswith("`") or label.endswith("`")
        or (label.strip(" ") and (label.startswith(" ") or label.endswith(" ")))
    ):
        # Removing the neutral guards restores the code-span boundary padding.
        padding = " "
    return result.replace(guard, padding)


def _row(target, example, highlight):
    # Only a trusted editor exporter may supply HTML. Configured text never may.
    if highlight is None:
        content = escape(example, quote=True).replace("\n", "<br>")
    else:
        content = highlight(example)
        if not isinstance(content, str) or not content:
            raise ValueError("The syntax highlighter returned no minihtml")
    return '<a class="action" href="{}">{}</a>'.format(target, content)


def render_picker(settings, custom_only=False, highlight=None):
    """Render internal links, optionally using a trusted syntax-to-minihtml callable."""
    resolved = resolve_settings(settings)
    templates = custom_formats(resolved)
    title = "Custom Formats" if custom_only else "Markdown Formatting"
    parts = [_CSS, "<body>", "<h1>{}</h1>".format(title)]

    if not custom_only:
        profile = escape(profile_name(resolved["profile"]), quote=True)
        parts.append('<div class="profile">Profile: {}</div>'.format(profile))
        previous_group = None
        for action in available_actions(resolved):
            group = ACTIONS[action]["group"]
            if group != previous_group:
                parts.append("<h2>{}</h2>".format(escape(group, quote=True)))
                previous_group = group
            parts.append(_row("action:" + action, _example(action, resolved), highlight))

    if templates:
        parts.append("<h2>Custom Formats</h2>")
        for index, item in enumerate(templates):
            example = item["prefix"] + item["label"] + item["suffix"]
            parts.append(_row("custom:{}".format(index), example, highlight))

    parts.append(
        '<div class="footer"><a class="settings" href="settings">Settings…</a></div>'
    )
    parts.append("</body>")
    return "\n".join(parts)
