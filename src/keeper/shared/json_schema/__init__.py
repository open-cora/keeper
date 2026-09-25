"""The constrained JSON Schema subset AROC accepts, and the checks over it.

Two halves of one rule, split by which side of a write they run on:

  - `subset` declares the keyword allowlist and executions a submitted schema
    against it. It answers "is this a schema AROC is willing to store".
  - `validation` answers the two questions that follow: is a declared
    schema well formed (declarer side), and do a carrier's values conform
    to it (carrier side).

`validation` imports `subset`; nothing imports the other way. They share a
package rather than a filename prefix because the prefix was the only thing
tying them together, and a folder says it better.

Nothing is re-exported here. Both modules are imported by path, so a reader
of an import line can see which half is in play.
"""
