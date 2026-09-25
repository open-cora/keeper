"""Pin what the fitness suite ranges over, so a vacuous pass cannot hide.

The checks in this directory iterate over discovered bounded contexts, over
the aggregates inside them, and over the slices inside those. Given none of
a kind, the matching checks iterate over nothing. A parametrized check with
an empty parameter set is reported as a SKIP, and a check that loops over an
empty list is reported as a PASS. Neither is evidence that a rule holds.

So the counts are pinned here, at three granularities, and each has to be
raised deliberately. Three and not one because they move independently: a
bounded context can exist with no slices in it yet, and every slice rule
would range over nothing while the bounded-context pin looked satisfied.

When a pin fails because you just added something:

  1. Confirm the checks of that kind now actually see it. A rule still
     collecting zero subjects is enforcing nothing, whatever the pin says.
  2. Raise the number in the same commit.

Doing (2) without (1) turns the pin into bookkeeping. The point is the look,
not the number.

One asymmetry worth knowing. The bounded-context count reads the directory
tree; the aggregate and slice counts read git's tracked set, because that is
what the rules themselves read. A bounded context whose files are all
unstaged therefore shows up as one BC with zero aggregates, which is exactly
the state where a full green run has checked nothing inside it.

## The layer underneath the counts

Every count above is derived by enumerating files, and every enumeration
resolves against a root. A wrong root is the cheapest way to make the whole
directory vacuous at once, and the quietest: `git ls-files` run in a
directory that happens to be tracked by some other repository succeeds, so
the rules come back green having read the wrong tree.

The checks at the end of this module hold that layer. They are relational
rather than numeric on purpose. A pinned file count would have to be bumped
on every commit that adds a module, which teaches everyone to bump it
without looking, and that is the opposite of what the pins above are for.
"""

import pytest

from tests._roots import APP_ROOT, REPO_ROOT
from tests.architecture.conftest import (
    discovered_aggregates,
    discovered_bcs,
    discovered_slices,
    tracked_file_basenames,
    tracked_markdown_files,
    tracked_migration_files,
    tracked_python_files,
    tracked_test_files,
)

pytestmark = pytest.mark.architecture

EXPECTED_BC_COUNT = 6
"""Bounded contexts this suite expects to find under `src/keeper`.

Zero is the baseline's honest state. Raise it deliberately, alongside the
check described in the module docstring, never to make a red run green.
"""

EXPECTED_AGGREGATE_COUNT = 8
"""Aggregate folders this suite expects to find across all bounded contexts.

Separate from the bounded-context pin because the rules that read an
aggregate's state, events and deserializer range over these, not over
packages. A bounded context added without one leaves every such rule idle.
"""

EXPECTED_SLICE_COUNT = 34
"""Slice folders this suite expects to find across all bounded contexts.

Separate again, and the last to move. The slice contract, decider purity,
decider signature, cross-slice independence, subject naming and wire-label
rules all range over these. Until it is above zero, none of them is
enforcing anything, however green the run.
"""


def test_discovered_bc_count_matches_the_pinned_expectation() -> None:
    found = discovered_bcs()
    assert len(found) == EXPECTED_BC_COUNT, (
        f"Fitness suite ranges over {len(found)} bounded contexts {found}, "
        f"but EXPECTED_BC_COUNT is {EXPECTED_BC_COUNT}.\n"
        "If you just added a BC: confirm the fitness tests actually see it "
        "(a rule that still collects zero subjects is not enforcing anything), "
        "then bump EXPECTED_BC_COUNT in the same commit."
    )


def test_discovered_aggregate_count_matches_the_pinned_expectation() -> None:
    found = discovered_aggregates()
    assert len(found) == EXPECTED_AGGREGATE_COUNT, (
        f"Fitness suite ranges over {len(found)} aggregates {found}, but "
        f"EXPECTED_AGGREGATE_COUNT is {EXPECTED_AGGREGATE_COUNT}.\n"
        "If you just added an aggregate: confirm the state, events and "
        "deserializer rules now collect it, then bump the number in the same "
        "commit. If you added one and this did not fail, its files are not "
        "staged and every rule in here is blind to them."
    )


def test_discovered_slice_count_matches_the_pinned_expectation() -> None:
    found = discovered_slices()
    assert len(found) == EXPECTED_SLICE_COUNT, (
        f"Fitness suite ranges over {len(found)} slices {found}, but "
        f"EXPECTED_SLICE_COUNT is {EXPECTED_SLICE_COUNT}.\n"
        "If you just added a slice: confirm the slice-contract, decider and "
        "wire-label rules now collect it rather than skipping on an empty "
        "parameter set, then bump the number in the same commit."
    )


def test_chassis_packages_are_not_mistaken_for_bounded_contexts() -> None:
    """The BC discovery must exclude the chassis, or every count is wrong.

    Guards the subtraction itself: if `NON_BC_PACKAGES` drifted out of sync
    with the tree, `discovered_bcs()` would report `api`, `infrastructure` and
    `shared` as bounded contexts and the count above would pass for the wrong
    reason.
    """
    found = discovered_bcs()
    for chassis in ("api", "infrastructure", "shared"):
        assert chassis not in found, (
            f"`{chassis}` is chassis, not a bounded context, but BC discovery "
            "returned it. Check NON_BC_PACKAGES in tests/architecture/conftest.py."
        )


def test_chassis_packages_contribute_no_aggregates_or_slices() -> None:
    """The aggregate and slice counts must not pick up chassis directories.

    Both derive their candidates by filtering on the bounded-context set, so
    this fails only if that filter is dropped. Cheap to keep, and it is the
    mistake that would make both pins pass for the wrong reason.
    """
    chassis = {"api", "infrastructure", "shared"}
    for label in discovered_aggregates() + discovered_slices():
        owner = label.split("/", 1)[0]
        assert owner not in chassis, (
            f"`{label}` is owned by chassis package `{owner}`, which has no "
            "aggregates or slices. The bounded-context filter was dropped."
        )


def test_the_repository_root_is_a_repository_root() -> None:
    """The root the cross-project rule resolves against is really one.

    It is derived from git rather than by counting directory levels, and
    the count is what this replaced. Two above `apps/keeper` is right in
    this tree and wrong in the published mirror, where the project is the
    checkout, and a count that is two too high names whatever directory
    happens to hold the clone.

    One rule still crosses between the roots, the one comparing the copies
    every project carries. Everything else is scoped to the project, which
    is what lets the mirror run the same suite and get the same answer.
    """
    assert (REPO_ROOT / ".git").exists(), f"{REPO_ROOT} is not a repository root."
    assert APP_ROOT.is_relative_to(REPO_ROOT), f"{APP_ROOT} is not inside {REPO_ROOT}."


def test_every_enumerator_finds_something() -> None:
    """Guard the enumerations themselves: an empty one passes every rule.

    Named one at a time rather than in a loop, so a failure says which
    pathspec stopped matching instead of which index of a tuple did.
    """
    assert tracked_python_files(), "No tracked source file under src/keeper."
    assert tracked_test_files(), "No tracked test file under tests/."
    assert tracked_markdown_files(), "No tracked documentation under docs/."
    assert tracked_migration_files(), "No tracked migration under infra/atlas/migrations/."
    assert tracked_file_basenames(), "No tracked file anywhere in the project."


def test_every_enumerated_file_sits_under_the_root_it_was_enumerated_from() -> None:
    """A path outside its own root means the root moved under the pathspec.

    `relative_to` is what the failure messages across this directory are
    built from, and it raises rather than reporting when this is false, so
    a rule would die with a ValueError naming neither cause nor cure.
    """
    for path in tracked_python_files() | tracked_test_files():
        assert path.is_relative_to(APP_ROOT), f"{path} is outside {APP_ROOT}."
    for path in tracked_markdown_files() | set(tracked_migration_files()):
        assert path.is_relative_to(REPO_ROOT), f"{path} is outside {REPO_ROOT}."
