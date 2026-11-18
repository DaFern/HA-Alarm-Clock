"""Create a new self-contained local-app build directory; never install it."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "prototypes" / "ma_one_shot"
PATCH_FILES = ("adapter.py", "build_patch.py", "upstream.json", "start_command.py.txt",
               "test_commands.py.txt", "alarm_commands.py.txt")


def prepare(destination):
    destination = Path(destination)
    destination.mkdir(parents=False, exist_ok=False)
    patches = destination / "patches"
    patches.mkdir()
    for name in ("config.json", "Dockerfile"):
        shutil.copyfile(HERE / name, destination / name)
    shutil.copyfile(HERE / "install.py", patches / "install.py")
    for name in PATCH_FILES:
        shutil.copyfile(SOURCE / name, patches / name)
    hashes = {str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(destination.rglob("*")) if path.is_file()}
    (destination / "build-context.json").write_text(json.dumps(hashes, indent=2) + "\n")
    return hashes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.destination)
    print(f"Prepared {args.destination}; not built or installed")
