"""
tests/test_server_sorting.py

Сортировка списка серверов: сначала по типу сервера (движку), затем
по алфавиту внутри группы (MainWindow.sort_server_labels).
"""

import unittest

from gui.main_window import sort_server_labels


class ServerSortingTest(unittest.TestCase):
    def test_grouped_by_engine_then_alphabetical(self):
        labels = [
            ("kz1", "kz1.tradesoft.ru", "mysql"),
            ("Zeta", "z.example.com", "mysql"),
            ("aisql", "aisql.tradesoft.corp", "mssql"),
            ("TESTING26", "192.168.128.160", "mssql"),
            ("ext4", "ext4.tradesoft.ru", "mysql"),
        ]
        result = [(d, h, e) for d, h, e in sort_server_labels(labels)]

        engines = [e for _, _, e in result]
        self.assertEqual(engines, ["mssql", "mssql", "mysql", "mysql", "mysql"])
        self.assertEqual(
            [d for d, _, _ in result],
            ["aisql", "TESTING26", "ext4", "kz1", "Zeta"],
        )

    def test_unknown_engine_goes_last(self):
        labels = [
            ("mysql-box", "m.example.com", "mysql"),
            ("odd", "o.example.com", "oracle"),
            ("mssql-box", "s.example.com", "mssql"),
        ]
        result = sort_server_labels(labels)
        self.assertEqual(
            [d for d, _, _ in result],
            ["mssql-box", "mysql-box", "odd"],
        )

    def test_sort_is_stable_and_case_insensitive(self):
        labels = [
            ("Beta", "b.example.com", "mysql"),
            ("alpha", "a.example.com", "mysql"),
        ]
        result = sort_server_labels(labels)
        self.assertEqual([d for d, _, _ in result], ["alpha", "Beta"])


if __name__ == "__main__":
    unittest.main()
