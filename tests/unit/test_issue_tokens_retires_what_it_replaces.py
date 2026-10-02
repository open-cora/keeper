"""Issuing a token to one caller retires that caller's older ones.

The script mints the token and writes the binding the verifier reads,
and the two have to agree about one instant. If the binding is later
than the token it was written beside, the caller is locked out the
moment its credential is replaced. If it is earlier, the credential it
was meant to retire still works.

Checked by running the script rather than by reading it, because the
agreement is between two values it computes and nothing else compares
them.

Loaded by path: it ships under `infra/deploy` so an operator can run it
on the keeper host with nothing installed, which also means it is not
importable as a module of this package.
"""

import base64
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "issue_tokens.py"


def _issuer_script() -> Any:
    spec = importlib.util.spec_from_file_location("_issue_tokens_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _claims(token: str) -> dict[str, Any]:
    body = token.split(".")[1]
    body += "=" * (-len(body) % 4)
    loaded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body))
    return loaded


def _run(
    root: Path, *subjects: str, rotate: tuple[str, ...] = ()
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Issue tokens into `root` and return the tokens and the bindings."""
    script = _issuer_script()
    rotation = [flag for subject in rotate for flag in ("--rotate", subject)]
    assert script.main([*subjects, "--root", str(root), *rotation]) == 0
    providers = json.loads((root / "etc" / "identity-providers.json").read_text())
    bindings = {row["subject"]: row for row in providers[0]["subject_bindings"]}
    tokens = {
        subject: _claims((root / "etc" / "tokens" / f"{subject}.token").read_text().strip())
        for subject in subjects
    }
    return tokens, bindings


def test_a_freshly_rotated_token_is_not_retired_by_the_binding_written_with_it(
    tmp_path: Path,
) -> None:
    """The lockout trap, and the reason the mint instant is passed in.

    Reading the clock once for the claim and again for the binding puts
    the retirement microseconds after the token it was meant to spare,
    and every rotation then 401s the caller it just issued to.

    Rotating rather than first-issuing, because a rotation is the only
    thing that publishes a retirement for the trap to live in.
    """
    _first, _ = _run(tmp_path, "19-bm")
    tokens, bindings = _run(tmp_path, "19-bm", rotate=("19-bm",))

    issued = datetime.fromtimestamp(tokens["19-bm"]["iat"], UTC)
    retired = datetime.fromisoformat(bindings["19-bm"]["not_before"])

    assert issued == retired, (
        f"the token says it was minted at {issued.isoformat()} and its own binding "
        f"retires anything before {retired.isoformat()}. A caller handed this token "
        "would be refused by the configuration shipped alongside it."
    )


def test_rotating_one_subject_retires_its_own_token_and_nobody_elses(tmp_path: Path) -> None:
    """The whole point: one beamline's credential dies, the others live.

    Both halves in one test because they share a setup whose cost is a
    real second of waiting. `iat` is defined in whole seconds, so two
    mints inside one second are indistinguishable and the retirement
    cannot separate them. Sleeping past the boundary tests the property
    rather than racing it.
    """
    before, _ = _run(tmp_path, "2-bm", "19-bm", "thinker")
    time.sleep(1.1)
    after, bindings = _run(tmp_path, "2-bm", "19-bm", "thinker", rotate=("19-bm",))

    rotated = datetime.fromisoformat(bindings["19-bm"]["not_before"])
    assert datetime.fromtimestamp(after["19-bm"]["iat"], UTC) >= rotated, (
        "the new token must survive its own binding"
    )
    assert datetime.fromtimestamp(before["19-bm"]["iat"], UTC) < rotated, (
        "the previous token is still accepted, so rotating added a credential "
        "instead of replacing one"
    )

    assert after["2-bm"] == before["2-bm"]
    assert after["thinker"] == before["thinker"]
    assert bindings["2-bm"].get("not_before") is None, (
        "rotating 19-bm published a retirement for 2-bm, which is the coupling "
        "this removes. It would refuse every copy of 2-bm's token older than "
        "the one on this disk, and nobody asked for 2-bm to be rotated."
    )


def test_a_first_issue_retires_nothing_because_there_is_nothing_to_retire(
    tmp_path: Path,
) -> None:
    """Every subject gets a binding; none of them gets a retirement.

    A subject being issued its first token has no older ones, so there
    is nothing a retirement could refuse except a copy somebody carries
    out later and a subsequent mint then invalidates.
    """
    _tokens, bindings = _run(tmp_path, "19-bm", "7-bm", "thinker")

    assert {"19-bm", "7-bm", "thinker"} == set(bindings)
    assert not [s for s, row in bindings.items() if row.get("not_before") is not None], (
        "a first issue published a retirement, which retires nothing today and "
        "refuses a distributed copy the first time this subject is re-minted."
    )


def test_a_run_that_keeps_a_token_does_not_retire_the_copy_a_caller_is_holding(
    tmp_path: Path,
) -> None:
    """The failure this cost four beamlines at once.

    The token in this directory is the source. A caller holds a copy,
    carried there by hand, and the two diverge the moment a mint here
    is not followed by a distribution there. A later run that keeps the
    token and publishes its mint instant anyway retires every copy
    older than this disk's, which is precisely the copy still in use.

    Measured as the caller sees it: an older token, against the binding
    a keeping run publishes.
    """
    script = _issuer_script()
    held = datetime.now(UTC).replace(microsecond=0)

    _tokens, _bindings = _run(tmp_path, "19-bm")
    # Backdate the caller's copy, which is what a distribution that
    # happened before the last mint looks like from here.
    older = held.timestamp() - 3600

    _again, bindings = _run(tmp_path, "19-bm")
    retired = bindings["19-bm"].get("not_before")

    assert retired is None or datetime.fromisoformat(retired).timestamp() <= older, (
        "a run that minted nothing published a retirement, so every copy of "
        "this caller's token older than the one on this disk is now refused. "
        "Nothing was rotated and nothing was distributed, so that is every "
        "caller that was working a moment ago."
    )
    assert script is not None


def test_a_rotation_stays_retired_through_a_later_run_that_keeps_the_token(
    tmp_path: Path,
) -> None:
    """A retirement has to outlive the run that declared it.

    It is published in the settings file and nowhere else, so a later
    run that rewrote the file without it would accept the very tokens
    the rotation was performed to kill.
    """
    _first, _ = _run(tmp_path, "19-bm")
    time.sleep(1.1)
    _rotated, after_rotation = _run(tmp_path, "19-bm", rotate=("19-bm",))
    _kept, after_keeping = _run(tmp_path, "19-bm")

    assert after_rotation["19-bm"].get("not_before") is not None, (
        "a rotation published no retirement, so the token it replaced is "
        "still accepted and rotating bought nothing."
    )
    assert after_keeping["19-bm"].get("not_before") == after_rotation["19-bm"]["not_before"], (
        "a run that kept the token dropped the retirement a rotation had "
        "declared, so the credential that rotation killed works again."
    )
