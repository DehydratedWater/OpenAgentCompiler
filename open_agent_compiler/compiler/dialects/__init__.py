"""Dialect package — registry + bundled dialect classes.

Importing this module auto-registers the bundled dialects in the
registry so consumers can resolve them by name (e.g. 'opencode',
'claude', 'pi'). User-supplied dialects call `register()` themselves
after import.
"""

from open_agent_compiler.compiler.dialects.registry import (
    _autoregister,
    get,
    list_dialects,
    register,
)

_autoregister()

__all__ = ["get", "list_dialects", "register"]
