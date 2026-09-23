"""
pricing_alert.py

Мониторинг веб-проценки: опрашивает Grafana (ClickHouse provider_logs /
provider_runtime_logs), сравнивает последний час с тем же часом сутки
назад и при аномалии уведомляет во все каналы (macOS-баннер, B24,
Telegram) с гиперссылками на дашборд Grafana за окно сбоя.

Триггеры (пороги в pricing_alert_config.json):
  runtime  — среднее время проценки на поставщике >= abs_sec
             и в INCREASE_FACTOR раз больше нормы;
  errors   — доля ответов поставщиков с кодом >=500 >= abs_pct
             и в INCREASE_FACTOR раз больше нормы;
  volume   — запросов проценки упало ниже (1 - volume_drop) от нормы.

Дедупликация: уведомляем при старте инцидента, затем раз в escalate_every
часов («продолжается N ч»), при восстановлении — «всё нормально».

При инциденте (один раз) дополнительно запускается detect_pricing_degradation.py
(MySQL-скан) ради списка сайтов с «Превышено время ожидания».

Секреты: Grafana-логин/пароль берутся из Keychain (opencode.grafana.*),
Telegram-токен/чат — из окружения (launchctl setenv) либо keychain.

Запуск: /opt/homebrew/bin/python3 ~/Work/scripts/parallels-sql-admins/pricing_alert.py
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent
CONFIG = REPO / "pricing_alert_config.json"
STATE = REPO / "logs" / "pricing_alert_state.json"
TS_B24 = Path.home() / "Work/ts-b24/scripts"

sys.path.insert(0, str(TS_B24))
from b24_client import B24Client  # noqa: E402

GRAFANA = "https://grafana.tradesoft.ru"
DASH_UID = "000000020"
DS_UID = "000000003"
CH_LOGIN = "opencode.grafana.login"
CH_PASSWORD = "opencode.grafana.password"

WINDOW_SEC = 3600
SHIFT_SEC = 86400
MIN_PROVIDER_N = 50
MAX_PROVIDERS_IN_MSG = 6
MAX_SITES_IN_MSG = 8
PHASE2 = REPO / "detect_pricing_degradation.py"


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _keychain_get(service: str) -> str:
    res = subprocess.run(
        [str(Path.home() / "bin/keychain-get"), service],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "KEYCHAIN_ASK": "0"},
    )
    if res.returncode != 0:
        raise RuntimeError(f"keychain-get {service}: rc={res.returncode}")
    return res.stdout.strip()


def _load_config() -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    defaults = {
        "increase_factor": 3.0,
        "runtime_abs_sec": 10.0,
        "errors_abs_pct": 5.0,
        "volume_drop": 0.7,
        "escalate_every_hours": 1.0,
        "window_seconds": WINDOW_SEC,
    }
    for k, v in defaults.items():
        cfg.setdefault(k, v)
    return cfg


def _load_state() -> dict:
    default = {"active": False, "active_since": "", "last_notify": "", "alerted_hours": 0}
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return default


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE)


def _grafana_query(cfg: dict, raw_query: str, t_from: int, t_to: int) -> list[tuple[str, list]]:
    payload = json.dumps({
        "from": str(t_from * 1000), "to": str(t_to * 1000),
        "queries": [{
            "refId": "A",
            "datasource": {"type": "vertamedia-clickhouse-datasource", "uid": DS_UID},
            "rawQuery": raw_query,
            "format": "table",
        }],
    }).encode("utf-8")
    req = urllib.request.Request(
        GRAFANA + "/api/ds/query", data=payload,
        headers={"Content-Type": "application/json"},
    )
    login = _keychain_get(CH_LOGIN)
    password = _keychain_get(CH_PASSWORD)
    import base64
    req.add_header(
        "Authorization",
        "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode(),
    )
    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"Grafana request failed: {last_err}")
    frames: list[tuple[str, list]] = []
    for frame in body["results"]["A"]["frames"]:
        fields = [f["name"] for f in frame["schema"]["fields"]]
        values = frame["data"]["values"]
        for i, name in enumerate(fields):
            if i < len(values) and values[i]:
                frames.append((name, values[i]))
    return frames


def _rows(frames: list[tuple[str, list]]) -> list[dict]:
    by_name: dict[str, list] = {}
    for name, values in frames:
        by_name[name] = values
    if not by_name:
        return []
    n = max(len(v) for v in by_name.values())
    out = []
    for i in range(n):
        row = {}
        for name, values in by_name.items():
            row[name] = values[i] if i < len(values) else None
        out.append(row)
    return out


def _window(t_from: int, t_to: int, cfg: dict) -> dict:
    q_rt = (
        "SELECT provider, count() n, avg(runtime) avg_r, max(runtime) max_r, "
        f"quantile(0.95)(runtime) p95 FROM provider.provider_runtime_logs "
        f"WHERE timestamp>=toDateTime({t_from}) AND timestamp<=toDateTime({t_to}) "
        "AND area='price' GROUP BY provider HAVING n>=%d" % MIN_PROVIDER_N
    )
    q_err = (
        "SELECT provider, count() n, countIf(statusCode>=500) e FROM provider.provider_logs "
        f"WHERE timestamp>=toDateTime({t_from}) AND timestamp<=toDateTime({t_to}) "
        "AND area='price' GROUP BY provider HAVING n>=%d" % MIN_PROVIDER_N
    )
    q_vol = (
        "SELECT count() n, countIf(totalTime>10) slow, "
        "avg(totalTime) avg_t, quantile(0.99)(totalTime) p99 "
        "FROM provider.provider_logs "
        f"WHERE timestamp>=toDateTime({t_from}) AND timestamp<=toDateTime({t_to}) "
        "AND area='price'"
    )
    rt = {r["provider"]: r for r in _rows(_grafana_query(cfg, q_rt, t_from, t_to))}
    err = {r["provider"]: r for r in _rows(_grafana_query(cfg, q_err, t_from, t_to))}
    vol = _rows(_grafana_query(cfg, q_vol, t_from, t_to))
    vol = vol[0] if vol else {}
    return {"runtime": rt, "errors": err, "volume": vol}


def _detect(cur: dict, base: dict, cfg: dict) -> dict:
    factor = cfg.get("increase_factor", 3.0)
    res = {"runtime": [], "errors": [], "volume": {}}

    for provider, r in sorted(cur["runtime"].items(), key=lambda kv: -kv[1]["avg_r"]):
        b = base["runtime"].get(provider)
        if not b or b["avg_r"] <= 0:
            continue
        if r["avg_r"] >= cfg["runtime_abs_sec"] and r["avg_r"] >= b["avg_r"] * factor:
            res["runtime"].append({
                "provider": provider,
                "cur": round(float(r["avg_r"]), 1),
                "base": round(float(b["avg_r"]), 1),
                "p95": round(float(r.get("p95") or 0), 1),
                "ratio": round(float(r["avg_r"]) / float(b["avg_r"]), 1),
                "n": int(r["n"]),
            })

    for provider, r in sorted(cur["errors"].items(), key=lambda kv: -kv[1]["e"]):
        base_n = base["errors"].get(provider, {}).get("n", 0)
        base_e = base["errors"].get(provider, {}).get("e", 0)
        if not base_n or base_e / base_n <= 0:
            continue
        cur_pct = 100.0 * int(r["e"]) / int(r["n"])
        base_pct = 100.0 * int(base_e) / int(base_n)
        if cur_pct >= cfg["errors_abs_pct"] and cur_pct >= base_pct * factor:
            res["errors"].append({
                "provider": provider,
                "pct": round(cur_pct, 1),
                "base_pct": round(base_pct, 1),
                "n": int(r["n"]),
            })

    cv, bv = cur["volume"], base["volume"]
    if cv and bv and bv.get("n"):
        drop_ratio = float(cv["n"]) / float(bv["n"])
        if drop_ratio < (1.0 - cfg["volume_drop"]):
            res["volume"] = {
                "cur": int(cv["n"]),
                "base": int(bv["n"]),
                "ratio": round(drop_ratio, 2),
                "slow": int(cv.get("slow") or 0),
                "avg": round(float(cv.get("avg_t") or 0), 2),
                "p99": round(float(cv.get("p99") or 0), 2),
            }
    return res


def _timepoint(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M МСК")


def _grafana_link(t_from: int, t_to: int, panel: int) -> str:
    return (f"{GRAFANA}/d/{DASH_UID}/provider-logs?"
            f"orgId=1&from={t_from * 1000}&to={t_to * 1000}&viewPanel={panel}")


def _esc_osascript(text: str) -> str:
    return re.sub(r'([\\"])', r"\\\1", str(text))


def _send_macos(title: str, body: str) -> None:
    first_line = body.splitlines()[0][:90] if body else title
    script = (
        f'display notification "{_esc_osascript(body)}" '
        f'with title "{_esc_osascript(title)}" subtitle "{_esc_osascript(first_line)}" '
        'sound name "Basso"'
    )
    res = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True, text=True, timeout=15,
    )
    if res.returncode != 0:
        raise RuntimeError(f"osascript rc={res.returncode}: {res.stderr.strip()[:120]}")


def _send_b24(text: str) -> None:
    client = B24Client()
    client.call("im.message.add", {
        "DIALOG_ID": "chat123028",
        "MESSAGE": text,
    })


def _send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TG_ALERT_CHAT_ID2")
    if not chat_id:
        chat_id = os.environ.get("TG_ALERT_CHAT_ID")
    thread_id = None
    if not token or not chat_id:
        try:
            token = token or _keychain_get("opencode.tg-alert-token")
            chat_id = chat_id or _keychain_get("opencode.tg-alert-chat2")
            thread_id = _keychain_get("opencode.tg-alert-thread")
        except RuntimeError:
            pass
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TG_ALERT_CHAT_ID2 not set")
    payload = {"chat_id": chat_id, "text": text}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        f"https://149.154.167.220/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Host": "api.telegram.org"},
    )
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        resp.read()


def _write_fallback(text: str) -> None:
    Path.home().joinpath("Work/ts-b24/data/alerts.log").parent.mkdir(
        parents=True, exist_ok=True)
    with open(str(Path.home() / "Work/ts-b24/data/alerts.log"), "a",
              encoding="utf-8") as f:
        f.write(f"{_ts()} pricing-alert: {text}\n")


def _notify(text: str, title: str) -> None:
    errors = []
    for name, fn in (("macos", lambda: _send_macos(title, text)),
                     ("b24", lambda: _send_b24(text)),
                     ("telegram", lambda: _send_telegram(text))):
        try:
            fn()
            print(f"{_ts()} delivered via {name}")
        except Exception as e:
            errors.append(f"{name}: {str(e)[:120]}")
            print(f"{_ts()} channel {name} failed: {e}")
    if errors:
        _write_fallback(f"{text}\n(channels: {'; '.join(errors)})")


def _runs_phase2(cur_from: int, cur_to: int) -> tuple[list[str], float]:
    try:
        out = Path("/tmp") / f"pricing_degradation_{int(time.time())}.csv"
        subprocess.run(
            [sys.executable or "python3", str(PHASE2),
             "--cur-from", datetime.fromtimestamp(cur_from).strftime("%Y-%m-%d %H:%M:%S"),
             "--cur-to", datetime.fromtimestamp(cur_to).strftime("%Y-%m-%d %H:%M:%S"),
             "--out", str(out)],
            capture_output=True, text=True, timeout=600,
            cwd=str(REPO),
        )
        import csv as _csv
        if not out.exists():
            return [], 0.0
        lines = []
        with out.open(newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            timeouts = [r for r in reader if r["METRIC"] == "timeouts"]
            for r in sorted(timeouts, key=lambda r: -float(r["DELTA"]))[:MAX_SITES_IN_MSG]:
                lines.append(f"    {r['DATABASE']} ×{float(r['DELTA']):.0f} к норме "
                             f"({float(r['CURRENT']):.0f}/ч)")
            if timeouts:
                top_to = float(max(timeouts, key=lambda r: float(r["DELTA"]))["DELTA"])
            else:
                top_to = 0.0
    except Exception as e:
        lines = [f"    (MySQL-скан не отработал: {str(e)[:100]})"]
        top_to = 0.0
    return lines, top_to


def _build_message(det: dict, cfg: dict, t_from: int, t_to: int, top_timeouts: float = 0.0) -> str:
    lines = [f"\U000026a0\ufe0f Веб-проценка замедлилась · {_timepoint(t_from)}–{_timepoint(t_to)}"]
    summary = []
    if det["runtime"]:
        n = len(det["runtime"])
        worst = max(det["runtime"], key=lambda r: r["ratio"])
        summary.append(f"{n} поставщик(ов) медленнее нормы до ×{worst['ratio']:.0f} "
                       f"({worst['cur']} с вместо ~{worst['base']} с)")
    if det["errors"]:
        n = len(det["errors"])
        worst_e = max(det["errors"], key=lambda e: e["pct"])
        summary.append(f"у {n} поставщиков ошибки 500+ до {worst_e['pct']:.0f}% "
                       f"(норма {worst_e['base_pct']:.0f}%)")
    if det["volume"]:
        v = det["volume"]
        summary.append(f"объём запросов проценки упал до ×{v['ratio']} "
                       f"({v['cur']} за час вместо {v['base']})")
    if top_timeouts > 0:
        summary.append(f"на БД до {top_timeouts:.0f} таймаутов/ч")
    if summary:
        lines.append("")
        lines.append(": ".join(["Итог", "; ".join(summary)]))
    lines.append("")
    if det["runtime"]:
        lines.append("Медленные поставщики (норма — сутки назад):")
        for r in det["runtime"][:MAX_PROVIDERS_IN_MSG]:
            lines.append(f"  • {r['provider']}: {r['cur']} с (норма {r['base']} с, "
                         f"p95 {r['p95']} с, ×{r['ratio']})")
        lines.append("")
    if det["errors"]:
        lines.append("Ошибки от поставщиков (код 500+):")
        for e in det["errors"][:MAX_PROVIDERS_IN_MSG]:
            lines.append(f"  • {e['provider']}: {e['pct']}% ошибочных (норма {e['base_pct']}%)")
        lines.append("")
    if det["volume"]:
        v = det["volume"]
        lines.append(f"Запросов проценки резко меньше: {v['cur']} за час "
                     f"(норма {v['base']}, ×{v['ratio']}); среднее {v['avg']} с, "
                     f"p99 {v['p99']} с, тяжёлых >10с: {v['slow']}")
        lines.append("")
    lines.append(f"График времени: {_grafana_link(t_from, t_to, 25)}")
    lines.append(f"График ошибок:  {_grafana_link(t_from, t_to, 27)}")
    return "\n".join(lines)


def main() -> int:
    cfg = _load_config()
    window = int(cfg.get("window_seconds", WINDOW_SEC))
    now = int(time.time())
    cur_from = now - window
    cur_to = now
    base_from = cur_from - SHIFT_SEC
    base_to = cur_to - SHIFT_SEC

    print(f"{_ts()} окно {_timepoint(cur_from)}–{_timepoint(cur_to)} "
          f"(эталон {_timepoint(base_from)})")
    cur = _window(cur_from, cur_to, cfg)
    base = _window(base_from, base_to, cfg)
    det = _detect(cur, base, cfg)
    is_abnormal = bool(det["runtime"] or det["errors"] or det["volume"])

    state = _load_state()
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not is_abnormal:
        if state.get("active"):
            _notify(f"\U00002705 Веб-проценка восстановлена · {_ts()}", "pricing-alert")
        _save_state({"active": False, "active_since": "", "last_notify": "",
                     "alerted_hours": 0})
        print(f"{_ts()} норма")
        return 0

    if not state.get("active"):
        if det["runtime"] or det["errors"]:
            site_lines, top_to = _runs_phase2(cur_from, cur_to)
        else:
            site_lines, top_to = [], 0.0
        lines = _build_message(det, cfg, cur_from, cur_to, top_to)
        if site_lines:
            lines += "\n\nТаймауты проценки на БД (× к норме, таймауты/ч):\n"
            lines += "\n".join(site_lines)
        _notify(lines, "pricing-alert: проценка замедлилась")
        _save_state({"active": True, "active_since": now_s, "last_notify": now_s,
                     "alerted_hours": 0})
        print(f"{_ts()} ИНЦИДЕНТ: {len(det['runtime'])} runtime, "
              f"{len(det['errors'])} errors, volume={bool(det['volume'])}")
        return 0

    hours = int((datetime.now() - datetime.strptime(
        state["active_since"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600)
    escalate_every = float(cfg.get("escalate_every_hours", 1.0))
    last = datetime.strptime(state["last_notify"], "%Y-%m-%d %H:%M:%S")
    if hours >= 1 and (datetime.now() - last).total_seconds() >= escalate_every * 3600:
        body = (f"\U000026a0\ufe0f Веб-проценка замедлена уже {hours} ч "
                f"(с {state['active_since']})")
        body += f"\nГрафик: {_grafana_link(cur_from - SHIFT_SEC, cur_to, 25)}"
        _notify(body, "pricing-alert: инцидент продолжается")
        _save_state({**state, "last_notify": now_s, "alerted_hours": hours})
    print(f"{_ts()} продолжается (часов: {hours})")
    return 0


if __name__ == "__main__":
    sys.exit(main())