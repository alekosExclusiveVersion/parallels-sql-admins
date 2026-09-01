"""
tests/test_db_search.py

Тесты поиска БД (backend/db_search_worker.py -> common/mysql_client.py):
- поиск по маске имени (SHOW DATABASES LIKE) с дозаполнением
  домена (site) из cfg_settings.csSiteDomain найденных БД;
- доменная маска (с точкой) дополнительно находит БД по совпадению
  csSiteDomain (cfg_settings) и по базовому имени (activauto.ru → activauto);
- объединение результатов без дублей;
- graceful fallback, когда чтение настроек недоступно;
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

        if "information_schema.tables" in sql:
            # filter_databases_with_settings_conn: список БД с таблицей настроек
            self._result = self.owner.settings_tables_result
        elif "stg_value LIKE" in sql:
            # поиск по домену (UNION ALL ... WHERE stg_value LIKE ...)
            if self.owner.raise_on_domain:
                raise RuntimeError("SELECT command denied to user")
            self._result = self.owner.domain_result
        elif "SELECT stg_value" in sql:
            # дозаполнение домена: точечный SELECT stg_value для одной БД
            db = self._db_ident(sql)
            value = self.owner.settings_sites.get(db, "")
            self._result = [{"stg_value": value}] if value else []
        elif "SHOW DATABASES" in sql and "LIKE" not in sql:
            # list_databases_conn: полный перечень БД (без маски)
            self._result = self.owner.show_all_result
        else:
            self._result = self.owner.show_result

        return 0

    @staticmethod
    def _db_ident(sql):
        """ar_shop_ru из SELECT ... FROM `ar_shop_ru`.`cfg_settings`."""
        start = sql.find("`")
        if start < 0:
            return ""
        end = sql.find("`", start + 1)
        return sql[start + 1:end] if end > start else ""

    def fetchall(self):
        return self._result


class SearchConn:
    def __init__(
        self,
        host,
        show_result,
        show_all_result,
        settings_tables_result=None,
        settings_sites=None,
        domain_result=None,
    ):
        self.host = host
        self._psql_db = None
        self.show_result = show_result
        self.show_all_result = show_all_result
        self.settings_tables_result = settings_tables_result or []
        self.settings_sites = settings_sites or {}
        self.domain_result = domain_result or []
        self.raise_on_domain = False
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
    def __init__(
        self,
        show_result=None,
        show_all_result=None,
        settings_tables_result=None,
        settings_sites=None,
        domain_result=None,
        raise_on_domain=False,
    ):
        self.show_result = show_result or []
        self.show_all_result = show_all_result or (show_result or [])
        self.settings_tables_result = settings_tables_result or []
        self.settings_sites = settings_sites or {}
        self.domain_result = domain_result or []
        self.raise_on_domain = raise_on_domain
        self.opens = 0
        self.conns = []

    def open(self, host, database=None):
        self.opens += 1
        conn = SearchConn(
            host,
            self.show_result,
            self.show_all_result,
            self.settings_tables_result,
            self.settings_sites,
            self.domain_result,
        )
        conn.raise_on_domain = self.raise_on_domain
        self.conns.append(conn)
        return conn


def _db_names(items):
    """Утилита: list[dict] → list[str] имён БД."""
    return [item["db"] for item in items]


def _db_sites(items):
    """Утилита: list[dict] → dict{db: site}."""
    return {item["db"]: item.get("site", "") for item in items}


class TestDatabaseSearch(unittest.TestCase):
    def _client(
        self,
        show_result,
        show_all_result=None,
        settings_tables_result=None,
        settings_sites=None,
        domain_result=None,
        raise_on_domain=False,
    ):
        factory = SearchFactory(
            show_result,
            show_all_result,
            settings_tables_result=settings_tables_result,
            settings_sites=settings_sites,
            domain_result=domain_result,
            raise_on_domain=raise_on_domain,
        )
        client = MySQLClient()
        client._open_connection = factory.open
        client._discard_conn = lambda conn: conn.close()
        return client, factory

    def test_search_by_name_enriches_sites_from_settings(self):
        show = [
            {"Database": "ar_example_com"},
            {"Database": "ar_shop_ru"},
        ]
        # cfg_settings есть у обоих, но csSiteDomain заполнен только у shop_ru
        tables = [
            {"table_schema": "ar_example_com"},
            {"table_schema": "ar_shop_ru"},
        ]
        sites = {"ar_shop_ru": "shop.ru"}
        client, factory = self._client(
            show,
            settings_tables_result=tables,
            settings_sites=sites,
        )

        result = client.search_databases("h1", "ar_%")

        self.assertEqual(
            _db_names(result), ["ar_example_com", "ar_shop_ru"]
        )
        # домены дозаполнены из cfg_settings и при поиске по имени (без точки)
        sites = _db_sites(result)
        self.assertEqual(sites.get("ar_shop_ru"), "shop.ru")
        self.assertEqual(sites.get("ar_example_com"), "")
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 5)
        self.assertIn("SHOW DATABASES", conn.executions[1][0])
        self.assertIn("information_schema.tables", conn.executions[2][0])
        self.assertIn("stg_value", conn.executions[3][0])
        self.assertIn("stg_value", conn.executions[4][0])

    def test_domain_mask_merges_settings_results(self):
        show = [{"Database": "ar_example_com"}]
        tables = [
            {"table_schema": "ar_example_com"},
            {"table_schema": "ar_example_com_db"},
            {"table_schema": "ar_other_site"},
        ]
        domain = [
            {"db_name": "ar_example_com_db", "stg_value": "example.com"},
            {"db_name": "ar_other_site", "stg_value": "other.com"},
        ]
        client, factory = self._client(
            show,
            settings_tables_result=tables,
            domain_result=domain,
        )

        result = client.search_databases("h1", "example.com")

        names = _db_names(result)
        self.assertIn("ar_example_com", names)
        self.assertIn("ar_example_com_db", names)
        self.assertIn("ar_other_site", names)
        # найденные по домену БД сохраняют site из cfg_settings
        sites = _db_sites(result)
        self.assertEqual(sites.get("ar_example_com_db"), "example.com")
        self.assertEqual(sites.get("ar_other_site"), "other.com")

    def test_domain_mask_dedupes_results(self):
        show = [{"Database": "ar_example_com"}]
        tables = [
            {"table_schema": "ar_example_com"},
            {"table_schema": "ar_example_com_db"},
        ]
        domain = [
            {"db_name": "ar_example_com", "stg_value": "example.com"},
            {"db_name": "ar_example_com_db", "stg_value": "example.com"},
        ]
        client, factory = self._client(
            show,
            settings_tables_result=tables,
            domain_result=domain,
        )

        result = client.search_databases("h1", "example.com")

        self.assertEqual(
            _db_names(result), ["ar_example_com", "ar_example_com_db"]
        )

    def test_domain_lookup_unavailable_falls_back(self):
        show = [{"Database": "ar_example_com"}]
        tables = [{"table_schema": "ar_example_com"}]
        client, factory = self._client(
            show,
            settings_tables_result=tables,
            raise_on_domain=True,
        )

        result = client.search_databases("h1", "example.com")

        # база по имени всё равно находится через SHOW LIKE '%example%'
        self.assertEqual(_db_names(result), ["ar_example_com"])
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 8)

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
        client, factory = self._client(show)

        result = client.search_databases("h1", "activauto.ru")

        names = _db_names(result)
        self.assertIn("autoprice_activautoru", names)
        self.assertIn("ar_activautoru", names)
        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 6)
        base_sql = conn.executions[4][0]
        self.assertIn("SHOW DATABASES", base_sql)
        self.assertIn("activauto", base_sql)

    def test_base_name_too_short_skipped(self):
        """a.ru → base='a' (< 3) → пропуск base search."""
        show = [{"Database": "a_ru"}]
        client, factory = self._client(show)

        result = client.search_databases("h1", "a.ru")

        self.assertEqual(_db_names(result), ["a_ru"])
        conn = factory.conns[0]
        # 4 queries: SET SESSION, SHOW (mask), SHOW (list), site-fill-фильтр
        self.assertEqual(len(conn.executions), 4)

    def test_base_name_with_wildcards_skipped(self):
        """*shop*.com → base='*shop*' (содержит *) → пропуск."""
        show = [{"Database": "shop_com"}]
        client, factory = self._client(show)

        result = client.search_databases("h1", "*shop*.com")

        conn = factory.conns[0]
        # 4 queries: SET SESSION, SHOW (mask), SHOW (list), site-fill-фильтр
        self.assertEqual(len(conn.executions), 4)

    def test_base_name_with_underscore_skipped(self):
        """my_site.com → base='my_site' (содержит _) → пропуск."""
        show = [{"Database": "my_site_com"}]
        client, factory = self._client(show)

        result = client.search_databases("h1", "my_site.com")

        conn = factory.conns[0]
        self.assertEqual(len(conn.executions), 4)

    def test_domain_returns_site(self):
        """Поиск по домену возвращает site для найденных БД."""
        show = []
        show_all = [{"Database": "ar_shop_ru"}]
        tables = [{"table_schema": "ar_shop_ru"}]
        domain = [
            {"db_name": "ar_shop_ru", "stg_value": "shop.ru"},
        ]
        client, factory = self._client(
            show,
            show_all_result=show_all,
            settings_tables_result=tables,
            domain_result=domain,
        )

        result = client.search_databases("h1", "shop.ru")

        sites = _db_sites(result)
        self.assertEqual(sites.get("ar_shop_ru"), "shop.ru")


if __name__ == "__main__":
    unittest.main()