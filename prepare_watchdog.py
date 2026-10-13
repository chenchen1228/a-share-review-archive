"""Refresh an isolated expected mirror without committing or publishing it."""
from pathlib import Path
import shutil
from sync_public_site import sync

target = Path('monitor-docs')
if not target.exists():
    shutil.copytree('docs', target)
sync(target)
