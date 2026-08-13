"""
tests/test_db_search.py

Тесты поиска БД (backend/db_search_worker.py -> common/mysql_client.py):
- поиск по маске имени (SHOW DATABASES LIKE) без обращения к psa;
- доменная маска (с точкой) дополнительно находит БД через Plesk psa;
- объединение результатов без дублей;
- graceful fallback, когда psa недоступен.
"""

import unittest

from pymysql.err import OperationalError

from common.mysql_client import MySQLClient


class SearchCursor:
    def __init__(self, owner):
        self.owner = owner
        self._result = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.owner.executions.append((sql, params))

        if "FROM psa.data_bases" in sql:
            if self.owner.raise_on_psa:
                raise RuntimeError("SELECT command denied to user")
            self._result = self.owner.psa_result
        else:
            self._result = self.owner.show_result

        return 0

    def fetchall(self):
        return self._result


class SearchConn:
    def __init__(self, host, show_result, psa_result):
        self.host = host
        self._psql_db = None
        self.show_result = show_result
        self.psa_result = psa_result
        self.raise_on_psa = False
        self.executions = []
        self.alive = True

    def escape(self, value):
        return (
            "'"
            + str(value).replace("\\", "\\\\").replace("'", "\\'")
            + "'"
        )

    def ping(self, reconnect=False):
        if not self.alive:
            raise OperationalError(2006, "Server has gone away")

    def cursor(self):
        return SearchCursor(self)

    def close(self):
        self.alive = False


class SearchFactory:
    def __init__(self, show_result=None, psa_result=None, raise_on_psa=False):
        self.show_result = show_result or []
        self.psa_result = psa_result or []
        self.raise_on_psa = raise_on_psa
        self.opens = 0
        self.conns = []

    def open(self, host, database=None):
        self.opens += 1
        conn = SearchConn(host, self.show_result, self.psa_result)
        conn.raise_on_psa = self.raise_on_psa
        self.conns.append(conn)
        return conn


class TestDatabaseSearch(unittest.TestCase):
    def _client(self, show_result, psa_result=None):
        factory = SearchFactory(show_result, psa_result)
        client = MySQLClient()
        client._open_connection = factory.open
        client._discard_conn = lambda conn: conn.close()
        return client, factory

    def test_search_by_name_skips_psa(self):
        show = [
            {"Database": "ar_example_com"},
            {"Database": "ar_shop_ru"},
        ]
        client, factory = self._client(show)

        result = client.search_databases("h1", "ar_%")

        self.assertEqual(result, ["ar_example_com", "ar_shop_ru"])
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 1)
        self.assertIn("SHOW DATABASES", conn.executions[0][0])
        self.assertNotIn("psa.data_bases", conn.executions[0][0])

    def test_domain_mask_merges_psa_results(self):
        show = [{"Database": "ar_example_com"}]
        psa = [
            {"db_name": "ar_example_com_db"},
            {"db_name": "ar_other_site"},
        ]
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "example.com")

        self.assertEqual(
            result,
            ["ar_example_com", "ar_example_com_db", "ar_other_site"],
        )
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 2)
        psa_sql = conn.executions[1][0]
        self.assertIn("FROM psa.data_bases", psa_sql)
        self.assertIn("LIKE '%example.com%'", psa_sql)

    def test_domain_mask_dedupes_results(self):
        show = [{"Database": "ar_example_com"}]
        psa = [
            {"db_name": "ar_example_com"},
            {"db_name": "ar_example_com_db"},
        ]
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "example.com")

        self.assertEqual(result, ["ar_example_com", "ar_example_com_db"])

    def test_psa_unavailable_falls_back(self):
        show = [{"Database": "ar_example_com"}]
        factory = SearchFactory(show, raise_on_psa=True)
        client = MySQLClient()
        client._open_connection = factory.open
        client._discard_conn = lambda conn: conn.close()

        result = client.search_databases("h1", "example.com")

        self.assertEqual(result, ["ar_example_com"])
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 2)

    def test_empty_mask_returns_empty(self):
        client, factory = self._client([{"Database": "ar_example_com"}])

        self.assertEqual(client.search_databases("h1", "   "), [])
        self.assertEqual(factory.opens, 0)


if __name__ == "__main__":
    unittest.main()
