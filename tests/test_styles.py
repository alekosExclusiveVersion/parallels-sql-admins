"""
tests/test_styles.py

Тесты системы тем (gui/styles.py):
- brand tokens присутствуют в обеих темах (LIGHT + DARK);
- build_stylesheet() полностью подставляет все токены;
- фокус-рамка у QTreeWidget/QTableWidget отключена (border:none).
"""

import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.styles import DARK, LIGHT, _TEMPLATE, build_stylesheet


class TestBrandTokensInThemes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_mysql_brand_in_light(self):
        self.assertIn("mysql_brand", LIGHT)

    def test_mssql_brand_in_light(self):
        self.assertIn("mssql_brand", LIGHT)

    def test_pgsql_brand_in_light(self):
        self.assertIn("pgsql_brand", LIGHT)

    def test_mysql_brand_in_dark(self):
        self.assertIn("mysql_brand", DARK)

    def test_mssql_brand_in_dark(self):
        self.assertIn("mssql_brand", DARK)

    def test_pgsql_brand_in_dark(self):
        self.assertIn("pgsql_brand", DARK)


class TestBuildStylesheet(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_light_no_unsubstituted_placeholders(self):
        qss = build_stylesheet("light")
        remaining = set(re.findall(r"\{(\w+)\}", qss))
        self.assertEqual(remaining, set(), f"Unsubstituted: {remaining}")

    def test_dark_no_unsubstituted_placeholders(self):
        qss = build_stylesheet("dark")
        remaining = set(re.findall(r"\{(\w+)\}", qss))
        self.assertEqual(remaining, set(), f"Unsubstituted: {remaining}")

    def test_template_tokens_all_present_in_themes(self):
        tokens_in_template = set(re.findall(r"\{(\w+)\}", _TEMPLATE))
        for theme_name, theme in [("LIGHT", LIGHT), ("DARK", DARK)]:
            missing = tokens_in_template - set(theme.keys())
            self.assertEqual(
                missing, set(),
                f"Theme {theme_name} missing tokens: {missing}",
            )


class TestFocusBorderRemoved(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_tree_widget_focus_border_none(self):
        for theme in ("light", "dark"):
            qss = build_stylesheet(theme)
            self.assertIn("border:none", qss)
            self.assertIn("QTreeWidget:focus", qss)


if __name__ == "__main__":
    unittest.main()
