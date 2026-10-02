"""Replay what production actually did against the matrix, before anything is turned on.

Setting `AUTHZ_POLICY_ID` swaps `AllowAllAuthorize` for `PolicyAuthorize` at
the next restart, and a command the policy does not hold is refused from
that instant. The failure mode is a beamline that cannot file a dataset in
the middle of somebody's beamtime, so the matrix gets replayed first.

What makes this worth running rather than reading: it drives the real
`PolicyAuthorize` over a real event store holding real policy events built
by the real `define_policy` decider. Nothing here reimplements the match. If
the adapter's rule changes, this changes with it.

## The two runs

    without actors   every call denied, because Access holds nobody
    with actors      every call allowed, except the ones declared below

The first run is not a control for its own sake. It is the state production
is in right now, and the gap between the runs is exactly the work the
cutover still needs.

## Where the calls come from

Two sources, because neither is sufficient. The event store says what was
written and by whom, which is ground truth for writes and silent about
reads. Each client's own source says what it can call, which catches the
path that exists and has not been exercised yet. `GET /inquiries/{id}` is
the one that proves the point: the thinker calls it, and three days of
access log never recorded it.
"""

import argparse
import asyncio
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import policy_matrix as matrix

from keeper.access.aggregates.actor import ACTOR_STREAM_TYPE
from keeper.access.aggregates.actor.events import ActorRegistered
from keeper.access.aggregates.actor.events import to_payload as actor_payload
from keeper.authority.adapters.policy_authorize import PolicyAuthorize
from keeper.authority.aggregates.policy import POLICY_STREAM_TYPE, Permission
from keeper.authority.aggregates.policy.events import to_payload as policy_payload
from keeper.authority.features.define_policy.command import DefinePolicy
from keeper.authority.features.define_policy.decider import decide as decide_policy
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.ports import Allow
from keeper.infrastructure.slices.envelope import to_new_event

_ACTOR_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/open-cora/keeper/principals")


def principal_id(subject: str) -> UUID:
    """The id a subject authenticates as, derived the way `issue_tokens.py` derives it."""
    return uuid5(_ACTOR_NAMESPACE, subject)


MEASURED: tuple[tuple[str, str, str | None], ...] = (
    ("19-bm", "RegisterDataset", None),
    ("19-bm", "RegisterDatasetAddress", None),
    ("19-bm", "WithdrawDatasetAddress", None),
    ("19-bm", "RegisterDevice", "19-bm"),
    ("19-bm", "ClaimExecution", None),
    ("19-bm", "DispatchExecution", None),
    ("19-bm", "EndExecution", None),
    ("19-bm", "ReportExecutionStep", None),
    ("19-bm", "ReportStepRun", None),
    ("19-bm", "MakeInquiry", None),
    ("19-bm", "DefineOperation", None),
    ("19-bm", "DefineProcedure", "19-bm"),
    ("19-bm", "AdoptProposal", "19-bm"),
    ("19-bm", "OpenPursuitRound", None),
    ("19-bm", "ClosePursuitRound", None),
    ("19-bm", "StartPursuit", "19-bm"),
    ("19-bm", "WithdrawPursuit", None),
    ("2-bm", "RegisterDataset", None),
    ("2-bm", "ClaimExecution", None),
    ("2-bm", "DispatchExecution", None),
    ("2-bm", "EndExecution", None),
    ("2-bm", "ReportExecutionStep", None),
    ("2-bm", "ReportStepRun", None),
    ("2-bm", "DefineOperation", None),
    ("2-bm", "DefineProcedure", "2-bm"),
    ("7-bm", "RegisterDataset", None),
    ("7-bm", "RegisterDevice", "7-bm"),
    ("7-bm", "ClaimExecution", None),
    ("7-bm", "DispatchExecution", None),
    ("7-bm", "EndExecution", None),
    ("7-bm", "ReportExecutionStep", None),
    ("7-bm", "ReportStepRun", None),
    ("7-bm", "DefineProcedure", "7-bm"),
    ("32-id", "RegisterDevice", "32-id"),
    ("thinker", "ClaimInquiry", None),
    ("thinker", "AnswerInquiry", None),
    ("thinker", "MakeInquiry", None),
    ("thinker", "MakeProposal", None),
    ("thinker", "DispatchExecution", None),
    ("thinker", "DefineOperation", None),
    ("thinker", "DefineProcedure", "2-bm"),
)
"""Every (principal, command, beamline) production has written, from the event store.

Derived by grouping `events` on principal_id, event_type and
`payload->>'beamline'`, then mapping each event type to the command that
produces it. Reads leave no event and are covered by `CLIENT_CALLS`.
"""

CLIENT_CALLS: tuple[tuple[str, str], ...] = tuple(
    [
        (beamline, command)
        for beamline in matrix.BEAMLINES
        for command in (
            "ListExecutions",
            "GetExecution",
            "ClaimExecution",
            "EndExecution",
            "ReportExecutionStep",
            "GetOperation",
            "GetProcedure",
            "RegisterDataset",
            "ReportStepRun",
            "ListDevices",
            "RegisterDevice",
        )
    ]
    + [
        ("thinker", command)
        for command in (
            "GetExecution",
            "ListInquiries",
            "GetInquiry",
            "MakeInquiry",
            "ClaimInquiry",
            "AnswerInquiry",
            "GetProcedure",
            "MakeProposal",
        )
    ]
)
"""What each deployed client can call, read from the clients' own sources.

A beamline account runs both a conductor and a reporter, so its row is the
union of the two. `RegisterDevice` comes from neither: it is the device
seeding an operator runs by hand with the same token, from the facility
descriptors that live outside this project.
"""

EXPECTED_DENIALS: frozenset[tuple[str, str, str | None]] = frozenset(
    {
        ("thinker", "DispatchExecution", None),
        ("thinker", "DefineOperation", None),
        ("thinker", "DefineProcedure", "2-bm"),
    }
)
"""Measured calls this matrix refuses on purpose, each one from the 2-BM rehearsal.

The thinker is central and holds no beamline of its own, so a command it can
issue reaches anywhere. These three are how it reached 2-BM once, by hand,
while 2-BM was not running users. Granting them again would make the
confinement this matrix exists for untrue on its most important principal.
Whoever repeats that rehearsal gets a 403 naming the command, which is a
readable failure rather than a silent reach.
"""


def _beamline_for(subject: str, command: str) -> str | None:
    """The beamline a call would carry, which is the subject's own or nothing."""
    return subject if command in matrix.FENCED else None


async def _store_with_policy(*, register_actors: bool) -> tuple[InMemoryEventStore, UUID]:
    """An event store holding the matrix as a policy, and optionally its actors."""
    store = InMemoryEventStore()
    now = datetime.now(UTC)

    permissions = frozenset(
        Permission(principal_id=principal_id(subject), command_name=command, beamline=beamline)
        for subject, command, beamline in matrix.grants()
    )
    policy_id = uuid4()
    events = decide_policy(None, DefinePolicy(permissions=permissions), now=now, new_id=policy_id)
    await store.append(
        POLICY_STREAM_TYPE,
        policy_id,
        0,
        [
            to_new_event(
                event_type=type(event).__name__,
                payload=policy_payload(event),
                occurred_at=event.occurred_at,
                event_id=uuid4(),
                command_name="DefinePolicy",
                correlation_id=uuid4(),
                principal_id=principal_id(matrix.ADMIN),
            )
            for event in events
        ],
    )

    if register_actors:
        for subject in matrix.SUBJECTS:
            actor = principal_id(subject)
            event = ActorRegistered(actor_id=actor, occurred_at=now)
            await store.append(
                ACTOR_STREAM_TYPE,
                actor,
                0,
                [
                    to_new_event(
                        event_type="ActorRegistered",
                        payload=actor_payload(event),
                        occurred_at=now,
                        event_id=uuid4(),
                        command_name="RegisterActor",
                        correlation_id=uuid4(),
                        principal_id=principal_id(matrix.ADMIN),
                    )
                ],
            )

    return store, policy_id


def _calls() -> list[tuple[str, str, str | None]]:
    """Every call to replay, measured and source-derived, deduplicated."""
    seen = dict.fromkeys(MEASURED)
    for subject, command in CLIENT_CALLS:
        seen.setdefault((subject, command, _beamline_for(subject, command)), None)
    return list(seen)


async def _run(*, register_actors: bool) -> list[tuple[tuple[str, str, str | None], bool]]:
    """Ask the real adapter about every call, and say which were allowed."""
    store, policy_id = await _store_with_policy(register_actors=register_actors)
    authorize = PolicyAuthorize(store, policy_id)
    results: list[tuple[tuple[str, str, str | None], bool]] = []
    for call in _calls():
        subject, command, beamline = call
        decision = await authorize.authorize(
            principal_id=principal_id(subject), command_name=command, beamline=beamline
        )
        results.append((call, isinstance(decision, Allow)))
    return results


async def main() -> int:
    """Replay both runs and report what the cutover would do."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    calls = _calls()
    print(f"replaying {len(calls)} calls against {len(list(matrix.grants()))} grants\n")

    without = await _run(register_actors=False)
    allowed_without = [call for call, ok in without if ok]
    print("without actors in Access")
    print(f"  allowed {len(allowed_without)}, denied {len(without) - len(allowed_without)}")
    if allowed_without:
        print("  UNEXPECTED: something was allowed with no actor registered")
        return 1
    print("  every call denied, which is what production would do today\n")

    with_actors = await _run(register_actors=True)
    denied = [call for call, ok in with_actors if not ok]
    print("with an actor per principal")
    print(f"  allowed {len(with_actors) - len(denied)}, denied {len(denied)}")

    surprises = [call for call in denied if call not in EXPECTED_DENIALS]
    for subject, command, beamline in sorted(denied, key=lambda c: (c[0], c[1])):
        where = "" if beamline is None else f" at {beamline}"
        mark = "by design" if (subject, command, beamline) in EXPECTED_DENIALS else "UNEXPECTED"
        print(f"  {mark:10} {subject:8} {command}{where}")

    missed = sorted(EXPECTED_DENIALS - set(denied))
    for subject, command, beamline in missed:
        where = "" if beamline is None else f" at {beamline}"
        print(f"  STALE      {subject:8} {command}{where} is declared denied and was allowed")

    if surprises or missed:
        print("\nrefused: the matrix does not match what was declared")
        return 1

    print("\nevery measured call is permitted, except the three declared above")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
