"""
tests/test_engine_icons.py

Тесты иконок движков СУБД:
- engine_icon_color(): токены цветов для known/unknown движков;
- icon(): кэширование, рендер path vs SVG;
- set_icon_theme(): разрешение токенов и сброс кэша.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.icons import (
    _PIXMAP_CACHE,
    engine_icon_color,
    icon,
    set_icon_theme,
)


class TestEngineIconColor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_known_engines(self):
        self.assertEqual(engine_icon_color("mysql"), "@mysql_brand")
        self.assertEqual(engine_icon_color("mssql"), "@mssql_brand")
        self.assertEqual(engine_icon_color("pgsql"), "@pgsql_brand")

    def test_unknown_engine_returns_accent(self):
        self.assertEqual(engine_icon_color("oracle"), "@icon_accent")

    def test_empty_engine_returns_accent(self):
        self.assertEqual(engine_icon_color(""), "@icon_accent")

    def test_none_engine_returns_accent(self):
        self.assertEqual(engine_icon_color(None), "@icon_accent")

    def test_case_insensitive(self):
        self.assertEqual(engine_icon_color("MySQL"), "@mysql_brand")
        self.assertEqual(engine_icon_color("MSSQL"), "@mssql_brand")
        self.assertEqual(engine_icon_color("PGSQL"), "@pgsql_brand")


class TestIconCaching(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        _PIXMAP_CACHE.clear()

    def test_same_key_returns_same_instance(self):
        a = icon("dns", 16, "#ff0000")
        b = icon("dns", 16, "#ff0000")
        self.assertIs(a, b)

    def test_different_size_returns_new_instance(self):
        a = icon("dns", 16, "#ff0000")
        b = icon("dns", 20, "#ff0000")
        self.assertIsNot(a, b)

    def test_different_color_returns_new_instance(self):
        a = icon("dns", 16, "#ff0000")
        b = icon("dns", 16, "#00ff00")
        self.assertIsNot(a, b)


class TestIconRendering(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        _PIXMAP_CACHE.clear()

    def test_path_based_icon_renders(self):
        qicon = icon("refresh", 16, "#000000")
        pixmap = qicon.pixmap(16, 16)
        self.assertFalse(pixmap.isNull())

    def test_svg_icon_renders_dns(self):
        qicon = icon("dns", 16, "#2563eb")
        pixmap = qicon.pixmap(16, 16)
        self.assertFalse(pixmap.isNull())

    def test_svg_icon_renders_account_tree(self):
        qicon = icon("account_tree", 16, "#7c3aed")
        pixmap = qicon.pixmap(16, 16)
        self.assertFalse(pixmap.isNull())

    def test_svg_icon_renders_server(self):
        qicon = icon("server", 16, "#b91c1c")
        pixmap = qicon.pixmap(16, 16)
        self.assertFalse(pixmap.isNull())


class TestSetIconTheme(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        _PIXMAP_CACHE.clear()
        set_icon_theme({})

    def test_resolves_token_from_theme(self):
        set_icon_theme({"brand": "#ff0000"})
        qicon = icon("dns", 16, "@brand")
        pixmap = qicon.pixmap(16, 16)
        self.assertFalse(pixmap.isNull())

    def test_cache_cleared_on_theme_change(self):
        icon("dns", 16, "@brand")
        self.assertTrue(len(_PIXMAP_CACHE) > 0)
        set_icon_theme({"brand": "#00ff00"})
        self.assertEqual(len(_PIXMAP_CACHE), 0)


if __name__ == "__main__":
    unittest.main()
