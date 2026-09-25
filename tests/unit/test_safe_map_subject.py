"""The subject mapper's result is checked before it becomes an identity.

`safe_map_subject` is the one place both token verifiers turn an
`(issuer, subject)` pair from a bearer token into a principal id, so it
is the one place a bad mapping can be refused. It had no test at all,
which is how the escalation guard below came to depend on two constants
happening to be equal without anything saying so.

The mapper is supplied by configuration. A deployment can point it at a
static table or at a lookup, so its output is an input to this process,
not an invariant of it.
"""

from uuid import UUID, uuid4

import pytest

from keeper.infrastructure.adapters.jwt_token_verifier import safe_map_subject
from keeper.infrastructure.ports.token_verifier import InvalidTokenError, PrincipalKind
from keeper.shared.reserved_ids import NIL_SENTINEL_ID, SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.unit


def _mapper_returning(principal_id: UUID, kind: str = "human"):
    async def mapper(issuer: str, subject: str) -> tuple[UUID, PrincipalKind]:
        _ = (issuer, subject)
        return principal_id, kind  # pyright: ignore[reportReturnType]

    return mapper


async def test_safe_map_subject_returns_the_mapping_when_the_mapper_succeeds() -> None:
    expected = uuid4()
    got, kind = await safe_map_subject(_mapper_returning(expected), "https://idp", "alice")
    assert (got, kind) == (expected, "human")


async def test_safe_map_subject_refuses_a_mapping_to_the_system_principal() -> None:
    """A valid token must not be able to resolve to the fallback identity.

    `SYSTEM_PRINCIPAL_ID` is what an unauthenticated request runs as
    under the dev posture. A bearer token reaching it would let anyone
    holding a token the IdP will sign act as the system account.
    """
    with pytest.raises(InvalidTokenError, match="system principal"):
        await safe_map_subject(_mapper_returning(SYSTEM_PRINCIPAL_ID), "https://idp", "alice")


async def test_safe_map_subject_refuses_a_mapping_to_the_nil_sentinel() -> None:
    """Unspecified is not an identity, whatever the system principal is.

    Checked separately from the case above rather than folded into it.
    The two constants were the same UUID once, and a single check would
    silently stop covering one of them the next time a value moves.
    """
    with pytest.raises(InvalidTokenError, match="nil sentinel"):
        await safe_map_subject(_mapper_returning(NIL_SENTINEL_ID), "https://idp", "alice")


async def test_safe_map_subject_refuses_a_kind_outside_the_closed_set() -> None:
    with pytest.raises(InvalidTokenError, match="expected one of"):
        await safe_map_subject(_mapper_returning(uuid4(), "wizard"), "https://idp", "alice")


async def test_safe_map_subject_wraps_a_raising_mapper_as_unknown_subject() -> None:
    async def mapper(issuer: str, subject: str) -> tuple[UUID, PrincipalKind]:
        _ = (issuer, subject)
        raise RuntimeError("projection unavailable")

    with pytest.raises(InvalidTokenError, match="subject mapper raised"):
        await safe_map_subject(mapper, "https://idp", "alice")
