"""Validated action metadata and user-facing settings for Markdown Formatting."""

import re
from collections import OrderedDict
from collections.abc import Mapping


# The single source of profile IDs and their display names, in chooser order.
PROFILE_NAMES = OrderedDict(
    [
        ("gfm", "GitHub Flavored Markdown"),
        ("commonmark", "CommonMark"),
        ("multimarkdown", "MultiMarkdown"),
    ]
)
# A tuple, not the mapping: membership tests on malformed (unhashable) user
# values must compare, never raise TypeError.
PROFILES = tuple(PROFILE_NAMES)
_ALL_PROFILES = PROFILES
_GFM_ONLY = ("gfm",)
_GFM_AND_MMD = ("gfm", "multimarkdown")
_MMD_ONLY = ("multimarkdown",)


ACTIONS = OrderedDict(
    [
        (
            "heading_1",
            {
                "label": "Heading 1",
                "group": "Headings",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "heading_2",
            {
                "label": "Heading 2",
                "group": "Headings",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "heading_3",
            {
                "label": "Heading 3",
                "group": "Headings",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "heading_4",
            {
                "label": "Heading 4",
                "group": "Headings",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "heading_5",
            {
                "label": "Heading 5",
                "group": "Headings",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "heading_6",
            {
                "label": "Heading 6",
                "group": "Headings",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "bold",
            {
                "label": "Bold",
                "group": "Inline",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "italic",
            {
                "label": "Italic",
                "group": "Inline",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "bold_italic",
            {
                "label": "Bold + Italic",
                "group": "Inline",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "strikethrough",
            {
                "label": "Strikethrough",
                "group": "Inline",
                "profiles": _GFM_ONLY,
            },
        ),
        (
            "inline_code",
            {
                "label": "Inline Code",
                "group": "Inline",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "fenced_code",
            {
                "label": "Fenced Code Block",
                "group": "Insert",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "link",
            {
                "label": "Link",
                "group": "Insert",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "image",
            {
                "label": "Image",
                "group": "Insert",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "blockquote",
            {
                "label": "Blockquote",
                "group": "Insert",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "unordered_list",
            {
                "label": "Unordered List",
                "group": "Lists",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "ordered_list",
            {
                "label": "Ordered List",
                "group": "Lists",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "task_list",
            {
                "label": "Task List",
                "group": "Lists",
                "profiles": _GFM_ONLY,
            },
        ),
        (
            "toggle_task",
            {
                "label": "Toggle Task",
                "group": "Lists",
                "profiles": _GFM_ONLY,
            },
        ),
        (
            "horizontal_rule",
            {
                "label": "Horizontal Rule",
                "group": "Insert",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "table",
            {
                "label": "Table",
                "group": "Insert",
                "profiles": _GFM_AND_MMD,
            },
        ),
        (
            "html_comment",
            {
                "label": "HTML Comment",
                "group": "Insert",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "insertion",
            {
                "label": "Insertion",
                "group": "Insert",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "footnote",
            {
                "label": "Footnote",
                "group": "Insert",
                "profiles": _MMD_ONLY,
            },
        ),
        (
            "critic_addition",
            {
                "label": "Critic Addition",
                "group": "Review",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "critic_deletion",
            {
                "label": "Critic Deletion",
                "group": "Review",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "critic_substitution",
            {
                "label": "Critic Substitution",
                "group": "Review",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "critic_highlight",
            {
                "label": "Critic Highlight",
                "group": "Review",
                "profiles": _ALL_PROFILES,
            },
        ),
        (
            "critic_comment",
            {
                "label": "Critic Comment",
                "group": "Review",
                "profiles": _ALL_PROFILES,
            },
        ),
    ]
)


CRITIC_ACTIONS = frozenset(
    (
        "critic_addition",
        "critic_deletion",
        "critic_substitution",
        "critic_highlight",
        "critic_comment",
    )
)

MAX_LABEL_LENGTH = 120
MAX_CUSTOM_FORMATS = 32
MAX_TEMPLATE_LENGTH = 256
MAX_PLACEHOLDER_LENGTH = 120
MAX_FENCE_LANGUAGE_LENGTH = 64
MAX_LINK_URL_LENGTH = 2048

_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\Z")
_FENCE_LANGUAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,63}\Z")


def _fresh_defaults():
    return {
        "profile": "gfm",
        "markdown_only": True,
        "show_in_context_menu": True,
        "hidden_actions": [],
        "labels": {},
        "picker_order": [],
        "styles": {},
        "custom_formats": [],
        "enable_critic_markup": True,
        "select_word_on_empty": True,
        "bullet_marker": "-",
        "emphasis_marker": "*",
        "strong_marker": "**",
        "fence_language": "",
        "link_url": "https://example.com",
    }


def _clean_text(value, maximum, allow_empty=False, allow_newlines=False):
    """Return value if it is bounded plain text, else None.

    With allow_newlines only LF and tab are admitted as control characters:
    Sublime buffers always use LF, so a literal CR would show as <0x0d>.
    """
    if not isinstance(value, str) or len(value) > maximum:
        return None
    if not allow_empty and not value:
        return None
    for character in value:
        codepoint = ord(character)
        if codepoint == 127 or codepoint < 32:
            if allow_newlines and character in "\t\n":
                continue
            return None
    return value


def _validated_action_list(value):
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    seen = set()
    for action in value:
        if not isinstance(action, str):
            continue
        if action in ACTIONS and action not in seen:
            result.append(action)
            seen.add(action)
    return result


def _validated_labels(value):
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for action, label in value.items():
        if action not in ACTIONS:
            continue
        clean = _clean_text(label, MAX_LABEL_LENGTH)
        if clean is not None:
            result[action] = clean
    return result


def _validated_styles(value):
    # Legacy and unused by the package: the Styled Picker follows the color
    # scheme. Still validated field by field so old settings stay harmless and
    # resolved settings keep exposing a well-formed value.
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for action, candidate in value.items():
        if action not in ACTIONS or not isinstance(candidate, Mapping):
            continue
        style = {}
        color = candidate.get("color")
        if isinstance(color, str) and _COLOR_RE.fullmatch(color):
            style["color"] = color
        for name in ("bold", "italic"):
            flag = candidate.get(name)
            if type(flag) is bool:
                style[name] = flag
        if style:
            result[action] = style
    return result


def _validated_custom_formats(value):
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for candidate in value:
        if len(result) >= MAX_CUSTOM_FORMATS:
            break
        if not isinstance(candidate, Mapping):
            continue
        label = _clean_text(candidate.get("label"), MAX_LABEL_LENGTH)
        prefix = _clean_text(
            candidate.get("prefix"),
            MAX_TEMPLATE_LENGTH,
            allow_empty=True,
            allow_newlines=True,
        )
        suffix = _clean_text(
            candidate.get("suffix"),
            MAX_TEMPLATE_LENGTH,
            allow_empty=True,
            allow_newlines=True,
        )
        placeholder = _clean_text(
            candidate.get("placeholder", "text"),
            MAX_PLACEHOLDER_LENGTH,
            allow_empty=True,
            allow_newlines=True,
        )
        if None in (label, prefix, suffix, placeholder):
            continue
        if not prefix and not suffix:
            continue
        # A legacy "color" (like any other extra key) is ignored, never an
        # error, and stays out of the template identity that repeat and the
        # pickers compare.
        result.append(
            {
                "label": label,
                "prefix": prefix,
                "suffix": suffix,
                "placeholder": placeholder,
            }
        )
    return result


def _validated_settings_fields(raw):
    """Return present fields with usable values, including explicit empty resets."""

    if not isinstance(raw, Mapping):
        return {}

    settings = {}

    profile = raw.get("profile")
    if profile in PROFILES:
        settings["profile"] = profile

    for name in ("markdown_only", "show_in_context_menu", "enable_critic_markup", "select_word_on_empty"):
        value = raw.get(name)
        if type(value) is bool:
            settings[name] = value

    for name, kinds, validate in (
        ("hidden_actions", (list, tuple), _validated_action_list),
        ("picker_order", (list, tuple), _validated_action_list),
        ("labels", (Mapping,), _validated_labels),
        ("styles", (Mapping,), _validated_styles),
        ("custom_formats", (list, tuple), _validated_custom_formats),
    ):
        value = raw.get(name)
        if isinstance(value, kinds):
            admitted = validate(value)
            # An explicit empty value clears a field. A nonempty container
            # with no usable entries is malformed, not an implicit reset.
            if not value or admitted:
                settings[name] = admitted

    bullet_marker = raw.get("bullet_marker")
    if bullet_marker in ("-", "*", "+") and isinstance(bullet_marker, str):
        settings["bullet_marker"] = bullet_marker

    emphasis_marker = raw.get("emphasis_marker")
    if emphasis_marker in ("*", "_") and isinstance(emphasis_marker, str):
        settings["emphasis_marker"] = emphasis_marker

    strong_marker = raw.get("strong_marker")
    if strong_marker in ("**", "__") and isinstance(strong_marker, str):
        settings["strong_marker"] = strong_marker

    fence_language = raw.get("fence_language")
    if fence_language == "":
        settings["fence_language"] = ""
    elif (
        isinstance(fence_language, str)
        and len(fence_language) <= MAX_FENCE_LANGUAGE_LENGTH
        and _FENCE_LANGUAGE_RE.fullmatch(fence_language)
    ):
        settings["fence_language"] = fence_language

    # "" is a valid destination, like an empty fence_language: [text]().
    link_url = _clean_text(raw.get("link_url"), MAX_LINK_URL_LENGTH, allow_empty=True)
    if link_url is not None:
        settings["link_url"] = link_url

    return settings


def resolve_settings(raw):
    """Return a fresh, fully validated settings dictionary.

    Invalid fields fall back independently, so one malformed project or view
    override cannot discard otherwise valid preferences.
    """

    settings = _fresh_defaults()
    settings.update(_validated_settings_fields(raw))
    return settings


def merge_settings(base, override):
    """Replace base fields only when an override explicitly supplies a valid value."""

    settings = resolve_settings(base)
    settings.update(_validated_settings_fields(override))
    return settings


def profile_name(profile):
    """Return the display name of a profile ID (the ID itself if unknown)."""

    if isinstance(profile, str) and profile in PROFILES:
        return PROFILE_NAMES[profile]
    return str(profile)


def available_actions(settings):
    """Return enabled built-in action IDs in configured picker order."""

    resolved = resolve_settings(settings)
    profile = resolved["profile"]
    hidden = set(resolved["hidden_actions"])
    enabled = []
    for action, metadata in ACTIONS.items():
        if profile not in metadata["profiles"] or action in hidden:
            continue
        if action in CRITIC_ACTIONS and not resolved["enable_critic_markup"]:
            continue
        enabled.append(action)

    enabled_set = set(enabled)
    ordered = [
        action for action in resolved["picker_order"] if action in enabled_set
    ]
    ordered_set = set(ordered)
    ordered.extend(action for action in enabled if action not in ordered_set)
    return ordered


def label_for(action, settings):
    """Return the validated custom label or the catalog label for an action."""

    if action not in ACTIONS:
        raise KeyError(action)
    resolved = resolve_settings(settings)
    return resolved["labels"].get(action, ACTIONS[action]["label"])


def custom_formats(settings):
    """Return safe custom wrappers only; never commands, snippets or extra keys."""

    if not isinstance(settings, Mapping):
        return []
    return _validated_custom_formats(settings.get("custom_formats"))
