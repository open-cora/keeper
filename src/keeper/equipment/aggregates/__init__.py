"""Aggregates of the Equipment bounded context.

One aggregate, the Device. This package is also the read-side surface a
sibling context would reach into, which is why the cross-BC doors in
`tach.toml` name `keeper.<bc>.aggregates` rather than a bare package. No
sibling reaches in here yet, and this context reaches into none of them:
a device is not tied to a run, and nothing about registering or faulting
one needs to know whether anything was running at the time.
"""
