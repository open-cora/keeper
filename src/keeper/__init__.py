"""Keeper: a parallel domain-modeling effort on an event-sourced chassis."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("keeper")
except PackageNotFoundError:  # pragma: no cover  # uninstalled / dev mode without -e
    __version__ = "0.0.0+unknown"
