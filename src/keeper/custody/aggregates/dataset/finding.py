"""What somebody concluded about a body of data, and what they weighed.

## Why a judgement belongs here when a reading does not

The rule this context applies to everything it is offered is to hold what
would otherwise be lost and what this system judged, and to refuse what can
be read back from whoever owns it. A mean over a frame has an owner: open
the data and compute it again. A judgement has none. Nothing stored anywhere
says that a scan arrived short of what was asked for, because the two halves
of that statement live in two places and nobody joins them.

So this is the third layer of what a reader can learn about data without
opening it. The address says where it is, the description says what shapes
are in it, and this says what somebody made of them.

## Why the two counts are here, when the shapes they came from are too

A judgement with no evidence is an assertion, and this system already
refuses one of those: a thinker may not attach a confidence score to its own
answer. What it does keep is the boundary an answer was drawn inside, two
plain counts, so a later reader can weigh the claim without being handed a
measurement.

The same reasoning carries here with one addition that makes it stronger. A
description is explicitly allowed to be superseded, because a scan engine at
some of these beamlines reopens a finished file to append the rotation angle
of each frame. So the shapes a finding was reached from are not recoverable
by reading the record later. They were true when it looked.

## The rule the shape enforces

    A finding must say what was concluded, and never enough to let a
    reader recompute the conclusion from values it did not have.

Three fields, and there is nowhere to put a mean, a sigma or a ratio. A rule
saying so could be read and ignored; a closed shape cannot, which is the
same move `Entry` makes one layer down.
"""

from dataclasses import dataclass

FINDING_JUDGEMENT_MAX_LENGTH = 64
"""The bound on a judgement, which is one short word from a vocabulary.

The same bound a role and a convention carry, because it is the same kind
of thing: a word this system does not own and will not define.
"""

DATASET_MAX_FINDINGS = 16
"""How many distinct judgements one dataset may carry.

A bound rather than a limit anybody is expected to reach. Findings are
written deliberately, one per thing a computation looked at, so a dataset
holding sixteen different ones is a caller that has started using the
judgement as a key for something else. Refused here, where the fold is
cheap to reason about, rather than discovered as a stream nobody wants to
load.
"""


class InvalidFindingError(ValueError):
    """A finding was built outside what it may hold.

    Raised at construction, so a malformed judgement fails where it is
    assembled rather than at the append.
    """


@dataclass(frozen=True)
class Finding:
    """What a computation concluded about data, and the counts behind it.

    ## Why the judgement is one open word

    `judgement` is whatever word the computation reached for, and nothing
    here checks it against a list. That is the same choice the role on an
    entry makes, and for the same reason: a vocabulary this system defines
    is a vocabulary that stops at the cases it thought of first, and the
    device register has been watching a free-form word converge without
    help, with four beamlines independently saying the same thing.

    A closed set was considered and refused on cost rather than on taste.
    Every new kind of finding would be a keeper change, a deploy and a
    migration, which is the cadence this tree already decided is wrong for
    anything that varies per experiment.

    The word carries what was examined as well as the verdict, so there is
    no second field naming the aspect. Two fields would let a caller pair
    an aspect with a verdict that does not belong to it, and the pairing
    nobody meant is the one that gets written.

    ## Why the counts are named for expectation rather than for a plan

    `expected` is what the computation expected to find and `arrived` is
    what it found. Deliberately not `planned`: the case this exists for is
    a scan whose rotation angles were never written, and nothing in any
    procedure asks for an angles array. A convention does. Where a
    computation got its expectation is its own business, the same way this
    system does not record why a thinker concluded what it concluded.

    Presence is a count, which is what lets one shape carry both known
    cases. A scan that asked for 128 projections and produced 100 is 128
    against 100. A scan whose angles were never recorded is 1 against 0.
    """

    judgement: str
    expected: int
    arrived: int

    def __post_init__(self) -> None:
        if not self.judgement.strip():
            raise InvalidFindingError(
                "a judgement is the word a computation reached for, and a blank one "
                "says nothing a reader could act on"
            )
        if len(self.judgement) > FINDING_JUDGEMENT_MAX_LENGTH:
            raise InvalidFindingError(f"a judgement is a short word, not {len(self.judgement)}")
        if self.expected < 0 or self.arrived < 0:
            raise InvalidFindingError(
                f"these count things, so {self.expected} and {self.arrived} cannot hold a negative"
            )


__all__ = [
    "DATASET_MAX_FINDINGS",
    "FINDING_JUDGEMENT_MAX_LENGTH",
    "Finding",
    "InvalidFindingError",
]
