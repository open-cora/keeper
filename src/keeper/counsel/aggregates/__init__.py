"""Aggregates of the Counsel bounded context.

One aggregate, the Proposal. This package is also the read-side surface
a sibling context would reach into, which is why the cross-BC doors in
`tach.toml` name `aroc.<bc>.aggregates` rather than a bare package. No
sibling reaches in here yet.
"""
