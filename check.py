"""
check.py

Поиск проектов, где:
csSystemCountry == country из config.ini

Выводит:
SERVER | DATABASE | COUNTRY | TARGET_VALUE

Результат сохраняется в CSV.
"""

from __future__ import annotations

import csv
from pathlib import Path

import common.config as C

APP = Path.home() / "Library/Application Support/Parallels SQL Admin"

if (APP / "config.ini").exists():
    cfg = C.load_config(APP / "config.ini")
    object.__setattr__(cfg.advanced, "servers_file", str(APP / "servers.json"))
    C.config = cfg

from common.config import config
from common.logger import logger
from common.mysql_client import mysql
from common.server_registry import ENGINE_MYSQL
from common.worker import worker_pool
from backend.repository import Repository


_RU_COUNTRIES = {"russia", "ru", "россия"}


def process_server(server: str):
    rows: list[dict] = []

    logger.info(f"{server}: подключение")

    # Одно соединение на сервер: список БД, проверка наличия cfg_settings
    # (одним запросом на чанк) и пакетное чтение настроек выполняются
    # без переподключений.
    with mysql.connect(server) as conn:

        databases = mysql.list_databases_conn(conn)

        eligible = mysql.filter_databases_with_settings_conn(
            conn,
            databases,
        )

        scanned = {
            item["database_name"]: item
            for item in mysql.scan_settings_batch(conn, eligible)
        }

    for db in eligible:

        item = scanned.get(db)

        if item is None:
            continue

        country = (item.get("country") or "").lower()

        if country not in _RU_COUNTRIES:
            continue

        rows.append(
            {
                "server": server,
                "database": db,
                "country": country,
                "value": item.get("target_value") or "",
            }
        )

    logger.success(f"{server}: найдено {len(rows)} проектов")

    return rows


def save_csv(data: list[dict]) -> None:

    log_dir = config.logging.directory
    log_dir.mkdir(exist_ok=True)

    csv_file = log_dir / config.logging.csv

    with csv_file.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.writer(f)

        writer.writerow(
            [
                "SERVER",
                "DATABASE",
                "COUNTRY",
                config.filter.target_setting,
            ]
        )

        for item in data:
            writer.writerow(
                [
                    item["server"],
                    item["database"],
                    item["country"],
                    item["value"],
                ]
            )

    logger.success(f"CSV сохранён: {csv_file}")


def main():

    specs = Repository().load_servers()

    servers = [s.host for s in specs if s.engine == ENGINE_MYSQL and s.host]

    logger.info(f"MySQL серверов: {len(servers)}")

    results = worker_pool.run(
        servers,
        process_server,
    )

    all_rows = []

    print()
    print(
        f'{"SERVER":20} '
        f'{"DATABASE":35} '
        f'{"COUNTRY":10} '
        f'{config.filter.target_setting}'
    )
    print("-" * 95)

    for result in results:

        if not result.success:
            continue

        for row in result.value:

            print(
                f'{row["server"]:20} '
                f'{row["database"]:35} '
                f'{row["country"]:10} '
                f'{row["value"]}'
            )

            all_rows.append(row)

    save_csv(all_rows)

    logger.success(
        f"Всего найдено проектов: {len(all_rows)}"
    )


if __name__ == "__main__":
    main()
