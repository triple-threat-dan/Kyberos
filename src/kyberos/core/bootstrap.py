"""
Bootstrap module for initializing the Kyberos workspace.

Ensures that the .kyberos directory structure exists, populates it with default templates
(AGENT.md, etc.) if missing, and installs default skills into the archive.
"""

import logging
import shutil
from pathlib import Path

from kyberos.core.config import KYBEROS_ROOT, KYBEROS_TEMPLATES_DIR, KYBEROS_WORKSPACE_DIR

logger = logging.getLogger("kyberos.bootstrap")

# Constants
PKG_ROOT = Path(__file__).resolve().parent.parent 
DEFAULT_SKILLS_DIR = PKG_ROOT / "skills" / "default"

FILES_TO_COPY = {
    "AGENT.md": "AGENT.md",
    "HEARTBEAT.md": "HEARTBEAT.md",
    "SOUL.md": "SOUL.md",
    "USER.md": "USER.md",
    "memories/THREAD.md": "memories/THREAD.md",
    "memories/MEMORY.md": "memories/MEMORY.md"
}

def ensure_workspace() -> None:
    """
    Ensures that the kyberos root directory exists and is populated with necessary files.
    Copies from templates if they don't exist in root.
    Installs default skills if missing.
    """
    if not KYBEROS_ROOT.exists():
        logger.info(f"Creating kyberos root at {KYBEROS_ROOT}")
        KYBEROS_ROOT.mkdir(parents=True, exist_ok=True)

    # Ensure subdirectories exist
    (KYBEROS_ROOT / "archive").mkdir(exist_ok=True)
    (KYBEROS_ROOT / "memories").mkdir(exist_ok=True)
    (KYBEROS_ROOT / "workspace").mkdir(exist_ok=True)

    if not KYBEROS_TEMPLATES_DIR.exists():
        logger.warning(f"Templates directory not found at {KYBEROS_TEMPLATES_DIR}. Cannot bootstrap workspace.")
        return

    for src_rel, dest_rel in FILES_TO_COPY.items():
        source = KYBEROS_TEMPLATES_DIR / src_rel
        target = KYBEROS_ROOT / dest_rel

        if not target.exists():
            if source.exists():
                logger.info(f"Bootstrapping {src_rel}...")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            else:
                logger.warning(f"Template {src_rel} missing in {KYBEROS_TEMPLATES_DIR}")

    # Copy Default Skills
    TARGET_SKILLS_DIR = KYBEROS_ROOT / "archive"

    if DEFAULT_SKILLS_DIR.exists():
        logger.info("Installing default skills...")
        if not TARGET_SKILLS_DIR.exists():
            TARGET_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        
        try:
            shutil.copytree(DEFAULT_SKILLS_DIR, TARGET_SKILLS_DIR, dirs_exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to install default skills: {e}")
    else:
        logger.warning(f"Default skills directory not found at {DEFAULT_SKILLS_DIR}")
