"""Compatibility import for the EYRES Dataset Augmentation tool.

The actual implementation lives in augmentation_tool.py.
Keep this shim so older scripts that import `augmentation` continue to work.
"""

from augmentation_tool import *  # noqa: F401,F403
