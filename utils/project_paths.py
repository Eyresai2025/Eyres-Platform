# utils/project_paths.py
from pathlib import Path
from datetime import datetime
import re

def _projects_root() -> Path:
    """
    Root folder:
      Documents/EyresAiPlatform/Projects
    Same as your ProjectPage root, so no mismatch.
    """
    root = Path.home() / "Documents" / "EyresAiPlatform" / "Projects"
    root.mkdir(parents=True, exist_ok=True)
    return root

def _safe_name(name: str) -> str:
    name = (name or "Project").strip()
    name = re.sub(r"[^\w\- ]+", "", name)
    name = re.sub(r"\s+", "_", name)
    return name or "Project"

def get_project_folder(project_name: str, with_timestamp: bool = True) -> Path:
    """
    Final folder:
      Documents/EyresAiPlatform/Projects/<ProjectName_YYYYMMDD_HHMMSS>
    """
    safe = _safe_name(project_name)
    if with_timestamp:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = f"{safe}_{ts}"
    folder = _projects_root() / safe
    folder.mkdir(parents=True, exist_ok=True)
    return folder
