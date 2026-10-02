"""Register an actor per principal, then author the policy this deployment will enforce.

Run once, against a keeper still running `AllowAllAuthorize`, before
`AUTHZ_POLICY_ID` is set. Nothing it writes changes a decision: a policy
is inert until the environment points at it, and an actor only matters
to an adapter that is not running yet.

## The order, which is the whole reason this is one script

`PolicyAuthorize` asks two questions, and Access answers the second. A
permission naming a principal Access holds no actor for authorizes
nothing, so a deployment that wrote the policy first and the actors
never would refuse every caller, including the one that could put it
right. Registering first and granting second is the documented
bootstrap, and doing both here is what keeps them from drifting apart
in somebody's shell history.

## Why it registers at a chosen id

The id a caller authenticates as is derived from its token subject and
published in the identity provider's subject bindings, so it is settled
before Access hears about it. An actor registered at a minted id would
be an actor nobody authenticates as.

## Re-running it

Registering an actor that exists is a 409 and is treated as done, so
the actor half is safe to repeat. The policy half is not: defining
writes a new policy with a new id every time, which is deliberate, a
rulebook is replaced by authoring another and pointing at it rather
than by being edited. Re-running leaves the old one in the log, inert
and unreferenced.

## Standard library only

The virtualenv this runs in is built with `--no-dev`, so the test
client and its HTTP stack are not there to borrow.
"""

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import policy_matrix as matrix

_ACTOR_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/open-cora/keeper/principals")

_CREATED = 201
_NO_CONTENT = 204
_CONFLICT = 409


def principal_id(subject: str) -> UUID:
    """The id a subject authenticates as, derived the way `issue_tokens.py` derives it."""
    return uuid5(_ACTOR_NAMESPACE, subject)


class SeedError(RuntimeError):
    """The keeper refused something this script cannot carry on without."""


def _post(
    base_url: str, path: str, body: dict[str, Any], *, token: str | None, context: ssl.SSLContext
) -> tuple[int, dict[str, Any]]:
    """Send one request, and hand back the status beside the decoded body."""
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=30) as answer:
            raw = answer.read().decode()
            return answer.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as refused:
        raw = refused.read().decode()
        try:
            return refused.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return refused.code, {"detail": raw}


def register_actors(
    base_url: str, *, token: str | None, context: ssl.SSLContext, dry_run: bool
) -> None:
    """Give every subject an actor at the id its token authenticates as."""
    for subject in matrix.SUBJECTS:
        actor = principal_id(subject)
        if dry_run:
            print(f"  would register {subject:8} {actor}")
            continue
        status, body = _post(
            base_url, "/actors", {"actor_id": str(actor)}, token=token, context=context
        )
        if status == _CREATED:
            print(f"  registered {subject:8} {actor}")
        elif status == _CONFLICT:
            print(f"  already    {subject:8} {actor}")
        else:
            raise SeedError(f"registering {subject} answered {status}: {body}")


def define_policy(
    base_url: str, *, token: str | None, context: ssl.SSLContext, dry_run: bool
) -> UUID | None:
    """Author the policy holding every grant the matrix states."""
    permissions = [
        {
            "principal_id": str(principal_id(subject)),
            "command_name": command,
            "beamline": beamline,
        }
        for subject, command, beamline in matrix.grants()
    ]
    scoped = sum(1 for p in permissions if p["beamline"] is not None)
    print(f"  {len(permissions)} grants, {scoped} of them naming a beamline")
    if dry_run:
        return None

    status, body = _post(
        base_url, "/policies", {"permissions": permissions}, token=token, context=context
    )
    if status != _CREATED:
        raise SeedError(f"defining the policy answered {status}: {body}")
    return UUID(str(body["policy_id"]))


def main() -> int:
    """Register the actors, author the policy, and say what to do with it."""
    parser = argparse.ArgumentParser(description="Seed this deployment's first policy.")
    parser.add_argument("--base-url", required=True, help="for example https://lyra:8443")
    parser.add_argument("--ca", help="the CA certificate the keeper's TLS is signed by")
    parser.add_argument("--token-file", help="a bearer token this deployment accepts")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would be written and write nothing"
    )
    args = parser.parse_args()

    context = ssl.create_default_context(cafile=args.ca)
    token = None
    if args.token_file:
        with open(args.token_file, encoding="utf-8") as handle:
            token = handle.read().strip()

    base_url = str(args.base_url).rstrip("/")
    print(f"Seeding {base_url}")
    print("\nActors")
    register_actors(base_url, token=token, context=context, dry_run=args.dry_run)

    print("\nPolicy")
    policy_id = define_policy(base_url, token=token, context=context, dry_run=args.dry_run)
    if policy_id is None:
        print("\nnothing was written")
        return 0

    print(f"  defined {policy_id}")
    print("\nNothing is enforced yet. Verify against this policy, then enable it with:")
    print(f"  AUTHZ_POLICY_ID={policy_id} ./push.sh HEAD")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeedError as refused:
        print(f"refused: {refused}", file=sys.stderr)
        raise SystemExit(1) from refused
