"""Pure-Python Markdown formatting engine used by the Sublime Text adapter.

``format_document(text, selections, action, options)`` never mutates anything.
It returns a :class:`FormatResult` holding the new text, one selection per
input selection (same order and direction) and the minimal, sorted,
non-overlapping :class:`Replacement` edits that turn ``text`` into the result.

Planning model
--------------
Selections are first grouped: inline actions group overlapping selections
(carets expand to the word under them), block actions group selections by
contiguous runs of touched lines.  Each group yields one ``_Operation``: a
replacement of ``text[start:end]`` plus *selection specs*, a mapping from the
original selection index to ``(a, b)`` offsets **relative to the operation's
start in the output**.  A relative offset may be negative or larger than the
replacement when a selection end lies in unchanged text around the edit.
``_finalize`` sorts and deduplicates the operations, rejects overlaps, applies
them and converts the relative specs to absolute output offsets.

Selection mapping is structural: wrapping shifts offsets by the opening
markup, unwrapping maps the markers to the content's ends, and line-based
actions map each line separately.  A character diff is only used within one
rewritten table row or footnote, never across a whole block.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from math import gcd
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class FormatResult:
    text: str
    selections: Tuple[Tuple[int, int], ...]
    edits: Tuple[Replacement, ...]


_DEFAULTS = {
    "bullet_marker": "-",
    "emphasis_marker": "*",
    "strong_marker": "**",
    "fence_language": "",
    "link_url": "https://example.com",
    "select_word_on_empty": True,
}

# Inline actions that need no option-specific planner (strikethrough reuses the
# Markdown emphasis planner, the rest are literal templates).
_SIMPLE_INLINE_ACTIONS = {
    "strikethrough",
    "html_comment",
    "insertion",
    "critic_addition",
    "critic_deletion",
    "critic_highlight",
    "critic_comment",
    "custom",
}

_BLOCK_ACTIONS = {
    "blockquote",
    "unordered_list",
    "ordered_list",
    "task_list",
    "toggle_task",
    "horizontal_rule",
    "table",
    "fenced_code",
}

_SUPPORTED_ACTIONS = {
    "bold",
    "italic",
    "bold_italic",
    "inline_code",
    "link",
    "image",
    "footnote",
    "critic_substitution",
} | _SIMPLE_INLINE_ACTIONS | _BLOCK_ACTIONS | {
    "heading_{0}".format(level) for level in range(1, 7)
}


@dataclass
class _Member:
    """One input selection inside a group.

    ``a``/``b`` are the original selection ends.  ``target_start`` and
    ``target_end`` are the range the action operates on (a caret expanded to
    its word, or whole lines for block actions).  ``desired_a``/``desired_b``
    are the ends the caller should see selected afterwards, expressed in the
    original text (the expanded word for a caret, otherwise ``a``/``b``).
    """

    index: int
    a: int
    b: int
    target_start: int
    target_end: int
    desired_a: int
    desired_b: int
    line_index: Optional[int] = None


@dataclass
class _InlineGroup:
    start: int
    end: int
    members: List[_Member]


@dataclass
class _Line:
    index: int
    start: int
    end: int
    newline_end: int


@dataclass
class _BlockGroup:
    first_line: int
    last_line: int
    members: List[_Member]


@dataclass
class _Operation:
    """Replace ``text[start:end]`` with ``text``.

    ``selection_specs`` maps a selection index to output offsets relative to
    the start of the replacement.  ``unwrapped`` marks operations that remove
    an existing wrapper (used to decide per-line toggles).
    """

    start: int
    end: int
    text: str
    selection_specs: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    order: int = 0
    final_start: int = 0
    unwrapped: bool = False


# Wrappers are described by ``(outer_start, outer_end, inner_start, inner_end)``:
# ``text[outer_start:outer_end]`` is the whole marked-up span including its
# opening and closing markup, ``text[inner_start:inner_end]`` the content
# between the markers.
_Wrapper = Tuple[int, int, int, int]


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validated_options(action: str, options: Optional[dict]) -> Dict[str, object]:
    if options is None:
        raw: Dict[str, object] = {}
    elif isinstance(options, dict):
        raw = dict(options)
    else:
        raise ValueError("options must be a dict or None")

    resolved: Dict[str, object] = dict(_DEFAULTS)
    resolved.update(raw)

    if not isinstance(resolved["select_word_on_empty"], bool):
        raise ValueError("select_word_on_empty must be a bool")

    for key in ("bullet_marker", "emphasis_marker", "strong_marker"):
        value = resolved[key]
        if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
            raise ValueError("{0} must be a non-empty single-line string".format(key))

    language = resolved["fence_language"]
    if not isinstance(language, str) or "\n" in language or "\r" in language:
        raise ValueError("fence_language must be a single-line string")

    link_url = resolved["link_url"]
    if not isinstance(link_url, str) or "\n" in link_url or "\r" in link_url:
        raise ValueError("link_url must be a single-line string")

    if action == "custom":
        if "prefix" not in raw or "suffix" not in raw:
            raise ValueError("custom formatting requires prefix and suffix")
        prefix = raw.get("prefix")
        suffix = raw.get("suffix")
        placeholder = raw.get("placeholder", "text")
        if not isinstance(prefix, str) or not isinstance(suffix, str):
            raise ValueError("custom prefix and suffix must be strings")
        if not prefix and not suffix:
            raise ValueError("custom prefix and suffix cannot both be empty")
        if not isinstance(placeholder, str):
            raise ValueError("custom placeholder must be a string")
        resolved["prefix"] = prefix
        resolved["suffix"] = suffix
        resolved["placeholder"] = placeholder

    return resolved


def _validated_selections(text: str, selections: object) -> List[Tuple[int, int]]:
    if not isinstance(selections, (list, tuple)):
        raise ValueError("selections must be a list or tuple")

    validated: List[Tuple[int, int]] = []
    for selection in selections:
        if not isinstance(selection, (list, tuple)) or len(selection) != 2:
            raise ValueError("each selection must contain two offsets")
        a, b = selection
        if not _is_plain_int(a) or not _is_plain_int(b):
            raise ValueError("selection offsets must be integers")
        if a < 0 or b < 0 or a > len(text) or b > len(text):
            raise ValueError("selection offset outside document")
        validated.append((a, b))
    return validated


def _is_word_character(character: str) -> bool:
    if character == "_" or character.isalnum():
        return True
    return unicodedata.category(character).startswith("M")


def _word_span(text: str, caret: int) -> Tuple[int, int]:
    if not text:
        return caret, caret

    probe: Optional[int] = None
    if caret < len(text) and _is_word_character(text[caret]):
        probe = caret
    elif caret > 0 and _is_word_character(text[caret - 1]):
        probe = caret - 1
    if probe is None:
        return caret, caret

    start = probe
    while start > 0 and _is_word_character(text[start - 1]):
        start -= 1
    end = probe + 1
    while end < len(text) and _is_word_character(text[end]):
        end += 1
    return start, end


def _inline_groups(
    text: str,
    selections: Sequence[Tuple[int, int]],
    select_word_on_empty: bool,
) -> List[_InlineGroup]:
    members: List[_Member] = []
    for index, (a, b) in enumerate(selections):
        start, end = sorted((a, b))
        if start == end and select_word_on_empty:
            word_start, word_end = _word_span(text, start)
        else:
            word_start, word_end = start, end

        if start == end and word_start != word_end:
            desired_a, desired_b = word_start, word_end
        else:
            desired_a, desired_b = a, b

        members.append(
            _Member(
                index=index,
                a=a,
                b=b,
                target_start=word_start,
                target_end=word_end,
                desired_a=desired_a,
                desired_b=desired_b,
            )
        )

    members.sort(key=lambda member: (member.target_start, member.target_end, member.index))
    groups: List[_InlineGroup] = []
    for member in members:
        if not groups:
            groups.append(_InlineGroup(member.target_start, member.target_end, [member]))
            continue

        current = groups[-1]
        same_start = member.target_start == current.start
        overlaps = member.target_start < current.end
        if same_start or overlaps:
            current.end = max(current.end, member.target_end)
            current.members.append(member)
        else:
            groups.append(_InlineGroup(member.target_start, member.target_end, [member]))
    return groups


def _document_lines(text: str) -> List[_Line]:
    lines: List[_Line] = []
    position = 0
    index = 0
    while position < len(text):
        newline = text.find("\n", position)
        if newline < 0:
            lines.append(_Line(index, position, len(text), len(text)))
            position = len(text)
            index += 1
            break
        content_end = newline
        if content_end > position and text[content_end - 1] == "\r":
            content_end -= 1
        lines.append(_Line(index, position, content_end, newline + 1))
        position = newline + 1
        index += 1

    if not lines or position == len(text) and text.endswith("\n"):
        lines.append(_Line(index, len(text), len(text), len(text)))
    return lines


def _line_index_for_offset(newline_ends: Sequence[int], offset: int) -> int:
    """Index of the line containing ``offset``.

    ``newline_ends`` holds each line's ``newline_end`` in document order.  An
    offset at the very end of the document belongs to the last line.
    """
    return min(bisect_right(newline_ends, offset), len(newline_ends) - 1)


def _block_groups(
    text: str,
    selections: Sequence[Tuple[int, int]],
) -> Tuple[List[_Line], List[_BlockGroup]]:
    lines = _document_lines(text)
    newline_ends = [line.newline_end for line in lines]
    member_lines: Dict[int, Tuple[int, int]] = {}
    selected_line_indices = set()
    members: List[_Member] = []

    for index, (a, b) in enumerate(selections):
        start, end = sorted((a, b))
        first = _line_index_for_offset(newline_ends, start)
        if start == end:
            last = first
        else:
            last = _line_index_for_offset(newline_ends, end - 1)
        member_lines[index] = (first, last)
        selected_line_indices.update(range(first, last + 1))
        members.append(
            _Member(
                index=index,
                a=a,
                b=b,
                target_start=lines[first].start,
                target_end=lines[last].end,
                desired_a=a,
                desired_b=b,
                line_index=first if start == end else None,
            )
        )

    if not selected_line_indices:
        return lines, []

    sorted_indices = sorted(selected_line_indices)
    ranges: List[Tuple[int, int]] = []
    range_start = sorted_indices[0]
    range_end = range_start
    for line_index in sorted_indices[1:]:
        if line_index == range_end + 1:
            range_end = line_index
        else:
            ranges.append((range_start, range_end))
            range_start = range_end = line_index
    ranges.append((range_start, range_end))

    # Every member's lines fall inside exactly one contiguous range.
    groups = [_BlockGroup(first, last, []) for first, last in ranges]
    range_starts = [first for first, _ in ranges]
    for member in members:
        first_line = member_lines[member.index][0]
        groups[bisect_right(range_starts, first_line) - 1].members.append(member)
    return lines, groups


_SEQUENCE_MATCHER_CELL_LIMIT = 250_000


def _subsequence_positions(needle: str, haystack: str) -> Optional[List[int]]:
    positions: List[int] = []
    search_at = 0
    for character in needle:
        found = haystack.find(character, search_at)
        if found < 0:
            return None
        positions.append(found)
        search_at = found + 1
    return positions


def _linear_diff_position(
    old: str,
    new: str,
    position: int,
    affinity: str,
) -> int:
    old_in_new = _subsequence_positions(old, new)
    if old_in_new is not None:
        if position == 0:
            return old_in_new[0]
        if position == len(old):
            return old_in_new[-1] + 1
        if affinity == "right":
            return old_in_new[position]
        return old_in_new[position - 1] + 1

    new_in_old = _subsequence_positions(new, old)
    if new_in_old is not None:
        return bisect_left(new_in_old, position)

    prefix = 0
    prefix_limit = min(len(old), len(new))
    while prefix < prefix_limit and old[prefix] == new[prefix]:
        prefix += 1

    suffix = 0
    suffix_limit = min(len(old) - prefix, len(new) - prefix)
    while suffix < suffix_limit and old[-suffix - 1] == new[-suffix - 1]:
        suffix += 1

    old_middle_end = len(old) - suffix
    new_middle_end = len(new) - suffix
    if position <= prefix:
        return position
    if position >= old_middle_end:
        return new_middle_end + position - old_middle_end

    old_width = old_middle_end - prefix
    new_width = new_middle_end - prefix
    return prefix + int(round((position - prefix) * new_width / old_width))


def _diff_position(old: str, new: str, position: int, affinity: str = "right") -> int:
    position = max(0, min(position, len(old)))
    if old == new:
        return position
    if not old:
        return len(new) if affinity == "right" else 0
    if not new:
        return 0
    if len(old) * len(new) > _SEQUENCE_MATCHER_CELL_LIMIT:
        return _linear_diff_position(old, new, position, affinity)

    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    opcodes = matcher.get_opcodes()

    equal_candidates: List[int] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal" and i1 <= position <= i2:
            equal_candidates.append(j1 + (position - i1))
    if equal_candidates:
        return max(equal_candidates) if affinity == "right" else min(equal_candidates)

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "insert" and position == i1:
            return j2 if affinity == "right" else j1
        if i1 <= position <= i2 and i2 > i1:
            if position == i1:
                return j1
            if position == i2:
                return j2
            old_width = i2 - i1
            new_width = j2 - j1
            return j1 + int(round((position - i1) * new_width / old_width))

    return len(new)


def _wrap_operation(
    group: _InlineGroup,
    prefix: str,
    content: str,
    suffix: str,
    uses_placeholder: bool,
    boundaries: Optional[Sequence[int]] = None,
) -> _Operation:
    """Replace the group with ``prefix + content + suffix``.

    Carets that produced a placeholder select it; every other selection keeps
    its offsets within the wrapped content.  ``boundaries[i]`` gives the
    output offset of original character ``i`` when ``content`` is an escaped
    form of the group's text.
    """
    specs: Dict[int, Tuple[int, int]] = {}
    width = group.end - group.start

    def relative(position: int) -> int:
        offset = max(0, min(position - group.start, width))
        return len(prefix) + (boundaries[offset] if boundaries is not None else offset)

    for member in group.members:
        if uses_placeholder and member.target_start == member.target_end:
            specs[member.index] = (len(prefix), len(prefix) + len(content))
        else:
            specs[member.index] = (relative(member.desired_a), relative(member.desired_b))
    return _Operation(group.start, group.end, prefix + content + suffix, specs)


def _unwrap_operation(
    wrapper: _Wrapper,
    new_inner: str,
    members: Iterable[_Member],
    inner_map: Optional[Mapping[int, int]] = None,
) -> _Operation:
    """Replace a whole wrapper with ``new_inner``.

    Positions in the opening markup map to the start of the new content,
    positions in the closing markup to its end, and positions inside the
    content keep their offset (through ``inner_map`` when the content is
    transformed, e.g. unescaped).
    """
    outer_start, outer_end, inner_start, inner_end = wrapper

    def relative(position: int) -> int:
        if position <= inner_start:
            return 0
        if position >= inner_end:
            return len(new_inner)
        offset = position - inner_start
        if inner_map is not None:
            offset = inner_map.get(offset, offset)
        return max(0, min(offset, len(new_inner)))

    specs = {
        member.index: (relative(member.desired_a), relative(member.desired_b))
        for member in members
    }
    return _Operation(outer_start, outer_end, new_inner, specs, unwrapped=True)


_NEWLINE = r"(?:\r\n|\r(?!\n)|\n)"
_BLANK_PARAGRAPH_RE = re.compile(_NEWLINE + r"[ \t]*" + _NEWLINE)


def _is_escaped_delimiter(text: str, position: int) -> bool:
    backslashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _find_unescaped(text: str, delimiter: str, start: int) -> int:
    search_at = start
    while True:
        found = text.find(delimiter, search_at)
        if found < 0 or not _is_escaped_delimiter(text, found):
            return found
        search_at = found + max(1, len(delimiter))


def _valid_static_wrapper(
    text: str,
    outer_start: int,
    outer_end: int,
    inner_start: int,
    inner_end: int,
    prefix: str,
    suffix: str,
    require_non_whitespace_inner: bool,
    respect_escaped_delimiters: bool,
) -> bool:
    if (
        respect_escaped_delimiters
        and prefix
        and _is_escaped_delimiter(text, outer_start)
    ):
        return False
    if (
        respect_escaped_delimiters
        and suffix
        and _is_escaped_delimiter(text, inner_end)
    ):
        return False
    inner = text[inner_start:inner_end]
    if _BLANK_PARAGRAPH_RE.search(inner):
        return False
    return not (require_non_whitespace_inner and (
        not inner or inner[0].isspace() or inner[-1].isspace()
    ))


class _PairIndex:
    """Delimiter pairs ``(opener, closer)`` of one text, searchable by position."""

    def __init__(self, pairs: Iterable[Tuple[int, int]], suffix_length: int, strong_only: set) -> None:
        self.pairs = sorted(pairs)
        self.openers = [opener for opener, _ in self.pairs]
        self.strong_only = strong_only
        self.max_ends: List[int] = []
        for _, closer in self.pairs:
            outer_end = closer + suffix_length
            self.max_ends.append(max(outer_end, self.max_ends[-1] if self.max_ends else 0))

    def containing(self, start: int, end: int) -> Iterable[Tuple[int, int]]:
        """Pairs whose outer span contains ``[start, end]``, innermost first."""
        index = bisect_right(self.openers, start) - 1
        while index >= 0 and self.max_ends[index] >= end:
            yield self.pairs[index]
            index -= 1


def _static_pairs(
    text: str,
    start: int,
    end: int,
    prefix: str,
    suffix: str,
    require_non_whitespace_inner: bool,
    respect_escaped_delimiters: bool,
) -> _PairIndex:
    def find_token(token: str, at: int) -> int:
        if respect_escaped_delimiters:
            return _find_unescaped(text, token, at)
        return text.find(token, at)

    # Establish pairs from left to right. A closing token must never be reused
    # as an opener for a wrapper spanning unrelated siblings.
    pairs: List[Tuple[int, int]] = []
    # Openers of single-character emphasis pairs whose delimiter runs are not
    # both of odd length: those markers belong to strong emphasis (``**x**``),
    # so an italic toggle must add a marker instead of stealing one.
    strong_only = set()
    search_at = 0
    if prefix == suffix and require_non_whitespace_inner:
        single_character = len(prefix) == 1
        underscore = set(prefix) == {"_"}
        openers: List[Tuple[int, int]] = []
        while True:
            position = find_token(prefix, search_at)
            if position < 0:
                break
            run_end = position + len(prefix)
            while text.startswith(prefix, run_end):
                run_end += len(prefix)
            before = text[position - 1] if position else ""
            after = text[run_end] if run_end < len(text) else ""
            can_open = bool(after and not after.isspace())
            can_close = bool(before and not before.isspace())
            if underscore and before.isalnum() and after.isalnum():
                # CommonMark: intraword underscores never delimit emphasis.
                can_open = can_close = False
            run_length = run_end - position
            # A run is one delimiter boundary: nested markers within the same
            # opening run must not be mistaken for empty sibling wrappers.
            for token in range(position, run_end, len(prefix)):
                if can_close and openers:
                    opener, opener_run_length = openers.pop()
                    pairs.append((opener, token))
                    if single_character and not (opener_run_length % 2 and run_length % 2):
                        strong_only.add(opener)
                elif can_open:
                    openers.append((token, run_length))
            search_at = run_end
    elif prefix == suffix:
        # Literal symmetric templates (``==``, ``%``): pair the nearest
        # flanking opener with the next flanking closer, so stray tokens such
        # as ``a == b`` or ``50%`` do not shift the pairing of later ones.
        # Tokens touching the selection are always accepted so whitespace
        # content still toggles back.
        check_open = not prefix[-1].isspace()
        check_close = not suffix[0].isspace()
        pending: Optional[int] = None
        while True:
            position = find_token(prefix, search_at)
            if position < 0:
                break
            token_end = position + len(prefix)
            before = text[position - 1] if position else ""
            after = text[token_end] if token_end < len(text) else ""
            can_open = (
                not check_open or start in (position, token_end)
                or bool(after and not after.isspace())
            )
            can_close = (
                not check_close or end in (position, token_end)
                or bool(before and not before.isspace())
            )
            if pending is not None and can_close:
                pairs.append((pending, position))
                pending = None
            elif can_open:
                pending = position
            search_at = token_end
    elif prefix + suffix == suffix + prefix:
        # Unequal runs of the same literal unit (e.g. << / <) have ambiguous
        # token boundaries. Consume existing closers before opening siblings,
        # and use the whole run so nested opening/closing runs stay balanced.
        unit = prefix[:gcd(len(prefix), len(suffix))]
        run_openers: List[int] = []
        for match in re.finditer("(?:" + re.escape(unit) + ")+", text):
            run_start, run_end = match.span()
            before = text[run_start - 1] if run_start else ""
            after = text[run_end] if run_end < len(text) else ""
            # Literal templates can contain whitespace; unlike Markdown
            # emphasis their opening boundary is never whitespace-rejected.
            close_count = 0
            if ((before and not before.isspace()) or not after
                    or run_start == end or run_end == end):
                maximum = min(len(run_openers), (run_end - run_start) // len(suffix))
                for count in range(maximum, -1, -1):
                    remaining = run_end - run_start - count * len(suffix)
                    if remaining % len(prefix) == 0:
                        close_count = count
                        break
            position = run_start
            for _ in range(close_count):
                pairs.append((run_openers.pop(), position))
                position += len(suffix)
            while position + len(prefix) <= run_end:
                run_openers.append(position)
                position += len(prefix)
    else:
        stack: List[int] = []
        while search_at < len(text):
            opener = find_token(prefix, search_at)
            closer = find_token(suffix, search_at)
            if opener < 0 and closer < 0:
                break
            if opener >= 0 and (
                closer < 0 or opener < closer
                or (opener == closer and len(prefix) > len(suffix))
            ):
                stack.append(opener)
                search_at = opener + len(prefix)
            else:
                if stack:
                    pairs.append((stack.pop(), closer))
                search_at = closer + len(suffix)
    return _PairIndex(pairs, len(suffix), strong_only)


def _pairs_depend_on_selection(
    text: str,
    start: int,
    end: int,
    prefix: str,
    suffix: str,
    require_non_whitespace_inner: bool,
) -> bool:
    """Whether ``_static_pairs`` would treat a token touching the selection
    specially; otherwise its result is the same for every selection and can
    be cached (it is then computed with an impossible selection)."""
    if prefix == suffix:
        width = len(prefix)
        return not require_non_whitespace_inner and (
            text.startswith(prefix, start)
            or text.startswith(prefix, end)
            or (start >= width and text.startswith(prefix, start - width))
            or (end >= width and text.startswith(prefix, end - width))
        )
    if prefix + suffix == suffix + prefix:
        unit = prefix[: gcd(len(prefix), len(suffix))]
        return text.startswith(unit, end) or (
            end >= len(unit) and text.startswith(unit, end - len(unit))
        )
    return False


def _find_static_wrapper(
    text: str,
    start: int,
    end: int,
    prefix: str,
    suffix: str,
    require_non_whitespace_inner: bool = False,
    respect_escaped_delimiters: bool = False,
    cache: Optional[Dict[tuple, object]] = None,
) -> Optional[_Wrapper]:
    """Find the innermost wrapper of ``prefix``/``suffix`` around the range.

    ``cache`` (scoped to one ``text``) keeps paragraph boundaries and marker
    pairs between calls so many selections do not rescan the document.
    """
    if require_non_whitespace_inner:
        # Common emphasis cannot span blank paragraphs. Bound detection before
        # pairing markers so unrelated prose cannot cause quadratic scans.
        boundaries = cache.get(("paragraphs",)) if cache is not None else None
        if boundaries is None:
            spans = [match.span() for match in _BLANK_PARAGRAPH_RE.finditer(text)]
            boundaries = ([span[0] for span in spans], [span[1] for span in spans])
            if cache is not None:
                cache[("paragraphs",)] = boundaries
        boundary_starts, boundary_ends = boundaries  # type: ignore[misc]
        index = bisect_right(boundary_ends, start)
        lower = boundary_ends[index - 1] if index else 0
        upper = len(text)
        if index < len(boundary_starts):
            if boundary_starts[index] < end:
                return None
            upper = boundary_starts[index]
        if lower or upper < len(text):
            found = _find_paired_wrapper(
                text[lower:upper], start - lower, end - lower, prefix, suffix,
                True, respect_escaped_delimiters, cache, (lower, upper),
            )
            if found is None:
                return None
            return (found[0] + lower, found[1] + lower, found[2] + lower, found[3] + lower)
    return _find_paired_wrapper(
        text, start, end, prefix, suffix,
        require_non_whitespace_inner, respect_escaped_delimiters, cache, (0, len(text)),
    )


def _find_paired_wrapper(
    text: str,
    start: int,
    end: int,
    prefix: str,
    suffix: str,
    require_non_whitespace_inner: bool,
    respect_escaped_delimiters: bool,
    cache: Optional[Dict[tuple, object]],
    cache_scope: Tuple[int, int],
) -> Optional[_Wrapper]:
    selected = text[start:end]
    # One-sided literal templates can only be toggled at a direct boundary.
    if not prefix and suffix:
        if selected.endswith(suffix):
            return start, end, start, end - len(suffix)
        if text.startswith(suffix, end):
            return start, end + len(suffix), start, end
        return None
    if prefix and not suffix:
        if selected.startswith(prefix):
            return start, end, start + len(prefix), end
        if start >= len(prefix) and text[start - len(prefix):start] == prefix:
            return start - len(prefix), end, start, end
        return None
    if not prefix and not suffix:
        return None

    if _pairs_depend_on_selection(text, start, end, prefix, suffix, require_non_whitespace_inner):
        index = _static_pairs(
            text, start, end, prefix, suffix,
            require_non_whitespace_inner, respect_escaped_delimiters,
        )
    else:
        key = ("pairs", cache_scope, prefix, suffix, require_non_whitespace_inner, respect_escaped_delimiters)
        cached = cache.get(key) if cache is not None else None
        if isinstance(cached, _PairIndex):
            index = cached
        else:
            index = _static_pairs(
                text, -1, -1, prefix, suffix,
                require_non_whitespace_inner, respect_escaped_delimiters,
            )
            if cache is not None:
                cache[key] = index

    best: Optional[_Wrapper] = None
    # A caret touching or inside either marker run counts as inside.
    for opener, closer in index.containing(start, end):
        inner_start, inner_end = opener + len(prefix), closer
        outer_end = closer + len(suffix)
        if end > outer_end:
            continue
        if opener in index.strong_only and not (
            # An explicit selection of "*x*" cut out of "**x**" still toggles.
            (start, end) == (opener, outer_end)
            and opener >= len(prefix)
            and text.startswith(prefix, opener - len(prefix))
        ):
            continue
        valid = _valid_static_wrapper(
            text, opener, outer_end, inner_start, inner_end, prefix, suffix,
            require_non_whitespace_inner, respect_escaped_delimiters,
        )
        complete_literal = (
            not require_non_whitespace_inner and not respect_escaped_delimiters
            and (start, end) in ((opener, outer_end), (inner_start, inner_end))
        )
        if (valid or complete_literal) and (
            best is None or outer_end - opener < best[1] - best[0]
        ):
            best = (opener, outer_end, inner_start, inner_end)
    return best


def _plan_static_inline(
    text: str,
    group: _InlineGroup,
    prefix: str,
    suffix: str,
    placeholder: str,
    require_non_whitespace_inner: bool = False,
    respect_escaped_delimiters: bool = False,
    cache: Optional[Dict[tuple, object]] = None,
) -> _Operation:
    wrapper = _find_static_wrapper(
        text,
        group.start,
        group.end,
        prefix,
        suffix,
        require_non_whitespace_inner,
        respect_escaped_delimiters,
        cache,
    )
    if wrapper is not None:
        return _unwrap_operation(wrapper, text[wrapper[2] : wrapper[3]], group.members)

    uses_placeholder = group.start == group.end
    content = placeholder if uses_placeholder else text[group.start : group.end]
    return _wrap_operation(group, prefix, content, suffix, uses_placeholder)


def _plan_common_inline(
    text: str,
    group: _InlineGroup,
    prefix: str,
    suffix: str,
    cache: Optional[Dict[tuple, object]] = None,
) -> Optional[_Operation]:
    if group.start == group.end:
        return _plan_static_inline(
            text,
            group,
            prefix,
            suffix,
            "text",
            require_non_whitespace_inner=True,
            respect_escaped_delimiters=True,
            cache=cache,
        )

    start = group.start
    end = group.end
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == end:
        return None

    def clamp(position: int) -> int:
        return max(start, min(position, end))

    members = [
        _Member(
            index=member.index,
            a=member.a,
            b=member.b,
            target_start=clamp(member.target_start),
            target_end=clamp(member.target_end),
            desired_a=clamp(member.desired_a),
            desired_b=clamp(member.desired_b),
            line_index=member.line_index,
        )
        for member in group.members
    ]
    return _plan_static_inline(
        text,
        _InlineGroup(start, end, members),
        prefix,
        suffix,
        "text",
        require_non_whitespace_inner=True,
        respect_escaped_delimiters=True,
        cache=cache,
    )


def _backtick_runs(text: str) -> List[Tuple[int, int, int]]:
    return [(match.start(), match.end(), len(match.group(0))) for match in re.finditer(r"`+", text)]


def _code_spans(text: str) -> List[_Wrapper]:
    """All code spans of ``text`` in document order; they never overlap."""
    runs = _backtick_runs(text)
    by_length: Dict[int, List[int]] = {}
    for index, (_, _, length) in enumerate(runs):
        by_length.setdefault(length, []).append(index)
    spans: List[_Wrapper] = []
    index = 0
    while index < len(runs):
        run_start, run_end, length = runs[index]
        if _is_escaped_delimiter(text, run_start):
            # Outside code spans a backslash escapes the run's first backtick.
            run_start += 1
            length -= 1
            if not length:
                index += 1
                continue
        # Closers are never escaped: backslashes are literal inside code.
        same = by_length.get(length, [])
        found = bisect_right(same, index)
        if found == len(same):
            index += 1
            continue
        closing_index = same[found]
        closer = runs[closing_index]
        spans.append((run_start, closer[1], run_end, closer[0]))
        # Everything up to the matching closer belongs to this code span.
        index = closing_index + 1
    return spans


def _find_code_span(
    text: str,
    start: int,
    end: int,
    spans: Optional[Sequence[_Wrapper]] = None,
) -> Optional[_Wrapper]:
    if spans is None:
        spans = _code_spans(text)
    found = bisect_right(spans, (start, len(text) + 1)) - 1
    if found < 0:
        return None
    outer_start, outer_end, inner_start, inner_end = spans[found]
    # A caret touching either backtick run counts as inside the span.
    if outer_start <= start and end <= outer_end and not _BLANK_PARAGRAPH_RE.search(
            text[inner_start:inner_end]):
        return spans[found]
    return None


def _plan_inline_code(
    text: str,
    group: _InlineGroup,
    spans: Optional[Sequence[_Wrapper]] = None,
) -> _Operation:
    existing = _find_code_span(text, group.start, group.end, spans)
    if existing is not None:
        outer_start, outer_end, inner_start, inner_end = existing
        content = text[inner_start:inner_end]
        inner_map: Optional[Dict[int, int]] = None
        if (
            len(content) >= 2
            and content.startswith(" ")
            and content.endswith(" ")
            and content.strip(" ")
        ):
            content = content[1:-1]
            inner_map = {offset: offset - 1 for offset in range(1, len(content) + 2)}
        return _unwrap_operation(existing, content, group.members, inner_map)

    uses_placeholder = group.start == group.end
    content = "code" if uses_placeholder else text[group.start : group.end]
    longest = max((length for _, _, length in _backtick_runs(content)), default=0)
    fence = "`" * max(1, longest + 1)
    pad = ""
    if content.startswith("`") or content.endswith("`"):
        pad = " "
    elif content and content.strip(" ") and (
        content.startswith(" ") or content.endswith(" ")
    ):
        pad = " "
    return _wrap_operation(group, fence + pad, content, pad + fence, uses_placeholder)


def _escape_label(label: str) -> Tuple[str, List[int]]:
    pieces: List[str] = []
    boundaries = [0]
    length = 0
    for character in label:
        escaped = "\\" + character if character in "\\[]" else character
        pieces.append(escaped)
        length += len(escaped)
        boundaries.append(length)
    return "".join(pieces), boundaries


def _unescape_label(label: str) -> Tuple[str, Dict[int, int]]:
    """Unescape ``\\``, ``[`` and ``]``; also map raw offsets to new offsets."""
    result: List[str] = []
    offsets: Dict[int, int] = {}
    index = 0
    while index < len(label):
        offsets[index] = len(result)
        if index + 1 < len(label) and label[index] == "\\" and label[index + 1] in "\\[]":
            offsets[index + 1] = len(result)
            result.append(label[index + 1])
            index += 2
        else:
            result.append(label[index])
            index += 1
    offsets[len(label)] = len(result)
    return "".join(result), offsets


def _escape_destination(destination: str) -> str:
    result: List[str] = []
    for character in destination:
        if character == "\\":
            result.append("\\\\")
        elif character in "()":
            result.append("\\" + character)
        elif character.isspace():
            result.extend("%{0:02X}".format(byte) for byte in character.encode("utf-8"))
        elif character == "<":
            result.append("%3C")
        elif character == ">":
            result.append("%3E")
        else:
            result.append(character)
    return "".join(result)


# Link text and destination stay inside one paragraph: a newline is allowed
# only when the next line is not blank.  Link text may contain balanced
# brackets one level deep but never a stray ``[``, so an unrelated earlier
# bracket cannot start a fake match that swallows the real link.
_LINK_CHAR = r"(?:\\.|[^\\\[\]\r\n]|" + _NEWLINE + r"(?![ \t]*(?:[\r\n]|$)))"
_LINK_DEST_CHAR = r"(?:\\.|[^\\)\r\n]|" + _NEWLINE + r"(?![ \t]*(?:[\r\n]|$)))"
_LINK_RE = re.compile(
    r"(?P<bang>!?)\[(?P<label>(?:" + _LINK_CHAR + r"|\[" + _LINK_CHAR + r"*\])*)\]"
    r"\((?P<dest>" + _LINK_DEST_CHAR + r"*)\)",
    re.DOTALL,
)
# Only used when the selection is exactly a link's text, so a link the engine
# created around several paragraphs still toggles back.
_LOOSE_LINK_RE = re.compile(
    r"(?P<bang>!?)\[(?P<label>(?:\\.|[^\\\[\]])*)\]\((?P<dest>(?:\\.|[^\\)])*)\)",
    re.DOTALL,
)


class _LinkIndex:
    """All link/image matches of one document, starting at every ``[``.

    Matches may overlap (a bracket inside link text starts its own attempt),
    so the innermost match containing a selection can be chosen.
    """

    def __init__(self, text: str) -> None:
        self.matches: List["re.Match[str]"] = []
        for bracket in re.finditer(r"\[", text):
            # The start is either "![" (an image) or a plain "[" (a link).
            position = bracket.start()
            if _is_escaped_delimiter(text, position):
                continue
            if position and text[position - 1] == "!" and not _is_escaped_delimiter(text, position - 1):
                position -= 1
            match = _LINK_RE.match(text, position)
            if match is not None:
                self.matches.append(match)
        self.starts = [match.start() for match in self.matches]
        self.max_ends: List[int] = []
        for match in self.matches:
            self.max_ends.append(max(match.end(), self.max_ends[-1] if self.max_ends else 0))

    def find(self, start: int, end: int, image: bool) -> Optional["re.Match[str]"]:
        best: Optional["re.Match[str]"] = None
        index = bisect_right(self.starts, start) - 1
        while index >= 0 and self.max_ends[index] >= end:
            match = self.matches[index]
            # Anything inside the link, its destination included, toggles it;
            # so does a caret touching its first or last character.
            if (
                bool(match.group("bang")) == image
                and match.start() <= start
                and end <= match.end()
                and (best is None or match.end() - match.start() < best.end() - best.start())
            ):
                best = match
            index -= 1
        return best


def _plan_link(
    text: str,
    group: _InlineGroup,
    image: bool,
    destination: str,
    links: Optional[_LinkIndex] = None,
    escape_bang: bool = True,
) -> _Operation:
    if links is None:
        links = _LinkIndex(text)
    existing = links.find(group.start, group.end, image)
    if existing is None and group.start < group.end:
        lead_start = group.start - (2 if image else 1)
        loose = _LOOSE_LINK_RE.match(text, lead_start) if lead_start >= 0 else None
        if (
            loose is not None
            and bool(loose.group("bang")) == image
            and loose.span("label") == (group.start, group.end)
        ):
            existing = loose
    if existing is not None:
        label, offsets = _unescape_label(existing.group("label"))
        wrapper = (existing.start(), existing.end()) + existing.span("label")
        return _unwrap_operation(wrapper, label, group.members, offsets)

    uses_placeholder = group.start == group.end
    label = "alt text" if image and uses_placeholder else "link text" if uses_placeholder else text[group.start : group.end]
    escaped_label, boundaries = _escape_label(label)
    lead = "![" if image else "["
    operation = _wrap_operation(
        group,
        lead,
        escaped_label,
        "](" + _escape_destination(destination) + ")",
        uses_placeholder,
        None if uses_placeholder else boundaries,
    )
    if (
        not image
        and escape_bang
        and group.start
        and text[group.start - 1] == "!"
        and not _is_escaped_delimiter(text, group.start - 1)
    ):
        # "Wow![x](u)" would be an image: escape the "!" in front of the link.
        operation.start -= 1
        operation.text = "\\!" + operation.text
        operation.selection_specs = {
            index: (a + 2, b + 2) for index, (a, b) in operation.selection_specs.items()
        }
    return operation


_SUBSTITUTION_RE = re.compile(r"\{~~(?P<old>.*?)~>(?P<new>.*?)~~\}", re.DOTALL)


def _find_substitution(
    text: str,
    start: int,
    end: int,
) -> Optional[re.Match[str]]:
    candidates: List[re.Match[str]] = []
    for match in _SUBSTITUTION_RE.finditer(text):
        if (start == match.start() and end == match.end()) or (
            match.start("old") <= start and end <= match.end("new")
        ):
            candidates.append(match)
    if not candidates:
        return None
    return min(candidates, key=lambda match: match.end() - match.start())


def _plan_substitution(text: str, group: _InlineGroup) -> _Operation:
    existing = _find_substitution(text, group.start, group.end)
    if existing is not None:
        wrapper = (existing.start(), existing.end(), existing.start("old"), existing.end("new"))
        return _unwrap_operation(wrapper, text[wrapper[2] : wrapper[3]], group.members)

    old = "old" if group.start == group.end else text[group.start : group.end]
    replacement = "{~~" + old + "~>new~~}"
    new_start = 3 + len(old) + 2
    specs = {member.index: (new_start, new_start + 3) for member in group.members}
    return _Operation(group.start, group.end, replacement, specs)


def _indent_and_rest(content: str) -> Tuple[str, str]:
    match = re.match(r"[ \t]*", content)
    assert match is not None
    return match.group(0), content[match.end() :]


def _heading_parts(content: str) -> Optional[Tuple[str, int, str]]:
    match = re.match(r"^([ \t]*)(#{1,6})(?:[ \t]+|$)(.*)$", content)
    if match is None:
        return None
    return match.group(1), len(match.group(2)), match.group(3)


def _quote_parts(content: str) -> Optional[Tuple[str, str]]:
    indent, rest = _indent_and_rest(content)
    if not rest.startswith(">"):
        return None
    if len(rest) > 1 and not rest[1].isspace():
        return None
    body = rest[1:]
    if body.startswith((" ", "\t")):
        body = body[1:]
    return indent, body


def _unordered_parts(content: str) -> Optional[Tuple[str, str, str]]:
    match = re.match(r"^([ \t]*)([-+*])(?:[ \t]+|$)(.*)$", content)
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3)


def _ordered_parts(content: str) -> Optional[Tuple[str, str, str]]:
    match = re.match(r"^([ \t]*)(\d+[.)])(?:[ \t]+|$)(.*)$", content)
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3)


def _task_parts(content: str) -> Optional[Tuple[str, str, str, str]]:
    match = re.match(
        r"^([ \t]*)([-+*]|\d+[.)])(?:[ \t]+)\[([ xX])\](?:[ \t]+|$)(.*)$",
        content,
    )
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3), match.group(4)


def _is_horizontal_rule(content: str) -> bool:
    stripped = content.strip()
    return bool(
        re.fullmatch(r"(?:\*[ \t]*){3,}", stripped)
        or re.fullmatch(r"(?:-[ \t]*){3,}", stripped)
        or re.fullmatch(r"(?:_[ \t]*){3,}", stripped)
    )


def _clamped_selection_specs(
    members: Iterable[_Member],
    start: int,
    end: int,
) -> Dict[int, Tuple[int, int]]:
    def relative(position: int) -> int:
        return max(start, min(position, end)) - start

    return {
        member.index: (relative(member.desired_a), relative(member.desired_b))
        for member in members
    }


def _isolated_block_replacement(
    text: str,
    start: int,
    end: int,
    block: str,
    eol: str,
) -> str:
    """Keep ``text[start:end]`` and append ``block`` as its own paragraph.

    The block starts ``end - start + 2 * len(eol)`` characters into the result.
    """
    trailing = eol if text.startswith(eol, end) else ""
    return text[start:end] + eol + eol + block + trailing


# Blockquote markers in front of a line; other block actions keep them in
# place and work on the rest of the line.
_QUOTE_PREFIX_RE = re.compile(r"(?:[ ]{0,3}>[ ]?)*")


def _split_quote_prefix(content: str) -> Tuple[str, str]:
    match = _QUOTE_PREFIX_RE.match(content)
    assert match is not None
    return content[: match.end()], content[match.end() :]


def _line_offset_map(old: str, new: str, offset: int) -> int:
    """Map ``offset`` in ``old`` to ``new`` when only a line prefix changed.

    The line body is the longest common suffix; offsets in the unchanged
    leading part keep their value and offsets inside the rewritten prefix are
    scaled.  An offset at an insertion point moves after the inserted text.
    """
    limit = min(len(old), len(new))
    suffix = 0
    while suffix < limit and old[-1 - suffix] == new[-1 - suffix]:
        suffix += 1
    limit -= suffix
    prefix = 0
    while prefix < limit and old[prefix] == new[prefix]:
        prefix += 1
    old_middle_end = len(old) - suffix
    new_middle_end = len(new) - suffix
    if offset >= old_middle_end:
        return new_middle_end + offset - old_middle_end
    if offset <= prefix:
        return offset
    old_width = old_middle_end - prefix
    new_width = new_middle_end - prefix
    return prefix + int(round((offset - prefix) * new_width / old_width))


def _ordinal_counter():
    """Return ``next(indent)`` numbering list items per indentation level."""
    levels: List[List[int]] = []

    def next_number(indent: str) -> int:
        width = len(indent.expandtabs(4))
        while levels and levels[-1][0] > width:
            levels.pop()
        if levels and levels[-1][0] == width:
            levels[-1][1] += 1
        else:
            levels.append([width, 1])
        return levels[-1][1]

    return next_number


def _rewrite_heading(contents: Sequence[str], level: int) -> List[Tuple[str, Optional[Tuple[int, int]]]]:
    parsed = [_heading_parts(content) for content in contents]
    remove = all(parts is not None and parts[1] == level for parts in parsed)
    result: List[Tuple[str, Optional[Tuple[int, int]]]] = []
    for content, parts in zip(contents, parsed):
        if remove:
            assert parts is not None
            result.append((parts[0] + parts[2], None))
            continue
        if parts is None:
            indent, body = _indent_and_rest(content)
        else:
            indent, _, body = parts
        if body:
            result.append((indent + "#" * level + " " + body, None))
        else:
            marker_end = len(indent) + level + 1
            result.append(
                (indent + "#" * level + " Heading", (marker_end, marker_end + len("Heading")))
            )
    return result


def _rewrite_list(
    contents: Sequence[str],
    action: str,
    bullet: str,
) -> List[Tuple[str, Optional[Tuple[int, int]]]]:
    unordered = [_unordered_parts(content) for content in contents]
    ordered = [_ordered_parts(content) for content in contents]
    tasks = [_task_parts(content) for content in contents]

    remove_unordered = action == "unordered_list" and all(parts is not None for parts in unordered)
    remove_ordered = action == "ordered_list" and all(parts is not None for parts in ordered)
    remove_tasks = action == "task_list" and all(parts is not None for parts in tasks)
    next_number = _ordinal_counter()

    result: List[Tuple[str, Optional[Tuple[int, int]]]] = []
    for content, ul, ol, task in zip(contents, unordered, ordered, tasks):
        if action == "unordered_list":
            if remove_unordered:
                assert ul is not None
                new_content = ul[0] + (task[3] if task is not None else ul[2])
            elif ul is not None:
                new_content = ul[0] + bullet + " " + ul[2]
            elif ol is not None:
                new_content = ol[0] + bullet + " " + ol[2]
            else:
                indent, body = _indent_and_rest(content)
                new_content = indent + bullet + " " + body

        elif action == "ordered_list":
            if remove_ordered:
                assert ol is not None
                new_content = ol[0] + (task[3] if task is not None else ol[2])
            else:
                if ol is not None:
                    indent, body = ol[0], ol[2]
                elif ul is not None:
                    indent, body = ul[0], ul[2]
                else:
                    indent, body = _indent_and_rest(content)
                new_content = indent + "{0}. ".format(next_number(indent)) + body

        elif action == "task_list":
            if remove_tasks:
                assert task is not None
                new_content = task[0] + task[1] + " " + task[3]
            elif task is not None:
                new_content = content
            elif ul is not None:
                new_content = ul[0] + ul[1] + " [ ] " + ul[2]
            elif ol is not None:
                new_content = ol[0] + ol[1] + " [ ] " + ol[2]
            else:
                indent, body = _indent_and_rest(content)
                new_content = indent + bullet + " [ ] " + body

        else:
            if task is not None:
                checked = " " if task[2].lower() == "x" else "x"
                new_content = task[0] + task[1] + " [" + checked + "] " + task[3]
            elif ul is not None:
                new_content = ul[0] + ul[1] + " [x] " + ul[2]
            elif ol is not None:
                new_content = ol[0] + ol[1] + " [x] " + ol[2]
            else:
                indent, body = _indent_and_rest(content)
                new_content = indent + bullet + " [x] " + body

        placeholder = (len(new_content), len(new_content)) if not content.strip() else None
        result.append((new_content, placeholder))
    return result


def _rewrite_blockquote(contents: Sequence[str]) -> List[Tuple[str, Optional[Tuple[int, int]]]]:
    parsed = [_quote_parts(content) for content in contents]
    # Blank lines between quoted lines do not prevent toggling the quote off.
    considered = [parts for content, parts in zip(contents, parsed) if content.strip()]
    remove = all(parts is not None for parts in (considered or parsed))
    result: List[Tuple[str, Optional[Tuple[int, int]]]] = []
    for content, parts in zip(contents, parsed):
        if remove and parts is not None:
            new_content = parts[0] + parts[1]
        elif remove or parts is not None:
            new_content = content
        else:
            indent, body = _indent_and_rest(content)
            new_content = indent + "> " + body
        placeholder = (len(new_content), len(new_content)) if not content.strip() else None
        result.append((new_content, placeholder))
    return result


def _plan_prefixed_block(
    text: str,
    lines: Sequence[_Line],
    group: _BlockGroup,
    action: str,
    options: Mapping[str, object],
) -> _Operation:
    selected_lines = lines[group.first_line : group.last_line + 1]
    contents = [text[line.start : line.end] for line in selected_lines]
    start = selected_lines[0].start
    end = selected_lines[-1].end

    if action == "horizontal_rule":
        remove = all(_is_horizontal_rule(content) for content in contents)
        if not remove and any(content.strip() for content in contents):
            indent, _ = _indent_and_rest(contents[-1])
            eol = _preferred_eol(text, start, end)
            replacement = _isolated_block_replacement(text, start, end, indent + "---", eol)
            return _Operation(
                start,
                end,
                replacement,
                _clamped_selection_specs(group.members, start, end),
            )
        rewritten: List[Tuple[str, Optional[Tuple[int, int]]]] = []
        for content in contents:
            indent, _ = _indent_and_rest(content)
            new_content = indent if remove else indent + "---"
            placeholder = (len(new_content), len(new_content)) if not content.strip() else None
            rewritten.append((new_content, placeholder))
    elif action == "blockquote":
        rewritten = _rewrite_blockquote(contents)
    elif action.startswith("heading_") or action in {
        "unordered_list", "ordered_list", "task_list", "toggle_task",
    }:
        # Work on the text after any blockquote markers and leave those in
        # place.  Blank lines inside a selection that has content stay blank
        # and do not take part in the toggle decision.
        split = [_split_quote_prefix(content) for content in contents]
        active = [index for index, (_, body) in enumerate(split) if body.strip()]
        if not active:
            active = list(range(len(split)))
        bodies = [split[index][1] for index in active]
        if action.startswith("heading_"):
            changed = _rewrite_heading(bodies, int(action.rsplit("_", 1)[1]))
        else:
            changed = _rewrite_list(bodies, action, str(options["bullet_marker"]))
        rewritten = [(content, None) for content in contents]
        for index, (new_body, placeholder) in zip(active, changed):
            quote = split[index][0]
            if placeholder is not None:
                placeholder = (placeholder[0] + len(quote), placeholder[1] + len(quote))
            rewritten[index] = (quote + new_body, placeholder)
    else:
        raise ValueError("not a line-prefix action")

    new_contents = [new_content for new_content, _ in rewritten]
    output_parts: List[str] = []
    output_starts: List[int] = []
    output_length = 0
    for offset, (line, new_content) in enumerate(zip(selected_lines, new_contents)):
        output_starts.append(output_length)
        output_parts.append(new_content)
        output_length += len(new_content)
        if offset + 1 < len(selected_lines):
            separator = text[line.end : selected_lines[offset + 1].start]
            output_parts.append(separator)
            output_length += len(separator)
    replacement = "".join(output_parts)

    # Map selections line by line: only each line's prefix changes and the
    # separators are copied, so this is exact and linear in the selection
    # count (no whole-block diff).
    line_starts = [line.start for line in selected_lines]
    first_index = group.first_line

    def relative(position: int) -> int:
        if position < start:
            return position - start
        if position > end:
            return len(replacement) + position - end
        offset = bisect_right(line_starts, position) - 1
        line = selected_lines[offset]
        local = position - line.start
        old_length = line.end - line.start
        if local > old_length:
            return output_starts[offset] + len(new_contents[offset]) + local - old_length
        return output_starts[offset] + _line_offset_map(contents[offset], new_contents[offset], local)

    specs: Dict[int, Tuple[int, int]] = {}
    for member in group.members:
        placeholder = None
        if member.a == member.b and member.line_index is not None:
            offset = member.line_index - first_index
            placeholder = rewritten[offset][1]
        if placeholder is not None:
            base = output_starts[offset]
            specs[member.index] = (base + placeholder[0], base + placeholder[1])
        else:
            specs[member.index] = (relative(member.desired_a), relative(member.desired_b))
    return _Operation(start, end, replacement, specs)


def _preferred_eol(text: str, start: int, end: int) -> str:
    match = re.search(r"\r\n|\n|\r", text[start:end])
    if match is None:
        match = re.search(r"\r\n|\n|\r", text)
    return match.group(0) if match is not None else "\n"


def _fence_parts(content: str) -> Optional[Tuple[str, str, str]]:
    match = re.match(r"^([ \t]*)(`{3,}|~{3,})(.*)$", content)
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3)


def _find_enclosing_fence(
    text: str,
    lines: Sequence[_Line],
    group: _BlockGroup,
) -> Optional[Tuple[int, int]]:
    opening_index: Optional[int] = None
    character, length = "", 0
    for index, line in enumerate(lines):
        parts = _fence_parts(text[line.start:line.end])
        if parts is None:
            continue
        if opening_index is None:
            if line.newline_end == line.end:
                continue
            opening_index = index
            character, length = parts[1][0], len(parts[1])
        elif parts[1][0] == character and len(parts[1]) >= length and not parts[2].strip():
            if opening_index <= group.first_line and group.last_line <= index:
                return opening_index, index
            # A closing fence is consumed, never reconsidered as an opener.
            opening_index = None
    return None


def _plan_fenced_code(
    text: str,
    lines: Sequence[_Line],
    group: _BlockGroup,
    language: str,
) -> _Operation:
    enclosing = _find_enclosing_fence(text, lines, group)
    if enclosing is not None:
        opening_index, closing_index = enclosing
        opening_line = lines[opening_index]
        closing_line = lines[closing_index]
        content_start = opening_line.newline_end
        content = text[content_start : closing_line.start]
        if closing_index > opening_index + 1:
            previous_line = lines[closing_index - 1]
            separator = text[previous_line.end : closing_line.start]
            if separator and content.endswith(separator):
                content = content[: -len(separator)]
        wrapper = (opening_line.start, closing_line.end, content_start, content_start + len(content))
        return _unwrap_operation(wrapper, content, group.members)

    selected_lines = lines[group.first_line : group.last_line + 1]
    start, end = selected_lines[0].start, selected_lines[-1].end
    old = text[start:end]
    placeholder_mode = not old.strip()
    content = "code" if placeholder_mode else old
    longest = max((length for _, _, length in _backtick_runs(content)), default=0)
    fence = "`" * max(3, longest + 1)
    eol = _preferred_eol(text, start, end)
    # Fences inside a list item or another indented block keep its indentation.
    indent = _common_indentation(
        [row for row in (text[line.start : line.end] for line in selected_lines) if row.strip()]
    )
    opening = indent + fence + language + eol
    operation = _wrap_operation(
        _InlineGroup(start, end, group.members), opening, content, eol + indent + fence, False,
    )
    if placeholder_mode:
        for member in group.members:
            if member.a == member.b:
                operation.selection_specs[member.index] = (len(opening), len(opening) + len(content))
    return operation


def _escape_table_cell(cell: str) -> str:
    return cell.replace("\\", "\\\\").replace("|", "\\|")


def _common_indentation(rows: Sequence[str]) -> str:
    indents = [_indent_and_rest(row)[0] for row in rows if row]
    if not indents:
        return ""
    common = indents[0]
    for indent in indents[1:]:
        limit = min(len(common), len(indent))
        index = 0
        while index < limit and common[index] == indent[index]:
            index += 1
        common = common[:index]
    return common


def _render_table(
    indent: str,
    rows: Sequence[Sequence[str]],
    eol: str,
    alignments: Sequence[str] = (),
) -> str:
    """Render a padded pipe table; ``rows[0]`` is the header.

    ``alignments`` holds ``"left"``, ``"right"``, ``"center"`` or ``""`` per
    column (missing columns are unaligned).
    """
    column_count = max(len(row) for row in rows)
    normalized = [list(row) + [""] * (column_count - len(row)) for row in rows]
    aligned = list(alignments)[:column_count]
    aligned += [""] * (column_count - len(aligned))
    widths = [
        max(3, max(len(row[column]) for row in normalized))
        for column in range(column_count)
    ]

    def render_cell(cell: str, column: int) -> str:
        if aligned[column] == "right":
            return cell.rjust(widths[column])
        if aligned[column] == "center":
            return cell.center(widths[column])
        return cell.ljust(widths[column])

    def delimiter(column: int) -> str:
        width, alignment = widths[column], aligned[column]
        if alignment == "left":
            return ":" + "-" * (width - 1)
        if alignment == "right":
            return "-" * (width - 1) + ":"
        if alignment == "center":
            return ":" + "-" * (width - 2) + ":"
        return "-" * width

    def render_row(row: Sequence[str]) -> str:
        cells = [render_cell(row[column], column) for column in range(column_count)]
        return indent + "| " + " | ".join(cells) + " |"

    output = [render_row(normalized[0])]
    output.append(indent + "| " + " | ".join(delimiter(column) for column in range(column_count)) + " |")
    output.extend(render_row(row) for row in normalized[1:])
    return eol.join(output)


def _split_table_row(row: str) -> Optional[List[str]]:
    """Split a pipe-table row on unescaped pipes; None when it has no pipe."""
    row = row.strip()
    cells: List[str] = []
    current: List[str] = []
    index = 0
    leading = trailing = False
    while index < len(row):
        character = row[index]
        trailing = False
        if character == "\\" and index + 1 < len(row):
            current.append(row[index : index + 2])
            index += 2
            continue
        if character == "|":
            leading = leading or (not cells and not current)
            cells.append("".join(current))
            current = []
            trailing = True
        else:
            current.append(character)
        index += 1
    if not cells:
        return None
    cells.append("".join(current))
    if leading:
        cells = cells[1:]
    if trailing and cells:
        cells = cells[:-1]
    return [cell.strip() for cell in cells]


_TABLE_DELIMITER_CELL_RE = re.compile(r":?-+:?")


def _parse_pipe_table(rows: Sequence[str]) -> Optional[Tuple[List[List[str]], List[str]]]:
    """Return ``(cell rows without the delimiter row, alignments)`` or None."""
    if len(rows) < 2 or not all(row.strip() for row in rows):
        return None
    header = _split_table_row(rows[0])
    delimiter = _split_table_row(rows[1])
    if not header or not delimiter or len(header) != len(delimiter):
        return None
    if not all(_TABLE_DELIMITER_CELL_RE.fullmatch(cell) for cell in delimiter):
        return None
    alignments = [
        "center" if cell.startswith(":") and cell.endswith(":")
        else "left" if cell.startswith(":")
        else "right" if cell.endswith(":")
        else ""
        for cell in delimiter
    ]
    body: List[List[str]] = []
    for row in rows[2:]:
        cells = _split_table_row(row)
        body.append(cells if cells is not None else [row.strip()])
    return [header] + body, alignments


def _table_block(
    text: str,
    lines: Sequence[_Line],
    group: _BlockGroup,
) -> Tuple[int, int]:
    """Widen the group to the surrounding pipe-table lines, if it is in one."""
    def is_row(index: int) -> bool:
        content = text[lines[index].start : lines[index].end]
        return bool(content.strip()) and _split_table_row(content) is not None

    first, last = group.first_line, group.last_line
    if not all(is_row(index) for index in range(first, last + 1)):
        return first, last
    while first > 0 and is_row(first - 1):
        first -= 1
    while last + 1 < len(lines) and is_row(last + 1):
        last += 1
    return first, last


def _plan_existing_table(
    text: str,
    lines: Sequence[_Line],
    group: _BlockGroup,
) -> Optional[_Operation]:
    """Re-align an existing GFM pipe table touched by the group."""
    first, last = _table_block(text, lines, group)
    table_lines = lines[first : last + 1]
    raw_rows = [text[line.start : line.end] for line in table_lines]
    parsed = _parse_pipe_table(raw_rows)
    if parsed is None:
        return None
    rows, alignments = parsed
    start, end = table_lines[0].start, table_lines[-1].end
    eol = _preferred_eol(text, start, end)
    indent = _common_indentation(raw_rows)
    new_rows = _render_table(indent, rows, eol, alignments).split(eol)
    return _row_mapped_operation(text, table_lines, raw_rows, new_rows, eol, group.members, 0)


def _row_mapped_operation(
    text: str,
    table_lines: Sequence[_Line],
    raw_rows: Sequence[str],
    new_rows: Sequence[str],
    eol: str,
    members: Iterable[_Member],
    inserted_after_header: int,
) -> _Operation:
    """Replace the lines with ``new_rows`` and map selections row by row.

    Old row ``i`` becomes new row ``i``, shifted by ``inserted_after_header``
    for every row after the first (a delimiter row inserted below a header).
    """
    start, end = table_lines[0].start, table_lines[-1].end
    output_starts: List[int] = []
    length = 0
    for new_row in new_rows:
        output_starts.append(length)
        length += len(new_row) + len(eol)
    replacement = eol.join(new_rows)
    line_starts = [line.start for line in table_lines]

    def relative(position: int) -> int:
        if position < start:
            return position - start
        if position > end:
            return len(replacement) + position - end
        row = bisect_right(line_starts, position) - 1
        local = position - table_lines[row].start
        target = row + (inserted_after_header if row else 0)
        old_row, new_row = raw_rows[row], new_rows[target]
        if local > len(old_row):
            return output_starts[target] + len(new_row) + min(local - len(old_row), len(eol))
        return output_starts[target] + _diff_position(old_row, new_row, local, "right")

    specs = {
        member.index: (relative(member.desired_a), relative(member.desired_b))
        for member in members
    }
    return _Operation(start, end, replacement, specs)


def _plan_table(
    text: str,
    lines: Sequence[_Line],
    group: _BlockGroup,
) -> _Operation:
    existing = _plan_existing_table(text, lines, group)
    if existing is not None:
        return existing

    selected_lines = lines[group.first_line : group.last_line + 1]
    start, end = selected_lines[0].start, selected_lines[-1].end
    raw_rows = [text[line.start : line.end] for line in selected_lines]
    eol = _preferred_eol(text, start, end)
    indent = _common_indentation(raw_rows)
    has_tabs = any("\t" in row for row in raw_rows)
    has_nonblank = any(row.strip() for row in raw_rows)
    placeholder_rows = [
        ["Header 1", "Header 2"],
        ["Cell 1", "Cell 2"],
        ["Cell 3", "Cell 4"],
    ]

    if has_nonblank and all(member.a == member.b for member in group.members):
        table = _render_table(indent, placeholder_rows, eol)
        replacement = _isolated_block_replacement(text, start, end, table, eol)
        header_start = (end - start) + 2 * len(eol) + len(indent) + 2
        specs = {
            member.index: (header_start, header_start + len("Header 1"))
            for member in group.members
        }
        return _Operation(start, end, replacement, specs)

    if has_tabs:
        rows = []
        for row in raw_rows:
            if indent and row.startswith(indent):
                row = row[len(indent) :]
            rows.append([_escape_table_cell(cell.strip()) for cell in row.split("\t")])
        new_rows = _render_table(indent, rows, eol).split(eol)
        return _row_mapped_operation(text, selected_lines, raw_rows, new_rows, eol, group.members, 1)

    if has_nonblank:
        rows = []
        for row in raw_rows:
            if indent and row.startswith(indent):
                row = row[len(indent) :]
            rows.append([_escape_table_cell(row.strip())])
        new_rows = _render_table(indent, rows, eol).split(eol)
        return _row_mapped_operation(text, selected_lines, raw_rows, new_rows, eol, group.members, 1)

    replacement = _render_table(indent, placeholder_rows, eol)
    header_start = len(indent) + 2
    specs = {
        member.index: (header_start, header_start + len("Header 1"))
        for member in group.members
    }
    return _Operation(start, end, replacement, specs)


def _next_footnote_label(used: set, counter: int) -> Tuple[str, int]:
    """Next free ``note``/``noteN`` label; ``used`` holds casefolded labels."""
    while True:
        label = "note" if counter == 1 else "note{0}".format(counter)
        counter += 1
        if label.casefold() not in used:
            used.add(label.casefold())
            return label, counter


def _footnote_content(content: str, eol: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", eol + "    ")


def _plan_footnotes(
    text: str,
    groups: Sequence[_InlineGroup],
) -> List[_Operation]:
    # Footnote labels match case-insensitively, like link reference labels.
    used = {label.casefold() for label in re.findall(r"\[\^([^\]\r\n]+)\]", text)}
    counter = 1
    body_operations: List[_Operation] = []
    definitions: List[str] = []
    definition_specs: Dict[int, Tuple[int, int]] = {}
    eol = _preferred_eol(text, 0, len(text))
    definitions_length = 0

    for group in groups:
        label, counter = _next_footnote_label(used, counter)
        placeholder_mode = group.start == group.end
        raw_content = "Footnote text" if placeholder_mode else text[group.start : group.end]
        rendered_content = _footnote_content(raw_content, eol)
        marker = "[^" + label + "]"
        body_operations.append(_Operation(group.start, group.end, marker, {}))

        definition = "[^" + label + "]: " + rendered_content
        if definitions:
            definitions_length += len(eol)
        definition_start = definitions_length + len("[^" + label + "]: ")
        definitions.append(definition)
        definitions_length += len(definition)

        for member in group.members:
            if placeholder_mode:
                definition_specs[member.index] = (
                    definition_start,
                    definition_start + len(rendered_content),
                )
            else:
                relative_a = member.desired_a - group.start
                relative_b = member.desired_b - group.start
                definition_specs[member.index] = (
                    definition_start
                    + _diff_position(raw_content, rendered_content, relative_a, "right"),
                    definition_start
                    + _diff_position(raw_content, rendered_content, relative_b, "right"),
                )

    if not definitions:
        return []

    if text.endswith(eol + eol):
        separator = ""
    elif text.endswith(eol):
        separator = eol
    else:
        separator = eol + eol
    append_text = separator + eol.join(definitions)
    shifted_specs = {
        index: (start + len(separator), end + len(separator))
        for index, (start, end) in definition_specs.items()
    }
    body_operations.append(
        _Operation(len(text), len(text), append_text, shifted_specs)
    )
    return body_operations


def _normalize_operations(operations: Sequence[_Operation]) -> List[_Operation]:
    for order, operation in enumerate(operations):
        operation.order = order
    sorted_operations = sorted(
        operations,
        key=lambda operation: (operation.start, -(operation.end - operation.start), operation.order),
    )

    deduplicated: List[_Operation] = []
    for operation in sorted_operations:
        duplicate = next(
            (
                existing
                for existing in reversed(deduplicated)
                if existing.start == operation.start
                and existing.end == operation.end
                and existing.text == operation.text
            ),
            None,
        )
        if duplicate is not None:
            duplicate.selection_specs.update(operation.selection_specs)
            continue
        deduplicated.append(operation)

    previous_end = 0
    have_previous = False
    for operation in deduplicated:
        if have_previous and operation.start < previous_end:
            raise ValueError("formatting selections produce overlapping edits")
        previous_end = max(previous_end, operation.end)
        have_previous = True
    return deduplicated


def _finalize(
    text: str,
    original_selections: Sequence[Tuple[int, int]],
    operations: Sequence[_Operation],
) -> FormatResult:
    normalized = _normalize_operations(operations)
    pieces: List[str] = []
    cursor = 0
    output_length = 0
    result_selections: List[Optional[Tuple[int, int]]] = [None] * len(original_selections)

    for operation in normalized:
        untouched = text[cursor : operation.start]
        pieces.append(untouched)
        output_length += len(untouched)
        operation.final_start = output_length
        pieces.append(operation.text)
        output_length += len(operation.text)
        cursor = operation.end
        for index, (relative_a, relative_b) in operation.selection_specs.items():
            result_selections[index] = (
                operation.final_start + relative_a,
                operation.final_start + relative_b,
            )

    pieces.append(text[cursor:])
    final_text = "".join(pieces)

    def map_fallback(position: int) -> int:
        delta = 0
        for operation in normalized:
            if position < operation.start:
                return position + delta
            if operation.start <= position <= operation.end:
                old = text[operation.start : operation.end]
                return operation.final_start + _diff_position(
                    old,
                    operation.text,
                    position - operation.start,
                    "right",
                )
            delta += len(operation.text) - (operation.end - operation.start)
        return position + delta

    for index, selection in enumerate(result_selections):
        if selection is None:
            a, b = original_selections[index]
            result_selections[index] = (map_fallback(a), map_fallback(b))

    replacements = tuple(
        Replacement(operation.start, operation.end, operation.text)
        for operation in normalized
    )

    rebuilt = text
    for replacement in reversed(replacements):
        rebuilt = (
            rebuilt[: replacement.start]
            + replacement.text
            + rebuilt[replacement.end :]
        )
    if rebuilt != final_text:
        raise RuntimeError("edit plan does not reconstruct formatted text")

    return FormatResult(
        final_text,
        tuple(selection for selection in result_selections if selection is not None),
        replacements,
    )


_STATIC_TEMPLATES = {
    "html_comment": ("<!-- ", " -->", "comment"),
    "insertion": ("<ins>", "</ins>", "text"),
    "critic_addition": ("{++", "++}", "text"),
    "critic_deletion": ("{--", "--}", "text"),
    "critic_highlight": ("{==", "==}", "text"),
    "critic_comment": ("{>>", "<<}", "comment"),
}

# Inline wrappers applied line by line when a selection crosses a blank line or
# the start of another block, where one wrapper would be invalid markup.
# HTML comments may legitimately span blocks and stay whole.
_PER_LINE_ACTIONS = {
    "bold",
    "italic",
    "bold_italic",
    "strikethrough",
    "inline_code",
    "insertion",
    "critic_addition",
    "critic_deletion",
    "critic_highlight",
    "critic_comment",
    "custom",
}

# A line that starts a new block (quote, list item, heading, fence).
_BLOCK_START_RE = re.compile(
    r"[ ]{0,3}(?:>|[-+*](?:[ \t]|$)|\d{1,9}[.)](?:[ \t]|$)|#{1,6}(?:[ \t]|$)|`{3,}|~{3,})"
)
# Block markup in front of a line's inline content: quote markers,
# indentation, a list marker with optional task box, or heading hashes.
_BLOCK_PREFIX_RE = re.compile(
    r"(?:[ ]{0,3}>[ ]?)*[ \t]*"
    r"(?:(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$)(?:\[[ xX]\](?:[ \t]+|$))?|#{1,6}(?:[ \t]+|$))?"
)

_Planner = Callable[[str, _InlineGroup], Optional[_Operation]]


def _is_intraword(text: str, group: _InlineGroup) -> bool:
    """True when the selection sits inside a word, as ``y`` in ``x_y_z``.

    Runs of ``*`` and ``_`` around the selection are skipped before looking
    for letters or digits, so ``x_*y*_z`` still counts as intraword (and its
    asterisk emphasis toggles back off) while ``__hello__`` does not.
    """
    before, after = group.start, group.end
    while before > 0 and text[before - 1] in "*_":
        before -= 1
    while after < len(text) and text[after] in "*_":
        after += 1
    return (0 < before and after < len(text)
            and text[before - 1].isalnum() and text[after].isalnum())


def _inline_planner(action: str, options: Mapping[str, object], document: str) -> _Planner:
    """Planner for one inline action.

    Scans of ``document`` (marker pairs, code spans) are computed once and
    reused for every group; per-line planning passes other texts, which are
    scanned afresh.
    """
    cache: Dict[tuple, object] = {}

    def cache_for(text: str) -> Optional[Dict[tuple, object]]:
        return cache if text is document else None

    if action in {"bold", "italic", "bold_italic", "strikethrough"}:
        strong = str(options["strong_marker"])
        emphasis = str(options["emphasis_marker"])
        prefix, suffix = {
            "bold": (strong, strong),
            "italic": (emphasis, emphasis),
            "bold_italic": (strong + emphasis, emphasis + strong),
            "strikethrough": ("~~", "~~"),
        }[action]
        def plan_emphasis(text: str, group: _InlineGroup) -> Optional[_Operation]:
            # "_" emphasis does not work inside a word in CommonMark/GFM, so an
            # intraword selection uses "*", which does (and toggles back the same way).
            if "_" in prefix + suffix and _is_intraword(text, group):
                return _plan_common_inline(text, group, prefix.replace("_", "*"),
                                           suffix.replace("_", "*"), cache_for(text))
            return _plan_common_inline(text, group, prefix, suffix, cache_for(text))
        return plan_emphasis
    if action in _STATIC_TEMPLATES or action == "custom":
        if action == "custom":
            template = (str(options["prefix"]), str(options["suffix"]), str(options["placeholder"]))
        else:
            template = _STATIC_TEMPLATES[action]
        return lambda text, group: _plan_static_inline(
            text, group, *template, cache=cache_for(text)
        )
    if action == "inline_code":
        spans = _code_spans(document)
        return lambda text, group: _plan_inline_code(
            text, group, spans if text is document else None
        )
    if action == "critic_substitution":
        return _plan_substitution
    raise ValueError("unsupported action: {0}".format(action))


def _uses_per_line(action: str, options: Mapping[str, object]) -> bool:
    if action not in _PER_LINE_ACTIONS:
        return False
    if action != "custom":
        return True
    prefix, suffix = str(options["prefix"]), str(options["suffix"])
    return bool(prefix and suffix) and not any(
        character in prefix + suffix for character in "\r\n"
    )


def _block_crossing_lines(
    text: str,
    lines: Sequence[_Line],
    newline_ends: Sequence[int],
    group: _InlineGroup,
) -> Optional[Tuple[int, int]]:
    """Lines of a group that crosses a blank line or another block's start."""
    if group.start == group.end:
        return None
    first = _line_index_for_offset(newline_ends, group.start)
    last = _line_index_for_offset(newline_ends, group.end - 1)
    if first == last:
        return None
    for index in range(first, last + 1):
        content = text[lines[index].start : lines[index].end]
        if not content.strip() or (index > first and _BLOCK_START_RE.match(content)):
            return first, last
    return None


def _plan_per_line(
    text: str,
    lines: Sequence[_Line],
    first: int,
    last: int,
    group: _InlineGroup,
    planner: _Planner,
) -> Optional[_Operation]:
    """Apply an inline wrapper to each selected line's inline content.

    Every non-blank line is planned on its own, after its block markup.  When
    all of them are already wrapped they are all unwrapped; otherwise only the
    unwrapped lines get the wrapper.  The per-line edits are merged into one
    operation so the result stays a single edit for the group.
    """
    pieces: List[Tuple[int, int, _Operation]] = []
    for line in lines[first : last + 1]:
        content = text[line.start : line.end]
        prefix = _BLOCK_PREFIX_RE.match(content)
        assert prefix is not None
        segment_start = max(group.start, line.start + prefix.end())
        segment_end = min(group.end, line.end)
        # Wrap the line's text, not the whitespace around it.
        while segment_start < segment_end and text[segment_start].isspace():
            segment_start += 1
        while segment_end > segment_start and text[segment_end - 1].isspace():
            segment_end -= 1
        if segment_start >= segment_end:
            continue
        base = line.start

        def local(position: int) -> int:
            return max(segment_start, min(position, segment_end)) - base

        members = [
            _Member(
                index=index,
                a=member.a,
                b=member.b,
                target_start=segment_start - base,
                target_end=segment_end - base,
                desired_a=local(member.desired_a),
                desired_b=local(member.desired_b),
            )
            for index, member in enumerate(group.members)
        ]
        # Plan against the line alone: per-line wrappers never span lines.
        operation = planner(content, _InlineGroup(segment_start - base, segment_end - base, members))
        if operation is None:
            continue
        operation.start += base
        operation.end += base
        pieces.append((segment_start, segment_end, operation))

    if not pieces:
        return None
    unwrap = all(operation.unwrapped for _, _, operation in pieces)
    if not unwrap:
        pieces = [piece for piece in pieces if not piece[2].unwrapped]

    start, end = pieces[0][2].start, pieces[-1][2].end
    parts: List[str] = []
    new_starts: List[int] = []
    length = 0
    cursor = start
    for _, _, operation in pieces:
        gap = text[cursor : operation.start]
        parts.append(gap)
        length += len(gap)
        new_starts.append(length)
        parts.append(operation.text)
        length += len(operation.text)
        cursor = operation.end
    replacement = "".join(parts)

    def relative(position: int, index: int, end_index: int) -> int:
        for (segment_start, segment_end, operation), new_start in zip(pieces, new_starts):
            if position < min(segment_start, operation.start):
                # Unchanged text before this piece.
                return new_start - (operation.start - position)
            if position <= max(segment_end, operation.end):
                return new_start + operation.selection_specs[index][end_index]
        return len(replacement) + position - end

    specs = {
        member.index: (relative(member.desired_a, index, 0), relative(member.desired_b, index, 1))
        for index, member in enumerate(group.members)
    }
    return _Operation(start, end, replacement, specs, unwrapped=unwrap)


def _merge_touching_groups(groups: Sequence[_InlineGroup]) -> List[_InlineGroup]:
    """Merge non-empty groups that touch, e.g. ``a`` and ``b`` in ``ab``.

    Two code spans cannot touch (their backtick runs would merge), so
    adjacent selections become one span.
    """
    merged: List[_InlineGroup] = []
    for group in groups:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.start < previous.end == group.start < group.end
        ):
            merged[-1] = _InlineGroup(previous.start, group.end, previous.members + group.members)
        else:
            merged.append(group)
    return merged


def format_document(
    text: str,
    selections: List[Tuple[int, int]],
    action: str,
    options: Optional[dict] = None,
) -> FormatResult:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if not isinstance(action, str) or action not in _SUPPORTED_ACTIONS:
        raise ValueError("unsupported action: {0}".format(action))

    validated = _validated_selections(text, selections)
    resolved = _validated_options(action, options)
    if not validated:
        return FormatResult(text, (), ())

    operations: List[_Operation] = []

    if action == "footnote":
        groups = _inline_groups(
            text,
            validated,
            bool(resolved["select_word_on_empty"]),
        )
        operations.extend(_plan_footnotes(text, groups))
        return _finalize(text, validated, operations)

    if action in _BLOCK_ACTIONS or action.startswith("heading_"):
        lines, block_groups = _block_groups(text, validated)
        for block_group in block_groups:
            if action == "fenced_code":
                operations.append(
                    _plan_fenced_code(
                        text,
                        lines,
                        block_group,
                        str(resolved["fence_language"]),
                    )
                )
            elif action == "table":
                operations.append(_plan_table(text, lines, block_group))
            else:
                operations.append(
                    _plan_prefixed_block(text, lines, block_group, action, resolved)
                )
        return _finalize(text, validated, operations)

    groups = _inline_groups(
        text,
        validated,
        bool(resolved["select_word_on_empty"]),
    )

    if action in {"link", "image"}:
        links = _LinkIndex(text)
        previous_end = 0
        for group in groups:
            operations.append(
                _plan_link(
                    text,
                    group,
                    action == "image",
                    str(resolved["link_url"]),
                    links,
                    # Escaping a "!" in front must not touch a previous edit.
                    escape_bang=previous_end < group.start,
                )
            )
            previous_end = group.end
        return _finalize(text, validated, operations)

    if action == "inline_code":
        groups = _merge_touching_groups(groups)
    planner = _inline_planner(action, resolved, text)
    per_line = _uses_per_line(action, resolved)
    lines: Optional[List[_Line]] = None
    newline_ends: List[int] = []
    for group in groups:
        crossing = None
        if per_line and group.start < group.end and (
            "\n" in text[group.start : group.end] or "\r" in text[group.start : group.end]
        ):
            if lines is None:
                lines = _document_lines(text)
                newline_ends = [line.newline_end for line in lines]
            crossing = _block_crossing_lines(text, lines, newline_ends, group)
        if crossing is not None:
            assert lines is not None
            operation = _plan_per_line(text, lines, crossing[0], crossing[1], group, planner)
        else:
            operation = planner(text, group)
        if operation is not None:
            operations.append(operation)

    return _finalize(text, validated, operations)
