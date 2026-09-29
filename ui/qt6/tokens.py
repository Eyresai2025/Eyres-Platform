"""Qt6 design tokens for the EYRES AI Inspection Platform.

This module intentionally has no Qt imports so it can remain the visual
single-source-of-truth while the rest of the platform is migrated.
"""

COLORS = {
    "canvas": "#EEF3F9",
    "surface": "#FFFFFF",
    "surface_soft": "#F7F9FC",
    "surface_blue": "#EEF4FF",
    "text": "#172033",
    "text_secondary": "#344156",
    "muted": "#5F7087",
    "border": "#C9D5E5",
    "border_strong": "#B8C7DA",
    "primary": "#2868E8",
    "primary_hover": "#1E56C7",
    "cyan": "#16BCE8",
    "purple": "#7C4DFF",
    "magenta": "#ED2ED2",
    "success": "#159A67",
    "warning": "#D99000",
    "danger": "#D9435F",
}

RADIUS = {
    "small": 8,
    "medium": 10,
    "large": 18,
    "xlarge": 24,
}

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 20,
    "xl": 28,
    "xxl": 40,
}

BREAKPOINTS = {
    "compact_width": 1180,
    "small_width": 760,
    "short_height": 720,
}

MOTION = {
    "fast_ms": 140,
    "normal_ms": 190,
    "page_ms": 220,
}
