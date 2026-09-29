"""Application search is deterministic and does not depend on GTK or history."""
import importlib.util
from pathlib import Path
import sys
import unittest

SPEC = importlib.util.spec_from_file_location(
    "launcher_model", Path(__file__).resolve().parents[1] / "config/desktop/launcher_model.py")
model = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = model
SPEC.loader.exec_module(model)
Application = model.Application


class LauncherSearchTests(unittest.TestCase):
    def ids(self, applications, query):
        return [app.desktop_id for app in model.search_applications(applications, query)]

    def test_name_matches_rank_ahead_of_metadata(self):
        applications = [
            Application("metadata", "A Browser", keywords=("Chrome",)),
            Application("substring", "Google Chrome"),
            Application("prefix", "Chrome Dev"),
            Application("exact", "Chrome"),
        ]
        self.assertEqual(self.ids(applications, "chrome"), ["exact", "prefix", "substring", "metadata"])

    def test_unicode_casefold_and_width_normalization(self):
        applications = [Application("notes", "数学 ＮＯＴＥＳ"), Application("street", "Straße")]
        self.assertEqual(self.ids(applications, "数学 notes"), ["notes"])
        self.assertEqual(self.ids(applications, "STRASSE"), ["street"])

    def test_every_word_matches_across_searchable_fields(self):
        app = Application("notes", "Neovim", description="数学笔记", generic_name="Text Editor",
                          executable="nvim", keywords=("Markdown", "Code"))
        for query in ("nvim 数学", "editor markdown", "code 笔记"):
            with self.subTest(query=query):
                self.assertEqual(self.ids([app], query), ["notes"])
        self.assertEqual(self.ids([app], "markdown browser"), [])

    def test_empty_query_has_stable_name_and_id_order(self):
        applications = [Application("b", "Steam"), Application("z", "Kitty"), Application("a", "Steam")]
        self.assertEqual(self.ids(applications, "  "), ["z", "a", "b"])
        self.assertEqual(self.ids(list(reversed(applications)), ""), ["z", "a", "b"])

    def test_no_results_and_empty_database_are_valid(self):
        self.assertEqual(self.ids([], "chrome"), [])
        self.assertEqual(self.ids([Application("kitty", "Kitty")], "unknown"), [])


if __name__ == "__main__":
    unittest.main()
