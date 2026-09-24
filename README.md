# Keeper

*Themis, goddess of order and justice*

CORA itself: the system of record for the experiment. Event-sourced bounded
contexts over Postgres, hexagonal ports and adapters, and equivalent REST and
agent-protocol surfaces backed by a single handler per command.

The other three repositories are clients of this one. None of them is part of
it, and it imports none of them.

## Status

Nothing here yet. The tree that becomes keeper exists elsewhere and moves here
in one commit, after it is renamed. It is not split in pieces, because the
architecture fitness tests range over the whole package and a partial tree
makes them pass while examining almost nothing.

## The four

| Repo | Does |
| --- | --- |
| [keeper](https://github.com/open-cora/keeper) | Records what was proposed, run and produced |
| [conductor](https://github.com/open-cora/conductor) | Conducts a procedure across a beamline, one step at a time |
| [reporter](https://github.com/open-cora/reporter) | Reports what an acquisition engine did |
| [thinker](https://github.com/open-cora/thinker) | Proposes what to run next |

## License

Apache-2.0. See [LICENSE](LICENSE).
