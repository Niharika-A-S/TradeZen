"""
TradeZen Packaging Script
Creates a clean, portable zip archive ready to share with teammates.
Automatically excludes environment-specific, machine-specific, and private files:
- .venv / virtual environments
- frontend/node_modules and frontend/dist
- .git repository history
- backups/
- __pycache__ and .pytest_cache
- private .env files (includes clean .env.example)
"""

import os
import sys
import zipfile
from pathlib import Path

EXCLUDED_DIR_NAMES = {
    ".venv",
    "venv",
    "node_modules",
    "dist",
    ".git",
    "backups",
    "__pycache__",
    ".pytest_cache",
    ".vscode",
    "scratch",
}

EXCLUDED_FILE_NAMES = {
    ".env",  # Exclude private credentials; .env.example will be used
    ".DS_Store",
    "Thumbs.db",
}

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".zip",
    ".log",
}

def should_exclude(rel_path: Path) -> bool:
    # Check parts for excluded directory names
    for part in rel_path.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True
    
    # Check file name
    if rel_path.name in EXCLUDED_FILE_NAMES:
        return True
    
    # Check extension
    if rel_path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True

    return False

def create_shareable_zip(project_root: Path, output_zip_path: Path):
    print(f"==================================================")
    print(f"Packaging TradeZen for Teammates")
    print(f"Project root : {project_root}")
    print(f"Output zip   : {output_zip_path}")
    print(f"==================================================")

    file_count = 0
    total_uncompressed_bytes = 0

    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_root):
            # Prune excluded directories in-place to avoid traversing them
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]

            for file in files:
                abs_file_path = Path(root) / file
                rel_path = abs_file_path.relative_to(project_root)

                if should_exclude(rel_path):
                    continue

                # Add file inside a top-level 'TradeZen/' folder in the zip
                archive_name = Path("TradeZen") / rel_path
                zf.write(abs_file_path, arcname=str(archive_name))
                file_count += 1
                total_uncompressed_bytes += abs_file_path.stat().st_size

    zip_size_mb = output_zip_path.stat().st_size / (1024 * 1024)
    raw_size_mb = total_uncompressed_bytes / (1024 * 1024)

    print(f"\n[SUCCESS] Packaging Complete!")
    print(f"Total files included    : {file_count}")
    print(f"Uncompressed data size  : {raw_size_mb:.2f} MB")
    print(f"Compressed zip size     : {zip_size_mb:.2f} MB")
    print(f"Saved to: {output_zip_path.resolve()}\n")

if __name__ == "__main__":
    current_dir = Path(__file__).resolve().parent.parent
    
    # Target zip location: inside project root (TradeZen_Shareable.zip)
    output_zip = current_dir / "TradeZen_Shareable.zip"

    # Allow custom output path via CLI argument
    if len(sys.argv) > 1:
        output_zip = Path(sys.argv[1]).resolve()

    create_shareable_zip(current_dir, output_zip)
