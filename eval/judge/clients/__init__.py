"""Network-boundary package.

Everything else under ``eval/judge/`` is pure and network-free. This package is
the only place allowed to talk to a provider, which is what makes the
statistics in the rest of the judge subsystem testable without a key.
"""
