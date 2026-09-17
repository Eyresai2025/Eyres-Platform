"""Best-effort lifecycle management for embedded feature pages."""

from __future__ import annotations

import logging
from typing import Any, Iterable


_LOGGER = logging.getLogger("eyres.lifecycle")


def deactivate_component(component: Any) -> None:
    """Pause a component when navigating away, if it supports that contract."""
    callback = getattr(component, "deactivate", None)
    if callable(callback):
        callback()


def shutdown_component(component: Any) -> list[str]:
    """Stop one component using its first supported shutdown contract."""
    errors: list[str] = []
    if component is None:
        return errors
    for method_name in ("shutdown", "stop", "stop_capture", "stop_camera", "close"):
        callback = getattr(component, method_name, None)
        if not callable(callback):
            continue
        try:
            callback()
        except Exception as exc:  # shutdown must continue for remaining components
            message = f"{type(component).__name__}.{method_name}: {exc}"
            errors.append(message)
            _LOGGER.exception("Component shutdown failed: %s", message)
        break
    return errors


def shutdown_components(components: Iterable[Any]) -> list[str]:
    errors: list[str] = []
    seen: set[int] = set()
    for component in components:
        if component is None or id(component) in seen:
            continue
        seen.add(id(component))
        errors.extend(shutdown_component(component))
    return errors
