"""Import a heavy third-party module only when it is first used.

``requests`` (with urllib3 and charset_normalizer) and ``keyring`` cost several
megabytes of resident memory, yet an idle widget never touches them: only a
provider that is actually enabled, or a stored secret that is actually read,
does. :func:`lazy_module` returns a stand-in that imports the real module on
first attribute access and forwards everything (reads, writes and deletes) to
it, so call sites and ``monkeypatch.setattr(mod.keyring, "get_password", ...)``
in tests behave exactly as if the real module had been imported at the top.
"""

from __future__ import annotations

import importlib
from types import ModuleType


class _LazyModule:
    __slots__ = ("_lazy_name", "_lazy_module")

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_lazy_name", name)
        object.__setattr__(self, "_lazy_module", None)

    def _load(self) -> ModuleType:
        module = object.__getattribute__(self, "_lazy_module")
        if module is None:
            module = importlib.import_module(object.__getattribute__(self, "_lazy_name"))
            object.__setattr__(self, "_lazy_module", module)
        return module

    def __getattr__(self, attr: str):
        return getattr(self._load(), attr)

    def __setattr__(self, attr: str, value) -> None:
        setattr(self._load(), attr, value)

    def __delattr__(self, attr: str) -> None:
        delattr(self._load(), attr)

    def __dir__(self):
        return dir(self._load())

    def __repr__(self) -> str:
        name = object.__getattribute__(self, "_lazy_name")
        loaded = object.__getattribute__(self, "_lazy_module") is not None
        return f"<lazy module {name!r} ({'loaded' if loaded else 'not loaded yet'})>"


def lazy_module(name: str) -> ModuleType:
    """Return a proxy for module ``name`` that imports it on first use."""
    return _LazyModule(name)  # type: ignore[return-value]
