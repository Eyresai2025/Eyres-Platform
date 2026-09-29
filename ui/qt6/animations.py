"""Reusable restrained Qt6 motion helpers.

A QWidget can own only one QGraphicsEffect. Never replace a card's existing
drop-shadow effect with a temporary opacity effect because Qt deletes the old
C++ effect object.
"""
from PyQt6 import QtCore, QtWidgets

from .tokens import MOTION


def _has_existing_effect(widget: QtWidgets.QWidget) -> bool:
    try:
        return widget.graphicsEffect() is not None
    except RuntimeError:
        return False


def fade_in(widget: QtWidgets.QWidget, duration_ms: int | None = None) -> None:
    """Soft entrance that preserves existing graphics effects."""
    if widget is None:
        return

    duration = int(duration_ms or MOTION["normal_ms"])

    # Cards/panels already own a drop-shadow effect. Use their own safe
    # entrance hook instead of replacing that effect with opacity.
    if _has_existing_effect(widget):
        hook = getattr(widget, "animate_entrance", None)
        if callable(hook):
            hook(duration)
        return

    effect = QtWidgets.QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)

    animation = QtCore.QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(max(80, duration))
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def _finish():
        try:
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    animation.finished.connect(_finish)
    widget._eyres_fade_animation = animation
    animation.start()


def crossfade_stack(
    stack: QtWidgets.QStackedWidget,
    target: QtWidgets.QWidget,
    duration_ms: int | None = None,
) -> None:
    """Switch a stacked page with a restrained fade-in."""
    if stack.currentWidget() is target:
        return
    stack.setCurrentWidget(target)
    fade_in(target, duration_ms=duration_ms or MOTION["normal_ms"])
