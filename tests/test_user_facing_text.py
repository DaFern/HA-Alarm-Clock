"""Keep development-server terminology out of alarm runtime messages."""
import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UserFacingTextTests(unittest.TestCase):
    def test_runtime_strings_do_not_use_development_server_names(self):
        sources = [
            ("custom_components/household_alarms/ma_audio.py", False),
            ("custom_components/household_alarms/music.py", False),
            ("prototypes/ma_one_shot/test_commands.py.txt", True),
            ("prototypes/ma_one_shot/alarm_commands.py.txt", True),
        ]
        for name, fragment in sources:
            source = (ROOT / name).read_text()
            tree = ast.parse(("class Host:\n" if fragment else "") + source)
            docs = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            }
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                    self.assertIsNone(
                        re.search(r"\bdevelopment\b|\bdev server\b|\bMA companion\b", node.value, re.I),
                        f"{name}: {node.value}",
                    )

    def test_card_help_uses_music_assistant_name(self):
        source = (ROOT / "custom_components/household_alarms/frontend/household-alarms-card.js").read_text()
        self.assertNotIn("MA companion", source)
        self.assertNotIn("HA-AlarmClock MA", source)
        self.assertNotIn("selected MA library", source)
