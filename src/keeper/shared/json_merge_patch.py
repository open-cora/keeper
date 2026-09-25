"""RFC 7396 JSON Merge Patch implementation.

The canonical merge-semantics helper for any PATCH-shaped update to a
freeform values dict: a null member deletes the key, a non-null member
replaces it, and a nested object recurses.

It sits in the shared kernel rather than at a carrier aggregate because a
second implementation would be a second reading of the same RFC, and a PATCH
that deletes a key on one path and keeps it on another is a data bug that
looks like a merge preference.

## Why RFC 7396 rather than RFC 6902

The two RFCs answer different questions. RFC 7396 asks "what should this
document look like afterwards", which is what a PATCH body naturally
expresses for a flat-ish object of primitive values. RFC 6902 asks "what
operations should be applied", an array of typed ops that is strictly
more expressive and strictly more to write, read and validate.

7396 is the right default because the cost of 6902 is paid at every call
site while its extra power is needed at none of them yet. A slice that
does need indexed array edits can adopt 6902 for itself; this module is
not in its way.

## What RFC 7396 cannot express

  - Setting a key TO null, because null is the delete sentinel. A field
    that must distinguish "absent" from "explicitly null" cannot be
    patched through this helper and should not be modelled as a freeform
    dict key.
  - Editing one element of an array. A whole array replaces a whole
    array, which is usually what a caller wants and occasionally not.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import copy
from collections.abc import Mapping
from typing import Any


def merge_patch(current: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """Apply RFC 7396 JSON Merge Patch semantics.

    Returns a NEW deeply-copied dict (does not alias `current` at any
    nesting depth):
      - keys in `patch` with non-null values: set / replace
      - keys in `patch` with null: deleted from result
      - keys absent from `patch`: preserved from `current`

    Recursive on nested dicts: `merge_patch({"a": {"b": 1}}, {"a":
    {"c": 2}}) == {"a": {"b": 1, "c": 2}}`. RFC 7396 says nested
    null also deletes (`merge_patch({"a": {"b": 1}}, {"a": {"b":
    null}}) == {"a": {}}`).

    The result is `copy.deepcopy`'d so caller mutations of the
    returned dict do not propagate into `current` or into the event
    payload that this dict becomes. AROC's parameter/settings dicts
    are typically small (5-30 keys), so deepcopy cost is negligible
    compared to the safety guarantee.

    Note: cannot represent "set key to null"; null is overloaded as
    the delete sentinel. AROC values are never null in practice.
    """
    result: dict[str, Any] = copy.deepcopy(dict(current))
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            # Recursive merge into existing nested dict
            result[key] = merge_patch(result[key], value)
        else:
            # Set / replace (including dict-into-non-dict and scalars).
            # Deep-copy the patch value so caller mutations of the
            # patch don't propagate into the result either.
            result[key] = copy.deepcopy(value)
    return result


__all__ = ["merge_patch"]
