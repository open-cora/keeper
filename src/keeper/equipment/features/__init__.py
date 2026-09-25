"""Vertical slices for the Equipment bounded context.

One folder per use case, holding everything that use case needs. A slice
does not import a sibling slice: shared vocabulary belongs to the
aggregate, not to whichever slice reached for it first.

The three transition slices are the same shape three times over, and
that repetition is the pattern rather than a thing to factor out. Each
names its own event, its own refusal and its own reason for refusing,
and a shared helper would have to take all three as parameters to say
nothing the three files do not already say plainly.
"""
