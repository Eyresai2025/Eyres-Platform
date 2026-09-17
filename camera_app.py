"""Compatibility entry point for the refactored camera workflow."""
from pages.capture.page import CameraWidget, main

__all__ = ["CameraWidget", "main"]

if __name__ == "__main__":
    main()
