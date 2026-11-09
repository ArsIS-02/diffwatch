#!/usr/bin/env python3
"""DiffWatch — ежедневные снапшоты состояния хоста, диффы уходят в Graylog.

Дешёвый аналог FIM: открытые порты, включённые systemd-юниты, crontab,
состав пакетов. Любое изменение относительно вчерашнего снапшота — событие
по GELF UDP. Только stdlib.

Переменные окружения:
  DW_STATE_DIR   каталог со снапшотами (по умолчанию ~/.local/share/diffwatch)
  DW_GELF_HOST   куда слать (по умолчанию 127.0.0.1)
  DW_GELF_PORT   порт GELF UDP (по умолчанию 12206)
  DW_SUDO_PASS   пароль sudo для чтения /var/spool/cron (необязательно)
"""
import gzip, json, os, socket, subprocess, sys, time
from pathlib import Path

STATE_DIR = Path(os.environ.get("DW_STATE_DIR", "~/.local/share/diffwatch")).expanduser()
GELF_HOST = os.environ.get("DW_GELF_HOST", "127.0.0.1")
GELF_PORT = int(os.environ.get("DW_GELF_PORT", "12206"))
HOST = socket.gethostname()


def run(cmd, sudo=False):
    if sudo and os.environ.get("DW_SUDO_PASS"):
        cmd = ["sudo", "-S", "-p", ""] + cmd
        inp = os.environ["DW_SUDO_PASS"] + "\n"
    else:
        inp = None
    try:
        r = subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=60)
        return r.stdout
    except Exception:
        return ""


def collect():
    """Снимок состояния: {kind: {item: meta}}."""
    snap = {"port": {}, "unit": {}, "cron": {}, "package": {}}

    # Открытые порты (TCP+UDP, LISTEN/UNCONN)
    for line in run(["ss", "-tulnH"]).splitlines():
        parts = line.split()
        if len(parts) >= 5:
            proto, local = parts[0], parts[4]
            snap["port"][f"{proto}:{local.rsplit(':', 1)[-1]}"] = local

    # Включённые systemd-юниты (system + user)
    for scope, cmd in (("system", ["systemctl", "list-unit-files", "--state=enabled",
                                   "--no-legend", "--no-pager"]),
                       ("user", ["systemctl", "--user", "list-unit-files",
                                 "--state=enabled", "--no-legend", "--no-pager"])):
        for line in run(cmd).splitlines():
            parts = line.split()
            if parts:
                snap["unit"][f"{scope}:{parts[0]}"] = parts[1] if len(parts) > 1 else ""

    # Crontab: системные файлы + пользовательские spool + crontab -l
    cron_files = ["/etc/crontab"]
    cron_files += [str(p) for p in Path("/etc/cron.d").glob("*")] if Path("/etc/cron.d").is_dir() else []
    spool = run(["ls", "/var/spool/cron"], sudo=True)
    cron_files += [f"/var/spool/cron/{n}" for n in spool.split()]
    for path in cron_files:
        sudo = path.startswith("/var/spool/cron")
        body = run(["cat", path], sudo=sudo)
        if body:
            snap["cron"][path] = hashlib_sha1(body)
    user_ct = run(["crontab", "-l"])
    if user_ct:
        snap["cron"]["crontab:redos"] = hashlib_sha1(user_ct)

    # Пакеты
    for line in run(["rpm", "-qa", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}\n"]).splitlines():
        if line.strip():
            snap["package"][line.strip()] = ""

    return snap


def hashlib_sha1(text):
    import hashlib
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def diff(old, new):
    """Список событий: (kind, event, item, extra)."""
    events = []
    for kind in new:
        o, n = old.get(kind, {}), new[kind]
        for item in sorted(set(n) - set(o)):
            events.append((kind, "added", item, n[item]))
        for item in sorted(set(o) - set(n)):
            events.append((kind, "removed", item, o[item]))
        for item in sorted(set(o) & set(n)):
            if o[item] != n[item]:
                events.append((kind, "changed", item, f"{o[item]} -> {n[item]}"))
    return events


def send_gelf(fields):
    msg = {"version": "1.1", "host": HOST, "short_message": fields.pop("short"),
           "timestamp": time.time(), "level": fields.pop("level", 5)}
    msg.update({f"_{k}": v for k, v in fields.items()})
    data = gzip.compress(json.dumps(msg).encode())
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(data, (GELF_HOST, GELF_PORT))
    sock.close()


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    snap = collect()
    snap_path = STATE_DIR / f"{today}.json"
    prev = sorted(STATE_DIR.glob("*.json"))
    old = json.loads(prev[-1].read_text()) if prev else {}

    events = diff(old, snap) if old else []
    for kind, event, item, extra in events:
        level = 3 if (kind == "port" and event == "added") or kind in ("unit", "cron") else 4
        send_gelf({
            "short": f"diffwatch: {kind} {event}: {item}",
            "level": level, "tool": "diffwatch", "homelab_app": "diffwatch",
            "dw_event": event, "dw_kind": kind, "dw_item": item, "dw_detail": extra[:200],
        })

    # Пульс: снапшот снят, сколько чего под надзором
    send_gelf({
        "short": f"diffwatch: снапшот {today}: " +
                 ", ".join(f"{k}={len(v)}" for k, v in snap.items()),
        "level": 6, "tool": "diffwatch", "homelab_app": "diffwatch",
        "dw_event": "snapshot", "dw_kind": "all",
        "dw_ports": len(snap["port"]), "dw_units": len(snap["unit"]),
        "dw_crons": len(snap["cron"]), "dw_packages": len(snap["package"]),
    })

    snap_path.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"{today}: {len(events)} изменений, снапшот {snap_path.name}")


if __name__ == "__main__":
    main()
