#!/usr/bin/env python3
"""JARVIS theme config. Put next to jarvis_ui.py (in ~/jarvis) and run:  python config_ui.py

1. It first previews all 17 themes one after another (press any key to stop the tour).
2. Then you choose:
     ← / →  (or A / D)   browse themes, live preview
     Enter               save this theme and quit
     C                   turn theme cycling on/off (jarvis_ui rotates themes by itself)
     ↑ / ↓  (or + / -)   cycling interval: 10s 20s 30s 1m 2m 5m 10m
     R                   cycle in random order instead of in order
     Q                   quit without saving
Saved to data/theme.txt and data/theme_cycle.json. A running jarvis_ui.py picks changes up within ~2 seconds.
"""
import os, sys, re, time, json, select, termios, tty
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
import jarvis_ui as J

ORDER = J.THEME_ORDER
PRESETS = [10, 20, 30, 60, 120, 300, 600]
STATES = ["standby", "listening", "thinking", "speaking"]
DESC = {"emerald": "dust cloud (the original)", "arc": "cyan pulsing rings", "solar": "amber sun with rays",
        "nebula": "violet spiral galaxy", "ghost": "silver orb", "plasma": "magenta plasma globe filaments",
        "eclipse": "blue eclipse, blazing corona", "pearl": "iridescent pink-teal pearl",
        "magma": "molten orb, glowing cracks", "crystal": "ice crystal six-point star",
        "prism": "rainbow soap-bubble sphere", "reactor": "green arc-reactor HUD",
        "radar": "lime radar sweep with blips", "atom": "coral atom, orbiting electrons",
        "hex": "copper honeycomb ripple", "warp": "orange hyperspace tunnel",
        "storm": "yellow plasma ball lightning"}
TOUR_SECS = 1.2

cfg = J.load_cycle()
cfg["every"] = min(PRESETS, key=lambda p: abs(p - cfg["every"]))
orig = J.TH_NAME
st = {"idx": ORDER.index(orig), "tour": True, "tour_i": 0, "tour_t": time.time(), "quit": False, "saved": False}
J.set_theme(ORDER[0], save=False)


def fmt(sec):
    return f"{sec}s" if sec < 60 else f"{sec // 60}m"


def end_tour():
    st["tour"] = False
    st["idx"] = ORDER.index(orig)
    J.set_theme(orig, save=False)


def tick():
    if st["tour"] and time.time() - st["tour_t"] > TOUR_SECS:
        st["tour_i"] += 1
        st["tour_t"] = time.time()
        if st["tour_i"] >= len(ORDER):
            end_tour()
        else:
            J.set_theme(ORDER[st["tour_i"]], save=False)


def move(d):
    st["idx"] = (st["idx"] + d) % len(ORDER)
    J.set_theme(ORDER[st["idx"]], save=False)


def save():
    name = ORDER[st["idx"]]
    J.set_theme(name, save=True)
    try:
        os.makedirs(os.path.dirname(J.CYCLE_FILE), exist_ok=True)
        with open(J.CYCLE_FILE, "w") as f:
            json.dump(cfg, f)
    except Exception:
        pass
    st["saved"] = True
    st["quit"] = True


def keys(data):
    for k in re.findall(r"\x1b\[[0-9;]*[A-Za-z~]|\x1bO[A-Z]|.", data, re.S):
        if st["tour"]:
            end_tour()                      # any key ends the tour and hands over control
            if k in ("q", "Q", "\x03"):
                st["quit"] = True
            continue
        if k in ("\x1b[C", "\x1bOC", "d", "D", "l"):
            move(1)
        elif k in ("\x1b[D", "\x1bOD", "a", "A", "h"):
            move(-1)
        elif k in ("\x1b[A", "\x1bOA", "+", "="):
            cfg["every"] = PRESETS[min(len(PRESETS) - 1, PRESETS.index(cfg["every"]) + 1)]
        elif k in ("\x1b[B", "\x1bOB", "-", "_"):
            cfg["every"] = PRESETS[max(0, PRESETS.index(cfg["every"]) - 1)]
        elif k in ("c", "C"):
            cfg["on"] = not cfg["on"]
        elif k in ("r", "R"):
            cfg["random"] = not cfg["random"]
        elif k in ("\r", "\n"):
            save()
        elif k in ("q", "Q", "\x03"):
            st["quit"] = True


def build():
    name = J.TH_NAME
    head = Panel(Text("THEME CONFIG", style=f"bold {J.ACC}", justify="center"), box=box.ROUNDED,
                 border_style=J.EDGE, padding=0)
    g = Table.grid(expand=True)
    for _ in range(4):
        g.add_column(ratio=1, justify="center")
    cells = []
    for n in ORDER:
        cells.append(Text(f" {n} ", style=f"bold {J.ON_ACC} on {J.ACC}" if n == name else "#aab0ac"))
    nrows = 0
    for i in range(0, len(cells), 4):
        row = cells[i:i + 4]
        g.add_row(*(row + [Text("")] * (4 - len(row))))
        nrows += 1
    names = Panel(g, box=box.ROUNDED, border_style="#26292b", style="on #141618", padding=0)
    if st["tour"]:
        lines = [Text(f"Previewing: {name}  ({st['tour_i'] + 1}/{len(ORDER)})", style=f"bold {J.ACC}"),
                 Text(DESC[name], style=J.REPLY), Text(""),
                 Text("Press any key to take control", style=J.DIM)]
    else:
        mode = (f"CYCLE every {fmt(cfg['every'])}, {'random' if cfg['random'] else 'in order'}"
                if cfg["on"] else "FIXED (no cycling)")
        lines = [Text(f"{name}: {DESC[name]}", style=f"bold {J.ACC}"),
                 Text(f"Mode: {mode}", style=J.REPLY),
                 Text("←/→ browse  Enter save  Q quit", style=J.DIM),
                 Text("C cycle on/off  ↑/↓ interval  R random", style=J.DIM)]
    t = Text()
    for i, ln in enumerate(lines):
        if i:
            t.append("\n")
        t.append_text(ln)
    info = Panel(t, box=box.ROUNDED, border_style=J.ACC, padding=(0, 1))
    ps = STATES[int(time.time() / 2.5) % len(STATES)]
    lay = Layout()
    lay.split_column(Layout(head, size=3),
                     Layout(J.Dyn(lambda w, h: J.core.render(w, h, ps)), ratio=1),
                     Layout(names, size=nrows + 2),
                     Layout(info, size=6))
    return lay


def main():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        J.cursor(False)
        with Live(get_renderable=build, console=J.CON, screen=True, refresh_per_second=20):
            last = 0.0
            while not st["quit"]:
                if time.time() - last > 0.2:
                    J.cursor(False)
                    last = time.time()
                tick()
                if select.select([fd], [], [], 0.05)[0]:
                    keys(os.read(fd, 64).decode("utf-8", "ignore"))
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        J.cursor(True)
    if st["saved"]:
        c = (f"cycling every {fmt(cfg['every'])} ({'random' if cfg['random'] else 'in order'})"
             if cfg["on"] else "no cycling")
        print(f"Saved: theme '{ORDER[st['idx']]}', {c}.")
        print("A running jarvis_ui.py applies it within ~2 seconds; otherwise just start it.")
    else:
        print("Nothing saved.")


if __name__ == "__main__":
    main()