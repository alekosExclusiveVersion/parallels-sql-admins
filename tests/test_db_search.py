"""
tests/test_db_search.py

Тесты поиска БД (backend/db_search_worker.py -> common/mysql_client.py):
- поиск по маске имени (SHOW DATABASES LIKE) без обращения к psa;
- доменная маска (с точкой) дополнительно находит БД через Plesk psa;
- извлечение базового имени (activauto.ru → activauto);
- объединение результатов без дублей;
- graceful fallback, когда psa недоступен;
- фильтрация слишком коротких base (< 3 символов);
- фильтрация base с wildcards.
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
        elif "SHOW DATABASES" in sql:
            self._result = self.owner.show_result
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


def _db_names(items):
    """Утилита: list[dict] → list[str] имён БД."""
    return [item["db"] for item in items]


def _db_sites(items):
    """Утилита: list[dict] → dict{db: site}."""
    return {item["db"]: item.get("site", "") for item in items}


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

        self.assertEqual(
            _db_names(result), ["ar_example_com", "ar_shop_ru"]
        )
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 2)
        self.assertIn("SHOW DATABASES", conn.executions[1][0])
        self.assertNotIn("psa.data_bases", conn.executions[1][0])

    def test_domain_mask_merges_psa_results(self):
        show = [{"Database": "ar_example_com"}]
        psa = [
            {"db_name": "ar_example_com_db", "site_name": "example.com"},
            {"db_name": "ar_other_site", "site_name": "other.com"},
        ]
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "example.com")

        names = _db_names(result)
        self.assertIn("ar_example_com", names)
        self.assertIn("ar_example_com_db", names)
        self.assertIn("ar_other_site", names)
        # psa sites preserved
        sites = _db_sites(result)
        self.assertEqual(sites.get("ar_example_com_db"), "example.com")
        self.assertEqual(sites.get("ar_other_site"), "other.com")

    def test_domain_mask_dedupes_results(self):
        show = [{"Database": "ar_example_com"}]
        psa = [
            {"db_name": "ar_example_com", "site_name": "example.com"},
            {"db_name": "ar_example_com_db", "site_name": "example.com"},
        ]
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "example.com")

        self.assertEqual(
            _db_names(result), ["ar_example_com", "ar_example_com_db"]
        )

    def test_psa_unavailable_falls_back(self):
        show = [{"Database": "ar_example_com"}]
        factory = SearchFactory(show, raise_on_psa=True)
        client = MySQLClient()
        client._open_connection = factory.open
        client._discard_conn = lambda conn: conn.close()

        result = client.search_databases("h1", "example.com")

        self.assertEqual(_db_names(result), ["ar_example_com"])
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 4)

    def test_empty_mask_returns_empty(self):
        client, factory = self._client([{"Database": "ar_example_com"}])

        self.assertEqual(client.search_databases("h1", "   "), [])
        self.assertEqual(factory.opens, 0)

    def test_base_name_extraction(self):
        """activauto.ru → SHOW DATABASES LIKE '%activauto%'"""
        show = [
            {"Database": "autoprice_activautoru"},
            {"Database": "ar_activautoru"},
        ]
        psa = []
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "activauto.ru")

        names = _db_names(result)
        self.assertIn("autoprice_activautoru", names)
        self.assertIn("ar_activautoru", names)
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 4)
        base_sql = conn.executions[3][0]
        self.assertIn("SHOW DATABASES", base_sql)
        self.assertIn("activauto", base_sql)

    def test_base_name_too_short_skipped(self):
        """a.ru → base='a' (< 3) → пропуск base search."""
        show = [{"Database": "a_ru"}]
        psa = []
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "a.ru")

        self.assertEqual(_db_names(result), ["a_ru"])
        conn = factory.conns[0]
        # 3 queries: SET SESSION, SHOW (mask), psa — base search skipped
        self.assertEqual(len(conn.executions), 3)

    def test_base_name_with_wildcards_skipped(self):
        """*shop*.com → base='*shop*' (содержит *) → пропуск."""
        show = [{"Database": "shop_com"}]
        psa = []
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "*shop*.com")

        conn = factory.conns[0]
        # 3 queries: SET SESSION, SHOW (mask), psa — base search skipped
        self.assertEqual(len(conn.executions), 3)

    def test_base_name_with_underscore_skipped(self):
        """my_site.com → base='my_site' (содержит _) → пропуск."""
        show = [{"Database": "my_site_com"}]
        psa = []
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "my_site.com")

        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 3)

    def test_psa_returns_site(self):
        """psa возвращает site_name для найденных БД."""
        show = []
        psa = [
            {"db_name": "ar_shop_ru", "site_name": "shop.ru"},
        ]
        client, factory = self._client(show, psa)

        result = client.search_databases("h1", "shop.ru")

        sites = _db_sites(result)
        self.assertEqual(sites.get("ar_shop_ru"), "shop.ru")


if __name__ == "__main__":
    unittest.main()
