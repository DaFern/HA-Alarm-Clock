"""Build-time only, fail-closed patching of the pinned MA image."""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

from build_patch import candidates


def install(root):
    """Validate every original and candidate before replacing any installed file."""
    original, changes = candidates(root)
    for name, text in changes.items():
        ast.parse(text, filename=name)
    for name in changes:
        path = root / name
        if name not in original and path.exists():
            raise ValueError("Refusing to overwrite a pre-existing companion helper")
    for name, text in changes.items():
        (root / name).write_text(text)
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in changes}
    (root / "alarmclock-build.json").write_text(json.dumps({"protocol": 2, "sha256": hashes}, indent=2) + "\n")


if __name__ == "__main__":
    spec = importlib.util.find_spec("music_assistant")
    if spec is None or spec.origin is None:
        raise SystemExit("Pinned Music Assistant package not found")
    install(Path(spec.origin).resolve().parent.parent)
