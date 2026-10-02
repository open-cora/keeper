"""Who may issue which command, and where, when this deployment stops allowing everything.

Today the keeper runs with no `AUTHZ_POLICY_ID`, so `build_authorize` hands
back `AllowAllAuthorize` and every authenticated caller may issue every
command. This module is the rulebook that replaces that, written as data so
it can be read, argued with and replayed before anything is turned on.

## The shape of it

One principal per caller, the same five `issue_tokens.py` mints for, plus an
administrator that runs nothing. Three bands:

    reads        every principal, no beamline
    open writes  per role, no beamline
    fenced       per role, AT one named beamline

Only four commands are fenced, because only four handlers pass a beamline to
`authorize`. The other write slices resolve a beamline by reading a sibling
aggregate and authorize before that read, so a permission for them cannot say
where yet. `tests/architecture/test_beamline_commands_are_scoped.py` names
them. Treating the fence as complete would be the dangerous misreading: it
confines who may define a procedure, register a device, start a pursuit and
adopt a proposal, and it does not confine who may dispatch an execution.

## Why reads are granted to everyone

Because that is what today does, and read scoping is a separate decision.
This pass narrows writes. Narrowing reads at the same time would mean two
behaviour changes arriving in one restart with one of them untested, and the
read path is the one every client is on constantly.

`GetActor` and `GetPolicy` are the exception and are held by the
administrator alone. No deployed client calls either, measured against both
the clients' own sources and three days of the access log, so withholding
them costs nothing a caller is doing.

## Why the administrator exists

`DefinePolicy` refuses a policy nobody can change, and the check is
`GOVERNING_COMMAND_NAMES`, today `GrantPolicyPermission`. So somebody must
hold it. Putting it on a beamline principal would let that beamline grant
itself anything, which would make the fence decorative for the one principal
most able to misuse it. A separate subject that no machine runs keeps the
power off the floor.
"""

from collections.abc import Iterator

BEAMLINES: tuple[str, ...] = ("2-bm", "7-bm", "19-bm", "32-id")

ADMIN = "admin"

SUBJECTS: tuple[str, ...] = (*BEAMLINES, "thinker", ADMIN)

READS: tuple[str, ...] = (
    "GetDataset",
    "GetDevice",
    "GetExecution",
    "GetInquiry",
    "GetOperation",
    "GetProcedure",
    "GetProposal",
    "GetPursuit",
    "ListDatasets",
    "ListDevices",
    "ListExecutions",
    "ListInquiries",
    "ListOperations",
    "ListProcedures",
    "ListProposals",
    "ListPursuits",
    "ListStepsWithoutDatasets",
)

ADMIN_ONLY_READS: tuple[str, ...] = ("GetActor", "GetPolicy")

FENCED: tuple[str, ...] = (
    "AdoptProposal",
    "DefineProcedure",
    "RegisterDevice",
    "StartPursuit",
)
"""The four commands whose handler passes a beamline to `authorize`."""

BEAMLINE_WRITES: tuple[str, ...] = (
    "ClaimExecution",
    "DispatchExecution",
    "EndExecution",
    "ReportExecutionStep",
    "ReportStepRun",
    "RegisterDataset",
    "RegisterDatasetAddress",
    "WithdrawDatasetAddress",
    "DefineOperation",
    "MakeInquiry",
    "ClaimInquiry",
    "AnswerInquiry",
    "MakeProposal",
    "TakeProposal",
    "OpenPursuitRound",
    "ClosePursuitRound",
    "ChargePursuit",
    "ResumePursuit",
    "WithdrawPursuit",
    "FaultDevice",
    "RecoverDevice",
    "RetireDevice",
)
"""What a beamline account issues that carries no beamline to match on.

Wider than what each beamline has been measured doing, on purpose. A
beamline runs a conductor, a reporter and whatever an operator drives by
hand, and the cost of a command missing from this list is a refusal in the
middle of somebody's beamtime. The cost of one being present and unused is a
row. The fence that matters is still there: every one of these is a command
whose beamline the keeper cannot check yet, so withholding it here would buy
no confinement.
"""

THINKER_WRITES: tuple[str, ...] = (
    "MakeInquiry",
    "ClaimInquiry",
    "AnswerInquiry",
    "MakeProposal",
)
"""Exactly what the deployed thinker calls, read from its own source.

Narrow where the beamline lists are wide, and the asymmetry is the point.
The thinker is one central process whose whole job is to answer inquiries
and propose; it is also the one principal that is not tied to a place, so a
command it holds reaches every beamline. It gets nothing that writes to a
beamline's work.
"""

ADMIN_WRITES: tuple[str, ...] = (
    "DefinePolicy",
    "GrantPolicyPermission",
    "RevokePolicyPermission",
    "RegisterActor",
    "DeactivateActor",
    "ReactivateActor",
)


def grants() -> Iterator[tuple[str, str, str | None]]:
    """Yield every permission as (subject, command_name, beamline)."""
    for subject in SUBJECTS:
        for command in READS:
            yield subject, command, None

    for beamline in BEAMLINES:
        for command in BEAMLINE_WRITES:
            yield beamline, command, None
        for command in FENCED:
            yield beamline, command, beamline

    for command in THINKER_WRITES:
        yield "thinker", command, None

    for command in (*ADMIN_ONLY_READS, *ADMIN_WRITES):
        yield ADMIN, command, None


__all__ = [
    "ADMIN",
    "ADMIN_ONLY_READS",
    "ADMIN_WRITES",
    "BEAMLINES",
    "BEAMLINE_WRITES",
    "FENCED",
    "READS",
    "SUBJECTS",
    "THINKER_WRITES",
    "grants",
]
