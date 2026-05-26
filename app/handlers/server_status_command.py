"""Private server status command for allowed senders."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from app.config import Settings

_SERVER_STATUS_PATTERN = re.compile(r"^/(?:server|load)(?:@\S+)?\s*$", re.IGNORECASE)


def server_status_command_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return bool(_SERVER_STATUS_PATTERN.match(msg.strip()))


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _read_meminfo() -> dict[str, int]:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return {}
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.strip().split()
        if not parts:
            continue
        try:
            out[key] = int(parts[0]) * 1024
        except ValueError:
            continue
    return out


def _read_uptime() -> str:
    path = Path("/proc/uptime")
    if not path.is_file():
        return "unknown"
    try:
        seconds = int(float(path.read_text(encoding="utf-8").split()[0]))
    except (IndexError, ValueError):
        return "unknown"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def server_status_text() -> str:
    cpu_count = os.cpu_count() or 1
    try:
        load1, load5, load15 = os.getloadavg()
        load_line = f"{load1:.2f} / {load5:.2f} / {load15:.2f}"
        load_pct = f"{(load1 / cpu_count) * 100:.0f}% от {cpu_count} CPU"
    except (AttributeError, OSError):
        load_line = "unknown"
        load_pct = "unknown"

    mem = _read_meminfo()
    if mem:
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        used = max(total - available, 0)
        mem_pct = (used / total * 100) if total else 0
        mem_line = f"{_format_bytes(used)} / {_format_bytes(total)} ({mem_pct:.0f}%)"

        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = max(swap_total - swap_free, 0)
        swap_pct = (swap_used / swap_total * 100) if swap_total else 0
        swap_line = f"{_format_bytes(swap_used)} / {_format_bytes(swap_total)} ({swap_pct:.0f}%)"
    else:
        mem_line = "unknown"
        swap_line = "unknown"

    root_disk = shutil.disk_usage("/")
    root_used_pct = root_disk.used / root_disk.total * 100
    root_line = (
        f"{_format_bytes(root_disk.used)} / {_format_bytes(root_disk.total)} "
        f"({root_used_pct:.0f}%)"
    )

    return (
        "Сервер:\n"
        f"- uptime: {_read_uptime()}\n"
        f"- load avg 1/5/15m: {load_line}\n"
        f"- load vs CPU: {load_pct}\n"
        f"- RAM: {mem_line}\n"
        f"- swap: {swap_line}\n"
        f"- disk /: {root_line}"
    )


async def handle_server_status_command(event, *, settings: Settings) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return
    if not _SERVER_STATUS_PATTERN.match((event.message.message or "").strip()):
        return
    await event.reply(server_status_text())
