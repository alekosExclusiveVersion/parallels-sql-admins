"""
backend/repository.py

Фасад над common.server_registry: загрузка/сохранение списка серверов
с персональными реквизитами подключения (MySQL/MSSQL).
"""

from common.server_registry import ServerSpec, registry


class Repository:

    def __init__(self):
        self._registry = registry

    def load_servers(self):
        return self._registry.load()

    def reload_servers(self):
        """Принудительное перечитывание servers.json с диска."""
        return self._registry.reload()

    @property
    def servers(self):
        return self._registry.specs()

    def add_server(self, spec: ServerSpec) -> None:
        self._registry.add(spec)

    def update_server(self, old_host: str, spec: ServerSpec) -> None:
        self._registry.update(old_host, spec)

    def remove_server(self, host: str) -> bool:
        return self._registry.remove(host)

    def hosts(self) -> list[str]:
        return self._registry.hosts()
