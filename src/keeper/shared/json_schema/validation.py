"""Shared JSON Schema validators for the schema-validated-values pattern.

The pattern has two halves, and this module serves both:

  1. **Declarer aggregate** owns the optional schema. A schema mutation
     validates WELL-FORMEDNESS: that the submitted document parses, is
     Draft 2020-12, and stays inside the constrained subset.
  2. **Carrier aggregate** owns the values. A values mutation validates
     CONFORMANCE against whatever schema the declarer currently holds.

Each BC keeps its own typed error class so HTTP exception handlers stay
aligned with their BC namespace, and passes it in as a parameter. That
is why these are free functions taking `error_class` rather than a base
class BCs inherit: a shared base would couple the BCs to each other, and
a single shared error class would make a log aggregator unable to say
which BC refused the write.

Both halves use the same constrained subset
(`keeper.shared.json_schema.subset`) and the same `jsonschema-rs` Draft
2020-12 engine. The strict-by-default posture is uniform across both:
a missing schema plus non-empty values is a REJECT with operator-facing
guidance, not a silent accept. An operator who genuinely has nothing to
constrain declares an empty `{}` schema and says so.

See docs/reference/conventions.md for the four-cell posture table and
the authoring discipline a declared schema follows.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from collections.abc import Mapping
from typing import Any

import jsonschema_rs

from keeper.shared.json_schema.subset import DRAFT_2020_12_URI, check_subset

ALLOWED_UNIT_SYSTEMS: frozenset[str] = frozenset({"udunits", "ucum", "qudt", "iec61360", "ucefact"})
"""Closed namespace allowlist for the `unit.system` annotation. Each value names a unit
vocabulary whose codes are interpreted opaque-within-namespace:

  - ``udunits``: the scientific-data default (NeXus, netCDF and
    neighbours).
  - ``ucum``: clinical / cross-domain (HL7 FHIR, openEHR).
  - ``qudt``: linked-data / semantic-web; codes are IRIs.
  - ``iec61360``: Industry-4.0 / AAS submodel; codes are IRDIs.
  - ``ucefact``: UN/CEFACT Common Code, as used by schema.org's
    QuantitativeValue type.

Widening this set is a deliberate decision driven by a real consumer
appearing at a seam. Adding a system here does not buy automatic
conversion across namespaces. Nothing here converts between them, and
the boundary that first needs it is where that belongs."""


def validate_schema_declaration(
    schema: dict[str, Any],
    *,
    error_class: type[ValueError],
) -> None:
    """Validate that `schema` is a well-formed JSON Schema in AROC's
    constrained subset (declarer-side write-time check).

    Four failure modes, all raised as `error_class(reason)`:
      1. Missing or wrong `$schema` declaration
      2. Forbidden keyword used (per `subset.check_subset`)
      3. `unit` annotation present but malformed (per
         `validate_unit_annotations`)
      4. jsonschema-rs rejects the schema as malformed (for example an
         invalid `pattern` regex)

    Returns None on success. Caller persists the schema as-is; runtime
    validation of values against it reuses `validate_values_against_schema`
    below.

    Called on the DECLARER's write path, wherever an aggregate stores a
    schema another aggregate's values will be checked against.
    """
    declared = schema.get("$schema")
    if declared != DRAFT_2020_12_URI:
        msg = (
            f"$schema must be exactly {DRAFT_2020_12_URI!r} "
            f"(got: {declared!r}); AROC locks Draft 2020-12"
        )
        raise error_class(msg)

    check_subset(schema, path="<root>", error_class=error_class)

    validate_unit_annotations(schema, path="<root>", error_class=error_class)

    try:
        jsonschema_rs.Draft202012Validator(schema)
    except (jsonschema_rs.ValidationError, ValueError) as exc:
        msg = f"jsonschema-rs rejected the schema as malformed: {exc}"
        raise error_class(msg) from exc


def validate_unit_annotations(
    schema: Mapping[str, Any],
    *,
    path: str,
    error_class: type[ValueError],
) -> None:
    """Recursively validate any `unit` annotation in `schema` has the
    locked three-field shape (per the units convention in docs/reference/conventions.md).

    For every property whose declaration contains a `unit` key, the
    value must be a dict with:

      - REQUIRED ``system: str`` in `ALLOWED_UNIT_SYSTEMS`
      - REQUIRED ``code: str`` (non-empty)
      - OPTIONAL ``label: str``
      - No other keys

    Called from `validate_schema_declaration` after `check_subset`
    succeeds, so the underlying keyword whitelist is already known
    good. Recursion mirrors `check_subset`: execution `properties.<name>`
    for nested object properties.

    Raises `error_class(reason)` on the first violation. Returns None
    when no `unit` annotations are present (the common case for
    non-numeric schemas).
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        prop_path = f"{path}.properties.{prop_name}"
        if "unit" in prop_schema:
            _check_unit_annotation_shape(
                prop_schema["unit"],
                path=f"{prop_path}.unit",
                error_class=error_class,
            )
        validate_unit_annotations(prop_schema, path=prop_path, error_class=error_class)


_REQUIRED_UNIT_KEYS: frozenset[str] = frozenset({"system", "code"})
_OPTIONAL_UNIT_KEYS: frozenset[str] = frozenset({"label"})


def _check_unit_annotation_shape(
    annotation: Any,
    *,
    path: str,
    error_class: type[ValueError],
) -> None:
    if not isinstance(annotation, dict):
        msg = f"unit annotation at {path} must be a dict (got: {type(annotation).__name__})"
        raise error_class(msg)
    keys = set(annotation.keys())
    missing = _REQUIRED_UNIT_KEYS - keys
    if missing:
        msg = f"unit annotation at {path} missing required keys: {sorted(missing)}"
        raise error_class(msg)
    extra = keys - _REQUIRED_UNIT_KEYS - _OPTIONAL_UNIT_KEYS
    if extra:
        msg = (
            f"unit annotation at {path} has unknown keys: {sorted(extra)}; "
            f"allowed: {sorted(_REQUIRED_UNIT_KEYS | _OPTIONAL_UNIT_KEYS)}"
        )
        raise error_class(msg)
    system = annotation["system"]
    if not isinstance(system, str):
        msg = f"unit.system at {path} must be a string (got: {type(system).__name__})"
        raise error_class(msg)
    if system not in ALLOWED_UNIT_SYSTEMS:
        msg = (
            f"unit.system {system!r} at {path} is not in AROC's allowed "
            f"namespace list: {sorted(ALLOWED_UNIT_SYSTEMS)}"
        )
        raise error_class(msg)
    code = annotation["code"]
    if not isinstance(code, str) or not code:
        msg = f"unit.code at {path} must be a non-empty string"
        raise error_class(msg)
    if "label" in annotation:
        label = annotation["label"]
        if not isinstance(label, str):
            msg = f"unit.label at {path} must be a string (got: {type(label).__name__})"
            raise error_class(msg)


def validate_values_against_schema(
    values: Mapping[str, Any],
    schema: dict[str, Any] | None,
    *,
    error_class: type[ValueError],
    no_schema_message: str | None = None,
) -> None:
    """Validate a values dict against a JSON Schema (carrier-side
    write-time check).

    Two postures, picked by whether `no_schema_message` is supplied:

      - **STRICT** (`no_schema_message` provided): schema=None plus
        non-empty values rejects with the supplied message. This is the
        default posture, and the right one BEFORE an operator has
        committed to anything: it forces them to declare a schema
        rather than accept values nobody has said how to shape.
      - **RELAXED** (`no_schema_message=None`): schema=None always
        accepts, because the caller has already decided schemaless is
        acceptable at this checkpoint. The right posture AFTER an
        operator has committed and now carries responsibility for what
        they are steering; second-guessing them mid-flight is worse
        than trusting them. Such a caller typically early-returns on
        `schema is None` anyway, but passing `no_schema_message=None`
        makes the intent explicit and lets this helper own the dispatch.

    When `no_schema_message` is provided it MUST contain a `{keys}`
    placeholder, which is filled with a comma-separated list of the
    offending keys, sorted and single-quoted. A message without the
    placeholder raises `ValueError` here rather than at the call site,
    because `str.format` ignores a keyword nothing consumes: the caller
    would otherwise get a message missing the only part that says which
    values were refused, and nothing would say so.

    Behavior:
      - schema is None AND values is empty → accept (trivially valid)
      - schema is None AND values is non-empty AND no_schema_message
        is None → accept (RELAXED posture)
      - schema is None AND values is non-empty AND no_schema_message
        is provided → raise error_class with no_schema_message.format(keys=...)
      - schema is non-None AND values is empty → accept (no
        required-field check at this layer; `required` applies at the
        per-aggregate consumer point, where the values are finally
        resolved and acted on)
      - schema is non-None AND values is non-empty → compile via
        jsonschema-rs Draft 2020-12, run iter_errors, raise on first
        violation with path-prefixed diagnostic

    A carrier whose schema comes from SEVERAL declarers builds its union
    schema first and then calls this. The union step is BC-specific and
    does not belong here; the validation that follows it does.
    """
    if schema is None:
        if not values or no_schema_message is None:
            return
        if "{keys}" not in no_schema_message:
            msg = (
                "no_schema_message must contain a '{keys}' placeholder "
                f"(got: {no_schema_message!r})"
            )
            raise ValueError(msg)
        keys = ", ".join(f"'{k}'" for k in sorted(values.keys()))
        raise error_class(no_schema_message.format(keys=keys))

    if not values:
        return

    try:
        validator = jsonschema_rs.Draft202012Validator(schema)
    except (jsonschema_rs.ValidationError, ValueError) as exc:
        msg = f"jsonschema-rs failed to compile the schema: {exc}"
        raise error_class(msg) from exc

    errors = list(validator.iter_errors(dict(values)))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.instance_path) or "<root>"
        msg = f"validation failed at {path}: {first.message}"
        raise error_class(msg)


__all__ = [
    "ALLOWED_UNIT_SYSTEMS",
    "validate_schema_declaration",
    "validate_unit_annotations",
    "validate_values_against_schema",
]
