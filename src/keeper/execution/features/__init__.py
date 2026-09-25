"""Vertical slices for the Execution bounded context.

One folder per use case, holding everything that use case needs. A slice
does not import a sibling slice: shared vocabulary belongs to the
aggregate, not to whichever slice reached for it first.
"""
