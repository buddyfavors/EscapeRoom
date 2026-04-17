"""Escape room control server: web UI, RFID input, and game state."""

# Python 3.9: Pydantic v2 evaluates PEP 604 types (e.g. str | None); this backport must load first.
try:
    import eval_type_backport  # noqa: F401
except ImportError:
    pass

__version__ = "0.2.0"
