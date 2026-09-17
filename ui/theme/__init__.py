"""Public white-theme API."""

from .manager import adapt_legacy_page, apply_light_surface, asset_path, fade_in
from .stylesheet import application_stylesheet

__all__ = (
    "adapt_legacy_page", "apply_light_surface", "application_stylesheet",
    "asset_path", "fade_in",
)
