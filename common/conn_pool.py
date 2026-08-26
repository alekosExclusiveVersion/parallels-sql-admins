"""
common/conn_pool.py

Единый глобальный пул соединений к СУБД (используется MySQL и MSSQL).

Пул глобальный, а не thread-local: соединение к паре (host, database)
переиспользуется любыми потоками. Это исключает размножение соединений,
когда N рабочих потоков держат по N собственных коннектов к одному
серверу: последовательные запросы из разных потоков делят одно
соединение.

Ограничения (берутся из конфигурации клиента):
  - max_connections         — глобальный потолок одновременно «занятых»
    соединений (BoundedSemaphore с таймаутом ожидания);
  - max_per_key             — максимум одновременных соединений к одной
    паре (host, database);
  - pool_idle               — максимум простаивающих соединений одного
    ключа, которые держим открытыми;
  - max_idle_connections    — глобальный лимит простаивающих соединений;
  - idle_timeout            — простаивающее дольше закрывается.

Повторное вхождение в контекст connect() того же потока для того же
ключа отдаёт то же самое соединение (вложенный acquire не открывает
новый коннект и не занимает дополнительный слот).

Мёртвые соединения пересоздаются: перед повторным использованием
проверяется alive_check (для MySQL — ping). Если пул исчерпан дольше
acquire_timeout — бросается PoolTimeout вместо вечного ожидания.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional


class PoolTimeout(TimeoutError):
    """Пул не выдал соединение за acquire_timeout секунд."""


class _PooledConn:
    __slots__ = ("conn", "in_use", "owner", "depth", "last_used")

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.in_use = False
        self.owner: Optional[int] = None
        self.depth = 0
        self.last_used = 0.0


class _KeyPool:
    __slots__ = ("key", "conns", "slots")

    def __init__(self, key: tuple, max_per_key: int) -> None:
        self.key = key
        self.conns: list[_PooledConn] = []
        self.slots = threading.Semaphore(max(1, max_per_key))


class ConnectionPool:
    def __init__(
        self,
        cfg: Any,
        open_conn: Callable[[str, Optional[str]], Any],
        alive_check: Optional[Callable[[Any], bool]] = None,
        acquire_timeout: float = 10.0,
        name: str = "pool",
    ) -> None:
        # cfg — замыкание на клиент (lambda: self.cfg), чтобы подмена
        # конфигурации клиентом (тесты) применялась к пулу автоматически.
        self._cfg = cfg
        self._open = open_conn
        self._alive = alive_check
        self._acquire_timeout = float(acquire_timeout)
        self._name = name

        self._lock = threading.Lock()
        self._entries: dict[tuple, _KeyPool] = {}
        self._total = threading.BoundedSemaphore(
            max(1, int(self.cfg.max_connections))
        )
        self._idle_count = 0

    @property
    def cfg(self) -> Any:
        return self._cfg() if callable(self._cfg) else self._cfg

    # ----------------------------------------------------------
    # Публичный API
    # ----------------------------------------------------------

    def acquire(self, host: str, database: Optional[str] = None) -> Any:
        key = (host, database)
        tid = threading.get_ident()
        now = time.monotonic()

        with self._lock:
            kp = self._entries.get(key)
            if kp is None:
                kp = self._entries[key] = _KeyPool(key, self.cfg.max_per_key)
            else:
                # Вложенный acquire того же потока/ключа — то же соединение.
                for pc in kp.conns:
                    if pc.in_use and pc.owner == tid:
                        pc.depth += 1
                        pc.last_used = now
                        return pc.conn
            self._evict_key_locked(kp)

        # Слоты: сначала глобальный, потом по ключу (порядок исключает
        # циклическое ожидание между потоками).
        timeout = float(
            getattr(self.cfg, "acquire_timeout", self._acquire_timeout)
        )
        if not self._total.acquire(timeout=timeout):
            raise PoolTimeout(
                f"pool '{self._name}': лимит одновременных соединений "
                f"исчерпан ({self.cfg.max_connections}) дольше "
                f"{timeout:g} c"
            )
        if not kp.slots.acquire(timeout=timeout):
            self._total.release()
            raise PoolTimeout(
                f"pool '{self._name}': слишком много соединений к "
                f"{host} ({self.cfg.max_per_key})"
            )

        try:
            for _ in range(2):
                with self._lock:
                    pc = self._pick_idle(kp, tid, now)

                if pc is not None:
                    fresh = (now - pc.last_used) < 30
                    if fresh or self._alive is None or self._alive(pc.conn):
                        return pc.conn
                    # Соединение сдохло в простое — убираем и пересоздаём
                    # (счётчик idle уже уменьшен в _pick_idle).
                    with self._lock:
                        self._remove_pc(kp, pc)
                    continue

                # Нет свободного соединения — открываем новое.
                conn = self._open(host, database)
                with self._lock:
                    pc = _PooledConn(conn)
                    pc.in_use = True
                    pc.owner = tid
                    pc.depth = 1
                    pc.last_used = now
                    kp.conns.append(pc)
                    return conn
        except Exception:
            self._total.release()
            kp.slots.release()
            raise

        raise PoolTimeout(
            f"pool '{self._name}': не удалось получить соединение к {host}"
        )

    def release(self, host: str, database: Optional[str], raw_conn: Any) -> None:
        key = (host, database)
        tid = threading.get_ident()

        with self._lock:
            kp = self._entries.get(key)
            if kp is None:
                return

            for pc in kp.conns:
                if pc.conn is not raw_conn:
                    continue

                if pc.owner == tid:
                    pc.depth -= 1
                    if pc.depth > 0:
                        return
                    pc.depth = 0
                    pc.in_use = False
                    pc.owner = None
                    pc.last_used = time.monotonic()
                    self._idle_count += 1
                else:
                    # Релиз не владельцем (нештатно) — считаем свободным.
                    pc.in_use = False
                    pc.owner = None
                    pc.depth = 0
                    pc.last_used = time.monotonic()
                    self._idle_count += 1

                self._evict_key_locked(kp)
                self._evict_global_locked()
                self._total.release()
                kp.slots.release()
                return

    def close_all(self) -> None:
        """Закрывает все соединения пула (завершение приложения)."""
        with self._lock:
            for kp in self._entries.values():
                for pc in kp.conns:
                    try:
                        pc.conn.close()
                    except Exception:
                        pass
            self._entries.clear()
            self._idle_count = 0

    def debug_state(self) -> dict:
        """Снимок пула для тестов: {key: {...}}."""
        with self._lock:
            out: dict = {}
            for key, kp in self._entries.items():
                out[key] = {
                    "depth": sum(pc.depth for pc in kp.conns if pc.in_use),
                    "last_used": max(
                        (pc.last_used for pc in kp.conns), default=0.0
                    ),
                    "conn": kp.conns[0].conn if kp.conns else None,
                    "conns": [pc.conn for pc in kp.conns],
                    "in_use": [pc.conn for pc in kp.conns if pc.in_use],
                    "idle": [pc.conn for pc in kp.conns if not pc.in_use],
                }
            return out

    @property
    def idle_count(self) -> int:
        with self._lock:
            return self._idle_count

    @property
    def active_count(self) -> int:
        """Число соединений, занятых прямо сейчас (in_use)."""
        with self._lock:
            return sum(
                1
                for kp in self._entries.values()
                for pc in kp.conns
                if pc.in_use
            )

    @property
    def slots_available(self) -> int:
        """Сколько соединений можно ещё занять без превышения
        глобального потолка max_connections."""
        return max(0, int(self.cfg.max_connections) - self.active_count)

    def active_by_key(self) -> dict:
        """Занятость соединений по ключам (host, database) для диагностики."""
        with self._lock:
            return {
                key: {
                    "in_use": sum(1 for pc in kp.conns if pc.in_use),
                    "idle": sum(1 for pc in kp.conns if not pc.in_use),
                    "total": len(kp.conns),
                }
                for key, kp in self._entries.items()
            }

    # ----------------------------------------------------------
    # Внутренние хелперы (все под self._lock)
    # ----------------------------------------------------------

    def _pick_idle(
        self,
        kp: _KeyPool,
        tid: int,
        now: float,
    ) -> Optional[_PooledConn]:
        for pc in kp.conns:
            if pc.in_use:
                continue
            pc.in_use = True
            pc.owner = tid
            pc.depth = 1
            self._idle_count -= 1
            return pc
        return None

    def _remove_pc(self, kp: _KeyPool, pc: _PooledConn) -> None:
        try:
            kp.conns.remove(pc)
        except ValueError:
            return
        try:
            pc.conn.close()
        except Exception:
            pass

    def _evict_key_locked(self, kp: _KeyPool) -> None:
        """Ленивая зачистка простаивающих соединений одного ключа."""
        now = time.monotonic()
        idle_timeout = int(self.cfg.idle_timeout or 0)
        pool_idle = max(1, int(self.cfg.pool_idle or 1))

        idle = [pc for pc in kp.conns if not pc.in_use]
        idle.sort(key=lambda pc: pc.last_used)

        if idle_timeout > 0:
            cutoff = now - idle_timeout
            for pc in list(idle):
                if pc.last_used < cutoff:
                    self._remove_pc(kp, pc)
                    self._idle_count -= 1
                    idle.remove(pc)

        if len(idle) > pool_idle:
            for pc in idle[: len(idle) - pool_idle]:
                self._remove_pc(kp, pc)
                self._idle_count -= 1
            idle = idle[len(idle) - pool_idle:]

    def _evict_global_locked(self) -> None:
        """Глобальный лимит простаивающих соединений: закрывает самые
        старые idle-соединения по всем ключам, пока счётчик не упадёт."""
        max_idle = max(1, int(self.cfg.max_idle_connections or 1))

        if self._idle_count <= max_idle:
            return

        idle = [
            (pc, kp)
            for kp in self._entries.values()
            for pc in kp.conns
            if not pc.in_use
        ]
        idle.sort(key=lambda t: t[0].last_used)

        for pc, kp in idle[: self._idle_count - max_idle]:
            self._remove_pc(kp, pc)
            self._idle_count -= 1
