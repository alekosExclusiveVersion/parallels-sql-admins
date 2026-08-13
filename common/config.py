"""
common/config.py
Загрузка и валидация config.ini
"""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MySQLConfig:
    user: str
    password: str
    port: int
    connect_timeout: int
    read_timeout: int
    write_timeout: int
    retry: int
    pool_idle: int
    max_connections: int
    max_idle_connections: int
    idle_timeout: int
    max_per_key: int
    acquire_timeout: int


@dataclass(frozen=True)
class MSSQLConfig:
    user: str
    password: str
    port: int
    connect_timeout: int
    retry: int
    pool_idle: int
    idle_timeout: int
    max_idle_connections: int
    max_connections: int
    max_per_key: int
    acquire_timeout: int


@dataclass(frozen=True)
class PgsqlConfig:
    user: str
    password: str
    port: int
    connect_timeout: int
    retry: int
    pool_idle: int
    idle_timeout: int
    max_idle_connections: int
    max_connections: int
    max_per_key: int
    acquire_timeout: int


@dataclass(frozen=True)
class ParallelConfig:
    workers: int
    database_workers: int
    search_workers: int


@dataclass(frozen=True)
class SizesConfig:
    """Лимиты подсистемы подсчёта размеров БД/таблиц.

    max_connections — максимум одновременных соединений, которые может
        занять sizes-воркер (мягкий лимит поверх глобального пула);
    table_workers — параллельность запроса таблиц одной MSSQL-базы
        (без «взрыва» соединений: всё идёт через ключ (host, None));
    catalog_ttl — секунды, в течение которых каталог сервера отдаётся
        из кэша без обращения к БД (0 = кэш выключен).
    """

    max_connections: int
    table_workers: int
    catalog_ttl: int


@dataclass(frozen=True)
class FilterConfig:
    country: str
    country_setting: str
    target_setting: str
    target_value: str
    database_prefix: str
    exclude_database_regex: str


@dataclass(frozen=True)
class LoggingConfig:
    directory: Path
    csv: str
    errors: str
    run: str
    actions: str = "actions"
    max_bytes: int = 5_000_000
    backups: int = 3
    retention_days: int = 30
    verbose: bool = False


@dataclass(frozen=True)
class OutputConfig:
    color: bool
    progress: bool
    eta: bool
    speed: bool
    summary: bool


@dataclass(frozen=True)
class AdvancedConfig:
    ignore_databases: tuple[str, ...]
    settings_table: str
    batch_size: int
    export_csv: bool
    export_errors: bool
    servers_file: str


@dataclass(frozen=True)
class SecurityConfig:
    key_backend: str
    backup_count: int


@dataclass(frozen=True)
class Config:
    mysql: MySQLConfig
    mssql: MSSQLConfig
    pgsql: PgsqlConfig
    parallel: ParallelConfig
    sizes: SizesConfig
    filter: FilterConfig
    logging: LoggingConfig
    output: OutputConfig
    advanced: AdvancedConfig
    security: SecurityConfig


def _bool(cfg: ConfigParser, section: str, option: str) -> bool:
    return cfg.getboolean(section, option)


def load_config(config_file: str | Path | None = None) -> Config:
    if config_file is None:
        config_file = Path(__file__).resolve().parent.parent / "config.ini"

    config_file = Path(config_file)

    if not config_file.exists():
        raise FileNotFoundError(f"Файл конфигурации не найден: {config_file}")

    p = ConfigParser()
    p.read(config_file, encoding="utf-8")

    ignore = tuple(
        x.strip()
        for x in p.get(
            "advanced",
            "ignore_databases"
        ).replace("\n", "").split(",")
        if x.strip()
    )

    return Config(
        mysql=MySQLConfig(
            user=p.get("mysql", "user"),
            password=p.get("mysql", "password"),
            port=p.getint("mysql", "port", fallback=3306),
            connect_timeout=p.getint("mysql", "connect_timeout"),
            read_timeout=p.getint("mysql", "read_timeout"),
            write_timeout=p.getint("mysql", "write_timeout"),
            retry=p.getint("mysql", "retry"),
            pool_idle=p.getint("mysql", "pool_idle", fallback=4),
            max_connections=p.getint(
                "mysql",
                "max_connections",
                fallback=100,
            ),
            max_idle_connections=p.getint(
                "mysql",
                "max_idle_connections",
                fallback=16,
            ),
            idle_timeout=p.getint(
                "mysql",
                "idle_timeout",
                fallback=60,
            ),
            max_per_key=p.getint(
                "mysql",
                "max_per_key",
                fallback=4,
            ),
            acquire_timeout=p.getint(
                "mysql",
                "acquire_timeout",
                fallback=10,
            ),
        ),
        mssql=MSSQLConfig(
            user=p.get("mssql", "user", fallback="sa"),
            password=p.get("mssql", "password", fallback=""),
            port=p.getint("mssql", "port", fallback=1433),
            connect_timeout=p.getint("mssql", "connect_timeout", fallback=5),
            retry=p.getint("mssql", "retry", fallback=3),
            pool_idle=p.getint("mssql", "pool_idle", fallback=4),
            idle_timeout=p.getint("mssql", "idle_timeout", fallback=60),
            max_idle_connections=p.getint(
                "mssql",
                "max_idle_connections",
                fallback=16,
            ),
            max_connections=p.getint(
                "mssql",
                "max_connections",
                fallback=100,
            ),
            max_per_key=p.getint(
                "mssql",
                "max_per_key",
                fallback=4,
            ),
            acquire_timeout=p.getint(
                "mssql",
                "acquire_timeout",
                fallback=10,
            ),
        ),
        pgsql=PgsqlConfig(
            user=p.get("pgsql", "user", fallback="postgres"),
            password=p.get("pgsql", "password", fallback=""),
            port=p.getint("pgsql", "port", fallback=5432),
            connect_timeout=p.getint("pgsql", "connect_timeout", fallback=5),
            retry=p.getint("pgsql", "retry", fallback=3),
            pool_idle=p.getint("pgsql", "pool_idle", fallback=4),
            idle_timeout=p.getint("pgsql", "idle_timeout", fallback=60),
            max_idle_connections=p.getint(
                "pgsql",
                "max_idle_connections",
                fallback=16,
            ),
            max_connections=p.getint(
                "pgsql",
                "max_connections",
                fallback=100,
            ),
            max_per_key=p.getint(
                "pgsql",
                "max_per_key",
                fallback=4,
            ),
            acquire_timeout=p.getint(
                "pgsql",
                "acquire_timeout",
                fallback=10,
            ),
        ),
        parallel=ParallelConfig(
            workers=p.getint("parallel", "workers", fallback=8,),
            database_workers=p.getint("parallel", "database_workers", fallback=4,),
            search_workers=p.getint("parallel", "search_workers", fallback=4,),
        ),
        sizes=SizesConfig(
            max_connections=p.getint(
                "sizes", "max_connections", fallback=4
            ),
            table_workers=p.getint(
                "sizes",
                "table_workers",
                fallback=max(
                    1,
                    min(
                        p.getint(
                            "parallel", "database_workers", fallback=4
                        ),
                        4,
                    ),
                ),
            ),
            catalog_ttl=p.getint("sizes", "catalog_ttl", fallback=300),
        ),
        filter=FilterConfig(
            country=p.get("filter", "country").lower(),
            country_setting=p.get("filter", "country_setting"),
            target_setting=p.get("filter", "target_setting"),
            target_value=p.get("filter", "target_value"),
            database_prefix=p.get(
                "filter",
                "database_prefix",
                fallback="ar_",
            ),

            exclude_database_regex=p.get(
                "filter",
                "exclude_database_regex",
                fallback="",
            ),
        ),
        logging=LoggingConfig(
            directory=Path(p.get("logging", "directory")),
            csv=p.get("logging", "csv"),
            errors=p.get("logging", "errors"),
            run=p.get("logging", "run"),
            actions=p.get("logging", "actions", fallback="actions"),
            max_bytes=p.getint("logging", "max_bytes", fallback=5_000_000),
            backups=p.getint("logging", "backups", fallback=3),
            retention_days=p.getint("logging", "retention_days", fallback=30),
            verbose=_bool(p, "logging", "verbose"),
        ),
        output=OutputConfig(
            color=_bool(p, "output", "color"),
            progress=_bool(p, "output", "progress"),
            eta=_bool(p, "output", "eta"),
            speed=_bool(p, "output", "speed"),
            summary=_bool(p, "output", "summary"),
        ),
        advanced=AdvancedConfig(
            ignore_databases=ignore,
            settings_table=p.get("advanced", "settings_table"),
            batch_size=p.getint("advanced", "batch_size"),
            export_csv=_bool(p, "advanced", "export_csv"),
            export_errors=_bool(p, "advanced", "export_errors"),
            servers_file=p.get(
                "advanced",
                "servers_file",
                fallback="servers.json",
            ),
        ),
        security=SecurityConfig(
            key_backend=p.get(
                "security", "key_backend", fallback="macos_keychain"
            ),
            backup_count=p.getint(
                "security", "backup_count", fallback=5
            ),
        ),
    )


config = load_config()


if __name__ == "__main__":
    from pprint import pprint
    pprint(config)
