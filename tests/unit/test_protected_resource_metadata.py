"""The RFC 9728 document is a wire contract, so its shape is asserted whole.

Every client that discovers this deployment's auth reads exactly these keys.
A wrong `bearer_methods_supported`, a null audience, or a dropped
`aud_values_supported` is not a crash here; it is a client that cannot
authenticate and has no way to say why. None of that is reachable through the
endpoint test, which can only see that a 200 came back.
"""

from uuid import UUID

import pytest

from keeper.api.protected_resource_metadata import build_protected_resource_metadata
from keeper.infrastructure.auth.config import IdpConfig

pytestmark = pytest.mark.unit

_SURFACE = UUID("00000000-0000-0000-0000-000000000001")


def _idp(issuer: str) -> IdpConfig:
    return IdpConfig(
        issuer=issuer,
        audiences={_SURFACE: "aud-http"},
        jwks_url=f"{issuer}/jwks",
    )


def test_document_declares_header_as_the_only_bearer_method() -> None:
    document = build_protected_resource_metadata(
        resource="https://keeper.example", identity_providers=[], surface_audiences={}
    )
    assert document["bearer_methods_supported"] == ["header"]


def test_document_sorts_issuers_so_the_bytes_are_stable_across_restarts() -> None:
    document = build_protected_resource_metadata(
        resource="https://keeper.example",
        identity_providers=[_idp("https://zulu.example"), _idp("https://alpha.example")],
        surface_audiences={},
    )
    assert document["authorization_servers"] == [
        "https://alpha.example",
        "https://zulu.example",
    ]


def test_document_publishes_every_configured_audience_for_clients_to_choose_from() -> None:
    document = build_protected_resource_metadata(
        resource="https://keeper.example",
        identity_providers=[],
        surface_audiences={"http": "aud-http", "mcp_streamable_http": "aud-mcp"},
    )
    assert document["aud_values_supported"] == ["aud-http", "aud-mcp"]


def test_document_omits_aud_values_supported_when_no_surface_has_an_audience() -> None:
    document = build_protected_resource_metadata(
        resource="https://keeper.example",
        identity_providers=[],
        surface_audiences={"http": None},
    )
    assert "aud_values_supported" not in document


def test_document_drops_unconfigured_surfaces_rather_than_emitting_null() -> None:
    document = build_protected_resource_metadata(
        resource="https://keeper.example",
        identity_providers=[],
        surface_audiences={"http": "aud-http", "mcp_stdio": None},
    )
    assert document["io.keeper.surface_audiences"] == {"http": "aud-http"}


def test_document_namespaces_the_surface_map_rather_than_using_an_x_prefix() -> None:
    document = build_protected_resource_metadata(
        resource="https://keeper.example",
        identity_providers=[],
        surface_audiences={"http": "aud-http"},
    )
    assert "io.keeper.surface_audiences" in document
    assert not any(key.lower().startswith("x-") for key in document)


def test_document_maps_each_configured_surface_to_its_own_audience() -> None:
    """The route inverts the IdP list into a per-surface map before calling
    this. An IdP declaring two surfaces must land as two entries, not one."""
    document = build_protected_resource_metadata(
        resource="https://keeper.example",
        identity_providers=[_idp("https://idp.example")],
        surface_audiences={"http": "aud-http", "mcp_streamable_http": "aud-mcp"},
    )
    assert document["io.keeper.surface_audiences"] == {
        "http": "aud-http",
        "mcp_streamable_http": "aud-mcp",
    }
    assert document["authorization_servers"] == ["https://idp.example"]
