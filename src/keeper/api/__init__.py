"""Composition root: the FastAPI application and its MCP surface.

This is the only layer permitted to depend on every bounded context. It builds
the app, owns the lifespan that builds and tears down the kernel, and is where
each BC plugs its handlers, routes, MCP tools and projections in.

No bounded context exists yet, so the app serves operational surfaces only.
`main.py` names the four plug-in points a BC will use.
"""
