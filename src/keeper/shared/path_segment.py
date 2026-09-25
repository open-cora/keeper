"""Whether a string may be used as one path segment.

Lives in `keeper.shared` (`depends_on = []`) because both sides of a
remote-path seam need the SAME answer: the side that refuses to SEND an
unsafe segment, and the side that refuses to ACT on one, on the host where
the bytes actually land. Two copies of this rule would be two chances to
disagree, and the side that matters is whichever one is missing a case.

The values this guards are not authored here. A segment that arrives from
an external system is attacker-influenced whenever that system is writable
by someone who is not the caller, and it is then used to locate something on
a filesystem.

This is not shell-escaping, and it does not substitute for it: the narrower
rule is that a value said to name ONE path segment must not be able to name
a different directory, execution upward, or terminate a C string early.
"""

from __future__ import annotations

MAX_PATH_SEGMENT_LENGTH = 255
"""One segment's byte budget on the filesystems AROC reads (ext4, XFS,
NFS all cap a single name at 255). Longer is not a traversal risk, it
just cannot name a real entry, so refusing early keeps a pointless
round trip off the wire."""

_TRAVERSAL_SEGMENTS = frozenset({".", ".."})


def is_safe_path_segment(value: str) -> bool:
    """Whether `value` names exactly one ordinary path entry.

    Refuses the empty string, `.` and `..`, anything carrying a path
    separator or a NUL, and anything with leading or trailing
    whitespace. Whitespace is refused rather than stripped because a
    caller that meant to send `scan_005.h5 ` and a caller that meant
    `scan_005.h5` want different files, and silently picking one of
    them is how a probe reports a match for a path nobody asked about.

    Backslash is refused alongside `/` even though AROC reads POSIX
    hosts only: it costs nothing, and this rule is the kind that gets
    reused somewhere it was not written for.
    """
    if not value or len(value) > MAX_PATH_SEGMENT_LENGTH:
        return False
    if value in _TRAVERSAL_SEGMENTS:
        return False
    if value != value.strip():
        return False
    return not any(character in value for character in ("/", "\\", "\0"))


__all__ = ["MAX_PATH_SEGMENT_LENGTH", "is_safe_path_segment"]
