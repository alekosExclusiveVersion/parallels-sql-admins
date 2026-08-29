"""
tests/test_db_errors.py

Единичные тесты humanize_db_error: типовые англоязычные ошибки БД/пула
переводятся в русские формулировки, неизвестные тексты возвращаются как есть.
"""

import unittest

from common.db_errors import humanize_db_error


class TestHumanizeDbError(unittest.TestCase):
    def assert_russian(self, raw: str, expected_fragment: str):
        translated = humanize_db_error(raw)
        self.assertIn(expected_fragment, translated)
        self.assertNotIn(raw.lower(), translated.lower())

    def test_connection_failure(self):
        self.assert_russian(
            "Cannot open database \"ARSPARTS\" requested by the login.",
            "соединение с сервером",
        )

    def test_network_connect_error(self):
        self.assert_russian(
            "network-related or instance-specific error: connection refused",
            "соединение с сервером",
        )

    def test_login_failed(self):
        self.assert_russian("Login failed for user 'sa'.", "Не удалось войти")

    def test_wrong_password(self):
        self.assert_russian(
            "Access denied for user 'root'@'localhost' (using password: YES)",
            "Не удалось войти",
        )

    def test_permission_denied(self):
        self.assert_russian(
            "The server principal \"u1\" does not have permission to perform "
            "this operation.",
            "Недостаточно прав",
        )

    def test_database_in_use_for_single_user(self):
        self.assert_russian(
            "Cannot drop database because it is currently in use. "
            "ALTER DATABASE statement failed because database is in single-user mode.",
            "используется другим процессом",
        )

    def test_already_attached(self):
        self.assert_russian(
            "The database has already been attached to this server.",
            "уже присоединена",
        )

    def test_file_not_found(self):
        self.assert_russian(
            "Operating system error 2: The system cannot find the file "
            "\"c:\\data\\db.mdf\".",
            "файл базы данных",
        )

    def test_sqlite_open_failure(self):
        self.assert_russian("unable to open database file", "файл базы данных")

    def test_pool_timeout(self):
        self.assert_russian(
            "pool 'mssql': не удалось получить соединение к 192.168.128.160:1433",
            "Превышено время ожидания соединения",
        )

    def test_pool_limit_reached(self):
        self.assert_russian(
            "pool 'mysql': лимит одновременных соединений исчерпан (5) дольше 10 c",
            "Превышено время ожидания соединения",
        )

    def test_query_timeout(self):
        self.assert_russian(
            "Query timeout expired. The operation was completed successfully.",
            "ожидания ответа",
        )

    def test_database_already_exists(self):
        self.assert_russian("Database 'x' already exists.", "уже существует")

    def test_unknown_message_passed_through(self):
        self.assertEqual(
            humanize_db_error("Something entirely new happened"),
            "Something entirely new happened",
        )

    def test_empty_message(self):
        self.assertEqual(humanize_db_error(""), "")

    def test_russian_message_left_untouched(self):
        self.assertEqual(
            humanize_db_error("Неожиданная ошибка драйвера"),
            "Неожиданная ошибка драйвера",
        )


if __name__ == "__main__":
    unittest.main()