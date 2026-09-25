# End-to-end tier

Empty. There is no end to end yet: an e2e test drives a real request through a
real app against a real database and asserts on what the whole system did, and
with no bounded contexts there is nothing for it to do that the contract and
integration tiers do not already cover.

This file exists so the directory does. Git does not track empty directories,
so without it `tests/e2e` vanishes on a fresh clone, and the `test-db` lane in
both the Makefile and CI names that path explicitly. pytest treats a missing
path as an error, so the lane fails before running anything.

That failure is loud, which is the good case. The bad case is the same shape
one step removed: a lane that silently collects zero tests and reports green.

## What belongs here

A test that could not be written one tier down. The contract tier already
builds the real app, and the integration tier already uses a real database, so
reach for e2e only when the thing under test is the INTERACTION of several
slices across a boundary neither tier crosses on its own.
