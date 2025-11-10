import shutil
from pathlib import Path
from typing import Optional

from bilidownloader.constants import BASE_DIR
from bilidownloader.ui import prn_info


def find_command(executable: str) -> Optional[Path]:
    """
    Find the path to an executable in the system.

    Args:
        executable (str): the name of the executable to find

    Returns:
        Optional[Path]: the path to the executable, or None if not found
    """
    path = shutil.which(executable)
    return Path(path) if path else None


def _migrate_config():
    old_base_dir = Path("~/Bilibili").expanduser().resolve()
    if old_base_dir.exists():
        files_to_migrate = ["cookies.txt", "history.v2.tsv", "watchlist.txt"]
        fonts_dir_to_migrate = old_base_dir / "fonts"
        
        should_migrate = any((old_base_dir / file).exists() for file in files_to_migrate) or fonts_dir_to_migrate.exists()

        if should_migrate:
            prn_info(f"Migrating config from {old_base_dir} to {BASE_DIR}")
            for file in files_to_migrate:
                old_file = old_base_dir / file
                if old_file.exists():
                    prn_info(f"Moving {file}...")
                    shutil.move(str(old_file), str(BASE_DIR))
            if fonts_dir_to_migrate.exists():
                prn_info("Moving fonts directory...")
                new_fonts_dir = BASE_DIR / "fonts"
                new_fonts_dir.mkdir(exist_ok=True)
                for font_file in fonts_dir_to_migrate.iterdir():
                    shutil.move(str(font_file), str(new_fonts_dir))
                if not any(fonts_dir_to_migrate.iterdir()):
                    fonts_dir_to_migrate.rmdir()
        
        if not any(old_base_dir.iterdir()):
            prn_info("Removing old config directory")
            old_base_dir.rmdir()


_migrate_config()

BASE_DIR.mkdir(parents=True, exist_ok=True)
