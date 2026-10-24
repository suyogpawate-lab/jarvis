import os
import re
import time
import subprocess


def _read_meminfo():
    values = {}

    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()

                if len(parts) >= 2:
                    values[parts[0].rstrip(":")] = int(parts[1]) * 1024

    except Exception:
        pass

    return values


def _memory():
    mem = _read_meminfo()

    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", mem.get("MemFree", 0))
    used = max(total - available, 0)

    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    swap_used = max(swap_total - swap_free, 0)

    return {
        "total": total,
        "used": used,
        "available": available,
        "percent": round(used / total * 100, 1) if total else 0.0,
        "swap_total": swap_total,
        "swap_used": swap_used,
        "swap_percent": (
            round(swap_used / swap_total * 100, 1)
            if swap_total else 0.0
        ),
    }


def _top():
    result = {
        "cpu_percent": 0.0,
        "tasks": 0,
        "running": 0,
        "sleeping": 0,
        "stopped": 0,
        "zombie": 0,
    }

    try:
        proc = subprocess.run(
            ["top", "-b", "-n", "1"],
            capture_output=True,
            text=True,
            timeout=3,
        )

        output = proc.stdout

        for line in output.splitlines():

            # Example:
            # Tasks: 37 total, 1 running, 35 sleeping, 0 stopped, 1 zombie
            if line.startswith("Tasks:"):
                match = re.search(
                    r"Tasks:\s*(\d+)\s+total,\s*"
                    r"(\d+)\s+running,\s*"
                    r"(\d+)\s+sleeping,\s*"
                    r"(\d+)\s+stopped,\s*"
                    r"(\d+)\s+zombie",
                    line,
                    re.IGNORECASE,
                )

                if match:
                    (
                        result["tasks"],
                        result["running"],
                        result["sleeping"],
                        result["stopped"],
                        result["zombie"],
                    ) = map(int, match.groups())

            # Example:
            # 800%cpu 0%user 0%nice 0%sys 800%idle ...
            if "%cpu" in line.lower():

                idle_match = re.search(
                    r"([\d.]+)%idle",
                    line,
                    re.IGNORECASE,
                )

                cpu_match = re.search(
                    r"([\d.]+)%cpu",
                    line,
                    re.IGNORECASE,
                )

                if idle_match:
                    idle = float(idle_match.group(1))

                    cores = os.cpu_count() or 1
                    total_capacity = cores * 100.0

                    usage = (
                        (total_capacity - idle)
                        / total_capacity
                    ) * 100.0

                    result["cpu_percent"] = round(
                        max(0.0, min(100.0, usage)),
                        1,
                    )

                elif cpu_match:
                    # Fallback if an Android top variant doesn't
                    # expose the idle field.
                    result["cpu_percent"] = round(
                        max(
                            0.0,
                            min(
                                100.0,
                                float(cpu_match.group(1))
                                / (os.cpu_count() or 1),
                            ),
                        ),
                        1,
                    )

    except Exception:
        pass

    return result


def _jarvis_uptime():
    """Return this process's actual elapsed time using Linux /proc metadata."""
    try:
        # /proc/self/stat field 22 is starttime in clock ticks since boot.
        with open("/proc/self/stat", "r", encoding="utf-8") as stream:
            stat = stream.read()
        fields = stat[stat.rfind(")") + 2:].split()
        start_ticks = int(fields[19])
        ticks_per_second = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime", "r", encoding="utf-8") as stream:
            system_uptime = float(stream.read().split()[0])
        seconds = max(0.0, system_uptime - start_ticks / ticks_per_second)
    except (OSError, ValueError, IndexError, TypeError, AttributeError):
        # Fallback is process-module uptime, never reset on each telemetry call.
        started = getattr(_jarvis_uptime, "_started", None)
        if started is None:
            started = time.monotonic()
            _jarvis_uptime._started = started
        seconds = max(0.0, time.monotonic() - started)
    return {"seconds": round(seconds, 1), "text": _format_uptime(seconds)}


def _format_uptime(seconds):
    seconds = int(seconds)

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)

    if days:
        return f"{days}d {hours}h {minutes}m"

    if hours:
        return f"{hours}h {minutes}m"

    if minutes:
        return f"{minutes}m"

    return f"{seconds}s"


def get_telemetry():
    top = _top()

    return {
        "timestamp": time.time(),

        "cpu": {
            "percent": top["cpu_percent"],
            "cores": os.cpu_count() or 1,
        },

        "memory": _memory(),

        "tasks": {
            "total": top["tasks"],
            "running": top["running"],
            "sleeping": top["sleeping"],
            "stopped": top["stopped"],
            "zombie": top["zombie"],
        },

        "uptime": _jarvis_uptime(),
    }
