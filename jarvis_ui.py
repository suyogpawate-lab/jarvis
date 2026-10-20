#!/usr/bin/env python3
"""JARVIS terminal UI for Termux: dust-cloud presence + prompt box. No localhost.
Setup : pip install rich   (put jarvis_ui.py next to jarvis.py in ~/jarvis)
Run   : python jarvis_ui.py        (the plain CLI is still: python jarvis.py)
Typing = LISTENING, JARVIS working = THINKING, reply/TTS = SPEAKING, error = ALERT.
Preview a mode: /listening /thinking /speaking /alert /standby   |   /q or Ctrl-C quits.
Themes: /theme cycles, or /theme emerald|arc|solar|nebula|ghost|plasma|eclipse|pearl|magma|crystal|prism|reactor|radar|atom|hex|warp|storm (saved to data/theme.txt,
        or set JARVIS_THEME=emerald (or another listed theme) before running).
Keys  : ←/→ move the cursor (Ctrl/Alt+←/→ by word)  Home/End or Ctrl-A/E jump  Del deletes forward
        ↑/↓ recall earlier prompts (Ctrl-P / Ctrl-N always do);  while a long reply is showing,
        ↑/↓ scroll it instead (Ctrl+↑/↓ always scroll).  PgUp/PgDn scroll a page.
Printed output from jarvis.py's modules goes to ~/jarvis/data/ui.log so it can't corrupt the screen.
"""
import os, sys, time, json, math, random, threading, select, textwrap, shutil, subprocess
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.style import Style
from rich.color import Color
from rich.table import Table
from rich import box

FPS = 45  # target; real rate depends on the device CPU
HOME = os.path.dirname(os.path.abspath(__file__))  # the project folder (~/jarvis)
EV_FILE = os.path.join(HOME, "ui_events.jsonl")
STATES = ["standby", "listening", "thinking", "speaking", "alert"]


# ───────────────────────── connect to Jarvis ─────────────────────────
BRAIN = None      # the imported jarvis.py module (set in main)
BRAIN_ERR = ""


def set_state(state, log=None):
    """Optional: call from your own code (even from another process) to drive the presence."""
    try:
        os.makedirs(HOME, exist_ok=True)
        with open(EV_FILE, "a") as f:
            f.write(json.dumps({"state": state, "t": time.time()}) + "\n")
    except Exception:
        pass


# ───────────────────────── state ─────────────────────────
S = {"state": "standby", "buf": "", "reply": "", "reply_t": 0.0, "busy": False, "quit": False, "scroll": 0,
     "alert_until": 0.0, "alert_since": 0.0, "ext_speaking": False,
     "cur": 0, "hist": [], "hi": None, "draft": ""}
_ev_pos = 0
_fps = {"t": time.time(), "v": 0.0}


def set_local(state):
    S["state"] = state


def pump_events():
    global _ev_pos
    try:
        with open(EV_FILE) as f:
            f.seek(_ev_pos)
            data = f.read()
            _ev_pos = f.tell()
    except FileNotFoundError:
        return
    for line in data.splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("state") in STATES:
            set_local(e["state"])


# ───────────────────────── speech activity ─────────────────────────
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import voice.tts as _tts_mod
except Exception:
    _tts_mod = None

_PGREP = shutil.which("pgrep")
_mpv_cache = [0.0, False]


def _mpv_running():
    """Best-effort: is an mpv player process alive? (tts.py plays through mpv)"""
    if not _PGREP:
        return False
    now = time.time()
    if now - _mpv_cache[0] < 0.2:
        return _mpv_cache[1]
    try:
        r = subprocess.run([_PGREP, "-x", "mpv"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=1)
        _mpv_cache[1] = r.returncode == 0
    except Exception:
        _mpv_cache[1] = False
    _mpv_cache[0] = now
    return _mpv_cache[1]


def _manager_busy():
    """Ask tts_manager if it exposes a busy flag (name varies, so probe a few)."""
    try:
        import voice.tts_manager as tts_manager
        obj = getattr(tts_manager, "tts", None)
        for name in ("is_speaking", "speaking", "is_busy", "busy"):
            v = getattr(obj, name, None)
            if v is None:
                continue
            v = v() if callable(v) else v
            if isinstance(v, bool):
                return v
    except Exception:
        pass
    return False


def speech_active():
    try:
        if _tts_mod is not None and _tts_mod.is_speaking():
            return True
    except Exception:
        pass
    return _manager_busy() or _mpv_running()


def wait_for_speech(answer, t0, blocked_for):
    """Keep 'speaking' up until the audio has really finished."""
    est = len(answer) / 14.0                    # rough spoken duration at the configured rate
    if blocked_for >= est * 0.5:                # speak() itself blocked through playback
        return
    seen = False
    quiet_since = None
    start_deadline = time.time() + 12           # allow time for synthesis before audio starts
    hard = time.time() + max(est * 2, 30)
    while time.time() < hard and not S["quit"]:
        now = time.time()
        if speech_active():
            seen, quiet_since = True, None
        elif seen:
            quiet_since = quiet_since or now
            if now - quiet_since > 0.8:         # debounce gaps between queued chunks
                return
        elif now > start_deadline:
            break
        time.sleep(0.15)
    if not seen:                                # nothing detectable: fall back to an estimate
        left = len(answer) / 17 - (time.time() - t0)
        if left > 0:
            time.sleep(min(left, 20))


def speech_watch():
    """Show 'speaking' for speech Jarvis starts on its own (scheduled reminders etc.)."""
    while not S["quit"]:
        time.sleep(0.4)
        if S["busy"] or S["state"] == "alert":
            continue
        act = speech_active()
        if act:
            S["ext_speaking"] = True
            if S["state"] != "speaking":
                set_local("speaking")
        elif S["ext_speaking"]:
            S["ext_speaking"] = False
            settle()


# ───────────────────────── alert ─────────────────────────
# ALERT is for things that need your attention: errors/warnings, TTS failures and
# incoming notifications. It holds long enough to notice and clears when you start
# typing (after a short grace period) or when its hold time runs out.
def raise_alert(hold):
    S["alert_since"] = time.time()
    S["alert_until"] = time.time() + hold
    set_local("alert")


def settle():
    set_local("listening" if S["buf"] else "standby")


def work(text):
    set_local("thinking")
    try:
        if BRAIN is None:
            raise RuntimeError(BRAIN_ERR or "jarvis.py not loaded")
        answer, speak_it = BRAIN.handle_prompt(text)
        answer = str(answer or "").strip()
        S["reply"], S["reply_t"] = answer, time.time()
        if answer.startswith("[") and ("ERROR" in answer[:24] or "WARN" in answer[:24]):
            S["busy"] = False
            raise_alert(8)
            return
        if answer and speak_it:
            set_local("speaking")
            t0 = time.time()
            ok = BRAIN.speak(answer, quiet=True)
            if ok is False:
                S["reply"] = answer + "\n[TTS failed - see data/ui.log]"
                S["busy"] = False
                raise_alert(6)
                return
            wait_for_speech(answer, t0, time.time() - t0)
        elif answer:
            set_local("speaking")
            time.sleep(min(6, max(1.5, len(answer) / 30)))
    except Exception as e:
        S["reply"], S["reply_t"] = f"Error: {e}", time.time()
        S["busy"] = False
        raise_alert(8)
        return
    S["busy"] = False
    settle()


def notify(text):
    text = str(text)
    S["reply"], S["reply_t"] = "[NOTIFICATIONS] " + text, time.time()
    raise_alert(min(15, 6 + len(text) / 25))


def submit():
    text = S["buf"].strip()
    if not text:
        return
    cmd = text[1:].lower() if text.startswith("/") else text.lower()
    if cmd in ("q", "quit", "exit"):
        _clear_buf()
        S["quit"] = True
        return
    if text.startswith("/") and (cmd == "theme" or cmd.startswith("theme ")):
        _remember(text)
        _clear_buf()
        cycle_theme(cmd[5:].strip())
        return
    if text.startswith("/") and cmd in STATES:  # mode preview; other /commands go to Jarvis
        _remember(text)
        _clear_buf()
        set_local(cmd)
        return
    if S["busy"]:
        return
    S["busy"] = True
    _remember(text)
    _clear_buf()
    S["reply"] = ""
    threading.Thread(target=work, args=(text,), daemon=True).start()


_esc = [0]
_seq = [""]


def _clear_buf():
    S["buf"], S["cur"], S["hi"], S["draft"] = "", 0, None, ""


def _remember(text):
    h = S["hist"]
    if text and (not h or h[-1] != text):
        h.append(text)
        del h[:-100]


def _after_edit():
    """Keep the presence state in step with whether there is text in the prompt."""
    if S["state"] == "alert" and S["alert_until"] and time.time() - S["alert_since"] < 1.5:
        return  # don't let a stray keystroke swallow a fresh alert
    if not S["busy"]:
        if S["buf"]:
            set_local("listening")
        elif S["state"] == "listening":
            set_local("standby")


def _typed():
    """The user edited the text themselves: leave history browsing."""
    S["hi"] = None
    _after_edit()


def _word_left(buf, i):
    while i > 0 and buf[i - 1] == " ":
        i -= 1
    while i > 0 and buf[i - 1] != " ":
        i -= 1
    return i


def _word_right(buf, i):
    n = len(buf)
    while i < n and buf[i] == " ":
        i += 1
    while i < n and buf[i] != " ":
        i += 1
    return i


def hist_prev():
    h = S["hist"]
    if not h:
        return
    if S["hi"] is None:
        S["draft"] = S["buf"]
        S["hi"] = len(h) - 1
    else:
        S["hi"] = max(0, S["hi"] - 1)
    S["buf"] = h[S["hi"]]
    S["cur"] = len(S["buf"])
    _after_edit()


def hist_next():
    h = S["hist"]
    if S["hi"] is None:
        return
    if S["hi"] < len(h) - 1:
        S["hi"] += 1
        S["buf"] = h[S["hi"]]
    else:
        S["hi"] = None
        S["buf"] = S["draft"]
    S["cur"] = len(S["buf"])
    _after_edit()


def scroll_by(n):
    S["scroll"] = max(0, S["scroll"] + n)


def handle_seq(seq):
    """CSI/SS3 sequences: arrows, Home/End, Del, PgUp/PgDn (+ Ctrl/Alt/Shift variants like 1;5C)."""
    mod = 0
    if seq.endswith("~"):
        key = seq[:-1].split(";")[0] + "~"
        if ";" in seq:
            mod = int(seq[:-1].split(";")[-1]) if seq[:-1].split(";")[-1].isdigit() else 0
    else:
        key = seq[-1:]
        if ";" in seq:
            m = seq[:-1].split(";")[-1]
            mod = int(m) if m.isdigit() else 0
    word = mod in (3, 5)          # Alt or Ctrl held
    page = max(1, S.get("rh", 4) - 1)
    buf, cur = S["buf"], S["cur"]

    if key == "A":
        if mod == 5 or (S.get("sc") and S["hi"] is None):
            scroll_by(1)          # long reply on screen: arrows scroll it
        else:
            hist_prev()
    elif key == "B":
        if mod == 5 or (S.get("sc") and S["hi"] is None):
            scroll_by(-1)
        else:
            hist_next()
    elif key == "C":
        S["cur"] = _word_right(buf, cur) if word else min(len(buf), cur + 1)
    elif key == "D":
        S["cur"] = _word_left(buf, cur) if word else max(0, cur - 1)
    elif key in ("H", "1~", "7~"):
        S["cur"] = 0
    elif key in ("F", "4~", "8~"):
        S["cur"] = len(buf)
    elif key == "3~":             # Delete
        if cur < len(buf):
            S["buf"] = buf[:cur] + buf[cur + 1:]
            _typed()
    elif key == "5~":
        scroll_by(page)
    elif key == "6~":
        scroll_by(-page)


def handle_key(ch):
    if _esc[0] == 1:
        if ch in "[O":
            _esc[0] = 2
            _seq[0] = ""
            return
        _esc[0] = 0  # lone ESC: handle this key normally
    elif _esc[0] == 2:
        _seq[0] += ch
        if ch.isalpha() or ch == "~":
            _esc[0] = 0
            handle_seq(_seq[0])
        return
    if ch == "\x1b":
        _esc[0] = 1
        return
    if ch in ("\r", "\n"):
        submit()
        return
    if ch == "\x03":
        S["quit"] = True
        return
    if ch == "\x04":
        if not S["buf"]:
            S["quit"] = True
        return
    buf, cur = S["buf"], S["cur"]
    if ch in ("\x7f", "\x08"):                 # Backspace
        if cur > 0:
            S["buf"], S["cur"] = buf[:cur - 1] + buf[cur:], cur - 1
    elif ch == "\x15":                         # Ctrl-U: clear line
        S["buf"], S["cur"] = "", 0
    elif ch == "\x0b":                         # Ctrl-K: kill to end
        S["buf"] = buf[:cur]
    elif ch == "\x17":                         # Ctrl-W: delete previous word
        j = _word_left(buf, cur)
        S["buf"], S["cur"] = buf[:j] + buf[cur:], j
    elif ch == "\x01":                         # Ctrl-A
        S["cur"] = 0
        return
    elif ch == "\x05":                         # Ctrl-E
        S["cur"] = len(buf)
        return
    elif ch == "\x02":                         # Ctrl-B
        S["cur"] = max(0, cur - 1)
        return
    elif ch == "\x06":                         # Ctrl-F
        S["cur"] = min(len(buf), cur + 1)
        return
    elif ch == "\x10":                         # Ctrl-P
        hist_prev()
        return
    elif ch == "\x0e":                         # Ctrl-N
        hist_next()
        return
    elif ch >= " " and len(buf) < 2000:
        S["buf"], S["cur"] = buf[:cur] + ch + buf[cur:], cur + 1
    else:
        return
    _typed()


# ───────────────────────── themes ─────────────────────────
import colorsys

# cloud themes: tint = per state (dim speck rgb, bright speck rgb, haze rgb); alt = second hue that
#   the specks blend toward at the cloud's edge (this is what stops each theme being one flat colour)
# canvas themes: pal = (base rgb, bright rgb, thinking-accent rgb); colour flows base -> bright by position
_ALERT = ((104, 40, 40), (255, 222, 212), (52, 12, 12))
def _mix(a, b, m):
    return [a[i] + (b[i] - a[i]) * m for i in range(3)]


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(x))) for x in c)


def _canvas_theme(shape, pal):
    """Derive the UI colours of a canvas theme from its palette (base, bright, thinking-accent)."""
    c1, c2, c3 = pal
    acc = _mix(c1, c2, .75)
    return {"shape": shape, "acc": _hex(acc), "on": _hex([x * .06 for x in c1]),
            "reply": _hex(_mix(c2, (215, 215, 215), .6)), "edge": _hex([x * .38 for x in c1]),
            "dim": _hex(_mix(c1, (120, 120, 120), .55)),
            "grad": (_mix(c2, (255, 255, 255), .5), acc), "pal": pal}


THEMES = {
    "emerald": {  # the original look
        "shape": "cloud", "acc": "#7fc79a", "on": "#0d1510", "reply": "#b7d4c0", "edge": "#2e3a33",
        "dim": "#555b57", "grad": ((183, 220, 160), (122, 199, 154)), "alt": (110, 190, 235),
        "tint": {"standby": ((44, 62, 56), (190, 208, 200), (14, 28, 24)),
                 "listening": ((50, 84, 84), (222, 246, 246), (14, 38, 42)),
                 "thinking": ((72, 62, 98), (236, 226, 252), (30, 22, 48)),
                 "speaking": ((58, 82, 66), (232, 241, 235), (20, 42, 28)),
                 "alert": _ALERT}},
    "arc": {  # cyan rings
        "shape": "rings", "acc": "#3fd8ff", "on": "#04141a", "reply": "#b9e8f5", "edge": "#1e3a44",
        "dim": "#4f5f66", "grad": ((190, 240, 255), (63, 216, 255)), "alt": (130, 150, 255),
        "tint": {"standby": ((30, 60, 72), (170, 225, 240), (8, 26, 32)),
                 "listening": ((40, 96, 120), (200, 244, 255), (10, 40, 52)),
                 "thinking": ((60, 80, 130), (214, 226, 255), (18, 28, 60)),
                 "speaking": ((40, 110, 126), (220, 250, 255), (10, 48, 56)),
                 "alert": _ALERT}},
    "solar": {  # amber sun with rays
        "shape": "sun", "acc": "#ffb02e", "on": "#1a1004", "reply": "#f0d9b0", "edge": "#40300f",
        "dim": "#665c4a", "grad": ((255, 225, 160), (255, 176, 46)), "alt": (255, 90, 40),
        "tint": {"standby": ((70, 50, 22), (230, 200, 150), (30, 20, 6)),
                 "listening": ((120, 84, 30), (255, 236, 190), (48, 32, 8)),
                 "thinking": ((130, 70, 40), (255, 214, 180), (52, 24, 10)),
                 "speaking": ((140, 100, 30), (255, 244, 200), (56, 40, 8)),
                 "alert": ((110, 30, 30), (255, 214, 200), (56, 10, 10))}},
    "nebula": {  # violet spiral galaxy
        "shape": "spiral", "acc": "#c58bff", "on": "#150a20", "reply": "#dcc8f2", "edge": "#34234a",
        "dim": "#5e5370", "grad": ((230, 205, 255), (197, 139, 255)), "alt": (255, 110, 190),
        "tint": {"standby": ((52, 38, 78), (210, 190, 240), (22, 14, 36)),
                 "listening": ((84, 60, 130), (236, 222, 255), (34, 22, 56)),
                 "thinking": ((60, 80, 140), (214, 226, 255), (16, 24, 56)),
                 "speaking": ((100, 66, 150), (244, 232, 255), (40, 24, 64)),
                 "alert": ((110, 36, 56), (255, 214, 222), (56, 10, 24))}},
    "ghost": {  # silver orb
        "shape": "orb", "acc": "#e6e8ea", "on": "#0c0d0e", "reply": "#cfd3d6", "edge": "#34383b",
        "dim": "#5f6468", "grad": ((255, 255, 255), (170, 176, 180)), "alt": (140, 165, 255),
        "tint": {"standby": ((50, 54, 58), (200, 205, 208), (20, 22, 24)),
                 "listening": ((80, 86, 92), (232, 236, 238), (30, 33, 36)),
                 "thinking": ((70, 76, 96), (220, 224, 240), (26, 28, 42)),
                 "speaking": ((100, 106, 112), (246, 248, 250), (40, 43, 46)),
                 "alert": _ALERT}},
    "reactor": {  # green arc-reactor HUD (concentric rings, spinning arc segments)
        "shape": "reactor", "acc": "#2fe39a", "on": "#03140c", "reply": "#bdeedc", "edge": "#164a35",
        "dim": "#4d6a5e", "grad": ((190, 255, 220), (47, 227, 154)),
        "pal": ((16, 100, 72), (120, 255, 200), (110, 200, 255))},
}
NEW_THEMES = [  # canvas themes: (name, shape, (base rgb, bright rgb, thinking-accent rgb))
    ("radar", "radar", ((70, 150, 20), (200, 255, 90), (120, 220, 255))),
    ("atom", "atom", ((200, 60, 70), (255, 215, 190), (255, 205, 100))),
    ("hex", "hex", ((150, 70, 25), (255, 195, 125), (255, 235, 120))),
    ("warp", "warp", ((225, 70, 25), (255, 235, 180), (120, 180, 255))),
    ("storm", "storm", ((200, 170, 30), (255, 255, 225), (130, 170, 255))),
]
for _n, _s, _p in NEW_THEMES:
    THEMES[_n] = _canvas_theme(_s, _p)
# new dust orbs (same engine as emerald/arc/solar/nebula/ghost, each with its own shape + palette)
THEMES.update({
    "plasma": {  # magenta plasma globe: glowing filaments reaching out from a hot core
        "shape": "plasma", "acc": "#ff5fd0", "on": "#1a0516", "reply": "#f2c6e6", "edge": "#4a1840",
        "dim": "#6a4a64", "grad": ((255, 190, 235), (255, 95, 208)), "alt": (120, 150, 255),
        "tint": {"standby": ((90, 30, 80), (255, 170, 230), (40, 10, 36)),
                 "listening": ((140, 40, 120), (255, 200, 245), (54, 14, 48)),
                 "thinking": ((60, 50, 150), (210, 200, 255), (22, 18, 60)),
                 "speaking": ((190, 50, 150), (255, 225, 250), (70, 16, 56)),
                 "alert": _ALERT}},
    "eclipse": {  # royal-blue eclipse: dark core, blazing corona ring and flares
        "shape": "eclipse", "acc": "#6a9bff", "on": "#050a1c", "reply": "#c4d4f5", "edge": "#1c2c5a",
        "dim": "#4a5878", "grad": ((200, 220, 255), (106, 155, 255)), "alt": (255, 232, 175),
        "tint": {"standby": ((30, 50, 100), (190, 210, 255), (8, 14, 34)),
                 "listening": ((50, 80, 170), (215, 230, 255), (10, 20, 56)),
                 "thinking": ((80, 60, 170), (220, 210, 255), (22, 16, 60)),
                 "speaking": ((70, 110, 220), (235, 245, 255), (14, 26, 70)),
                 "alert": _ALERT}},
    "pearl": {  # iridescent pearl: soft swirling bands that shift from pink to teal
        "shape": "pearl", "acc": "#f0b6dc", "on": "#1a0e16", "reply": "#f0dde8", "edge": "#46344a",
        "dim": "#706070", "grad": ((255, 225, 240), (240, 182, 220)), "alt": (100, 230, 215),
        "tint": {"standby": ((80, 70, 90), (235, 220, 235), (26, 22, 30)),
                 "listening": ((110, 90, 120), (250, 235, 245), (34, 28, 40)),
                 "thinking": ((70, 100, 130), (215, 235, 255), (20, 28, 44)),
                 "speaking": ((130, 100, 120), (255, 240, 235), (42, 30, 36)),
                 "alert": _ALERT}},
    "magma": {  # molten orb: glowing cells split by dark cracks, white-hot core, crimson rim
        "shape": "magma", "acc": "#ff7a2e", "on": "#1c0802", "reply": "#f5cdb0", "edge": "#4a2010",
        "dim": "#70503f", "grad": ((255, 205, 140), (255, 122, 46)), "alt": (210, 45, 35),
        "tint": {"standby": ((90, 30, 15), (255, 150, 70), (32, 10, 4)),
                 "listening": ((130, 45, 18), (255, 185, 90), (46, 14, 6)),
                 "thinking": ((110, 35, 60), (255, 170, 150), (40, 12, 22)),
                 "speaking": ((170, 70, 20), (255, 225, 140), (60, 24, 6)),
                 "alert": _ALERT}},
    "crystal": {  # ice crystal: six-pointed star with spokes and an inner hexagon ring
        "shape": "crystal", "acc": "#9ad0ff", "on": "#06101c", "reply": "#d0e2f2", "edge": "#26405c",
        "dim": "#566878", "grad": ((235, 245, 255), (154, 208, 255)), "alt": (190, 150, 255),
        "tint": {"standby": ((50, 70, 100), (200, 225, 250), (14, 22, 34)),
                 "listening": ((70, 110, 160), (225, 242, 255), (18, 32, 52)),
                 "thinking": ((90, 80, 170), (225, 215, 255), (26, 22, 60)),
                 "speaking": ((90, 140, 200), (240, 250, 255), (22, 40, 64)),
                 "alert": _ALERT}},
    "prism": {  # soap-bubble prism: the whole rainbow flows around a glassy sphere
        "shape": "prism", "rainbow": True, "acc": "#c9b6ff", "on": "#0c0818", "reply": "#e2dcf5", "edge": "#3a3060",
        "dim": "#6a6480", "grad": ((255, 190, 220), (150, 200, 255)), "alt": (150, 200, 255),
        "tint": {"standby": ((50, 50, 60), (220, 225, 235), (14, 14, 20)),
                 "listening": ((70, 70, 85), (240, 242, 250), (18, 18, 26)),
                 "thinking": ((60, 60, 90), (235, 235, 255), (16, 16, 34)),
                 "speaking": ((80, 80, 95), (250, 250, 255), (22, 22, 30)),
                 "alert": _ALERT}},
})
THEME_ORDER = ["emerald", "arc", "solar", "nebula", "ghost", "plasma", "eclipse", "pearl", "magma", "crystal",
               "prism", "reactor"] + [n[0] for n in NEW_THEMES]
THEME_FILE = os.path.join(HOME, "data", "theme.txt")
TH_NAME = "emerald"
ACC = ON_ACC = REPLY = EDGE = DIM = ""
GRAD = ((183, 220, 160), (122, 199, 154))
SHAPE = "cloud"
RAINBOW = False
TINT = {}
ALT = (110, 190, 235)
PAL = ((16, 100, 72), (120, 255, 200), (110, 200, 255))
_STY = {}


def set_theme(name, save=True):
    """Switch palette + shape live. Unknown names are ignored. Returns True if applied."""
    global TH_NAME, ACC, ON_ACC, REPLY, EDGE, DIM, GRAD, SHAPE, TINT, ALT, PAL, RAINBOW
    name = (name or "").strip().lower()
    if name not in THEMES:
        return False
    t = THEMES[name]
    TH_NAME, ACC, ON_ACC, REPLY, EDGE, DIM = name, t["acc"], t["on"], t["reply"], t["edge"], t["dim"]
    GRAD, SHAPE = t["grad"], t["shape"]
    TINT = t.get("tint") or THEMES["emerald"]["tint"]
    ALT = t.get("alt", ALT)
    RAINBOW = bool(t.get("rainbow"))
    PAL = t.get("pal", PAL)
    _STY.clear()
    if save:
        try:
            os.makedirs(os.path.dirname(THEME_FILE), exist_ok=True)
            with open(THEME_FILE, "w") as f:
                f.write(name)
        except Exception:
            pass
    return True


def cycle_theme(arg=""):
    if arg and set_theme(arg):
        return
    set_theme(THEME_ORDER[(THEME_ORDER.index(TH_NAME) + 1) % len(THEME_ORDER)])


def load_theme():
    name = os.environ.get("JARVIS_THEME", "")
    if not name:
        try:
            name = open(THEME_FILE).read()
        except Exception:
            name = ""
    set_theme(name if name.strip().lower() in THEMES else "emerald", save=False)


load_theme()

TSPEED = {"standby": .35, "listening": .8, "thinking": 1.8, "speaking": 1.4, "alert": 2.6}
BIT = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
BR = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))   # braille bit for (dot column, dot row)


def _sty(state, bi, hi, ci=0):
    """Style for the dust-cloud themes. ci (0-5) = distance from centre: blends toward the theme's alt hue."""
    k = (state, bi, hi, ci)
    s = _STY.get(k)
    if s is None:
        dim, br, hz = TINT[state]
        f, hf = bi / 9, hi / 5
        fg = _mix(dim, br, f)
        if RAINBOW and state != "alert":      # prism: ci (0-11) is the hue around the colour wheel
            col = colorsys.hsv_to_rgb(min(11, ci) / 12, .62, 1.0)
            fg = [col[i] * 255 * (.22 + .78 * f) + 255 * f ** 3 * .2 for i in range(3)]
        elif state != "alert" and ci:
            fg = _mix(fg, [ALT[i] * (.35 + .65 * f) for i in range(3)], .6 * ci / 5)
        bg = [int(hz[i] * hf) for i in range(3)]
        s = Style(color=Color.from_rgb(*[max(0, min(255, int(c))) for c in fg]), bgcolor=Color.from_rgb(*bg))
        _STY[k] = s
    return s


def _pal(state):
    c1, c2, c3 = PAL
    if state == "alert":
        return (170, 48, 48), (255, 170, 150)
    if state == "thinking":
        return c3, c2
    if state == "speaking":
        return _mix(c1, c2, .5), _mix(c2, (255, 255, 255), .3)
    if state == "listening":
        return _mix(c1, c2, .35), c2
    return c1, _mix(c1, c2, .6)


def _csty(state, vi, hi):
    """Style for the canvas themes: vi = brightness 0-11, hi = position colour 0-5 (base -> bright)."""
    k = ("c", state, vi, hi)
    s = _STY.get(k)
    if s is None:
        a, b = _pal(state)
        base = _mix(a, b, hi / 5)
        v = vi / 11
        f = .2 + .8 * v
        fg = [min(255, int(base[i] * f + 255 * v ** 4 * .3)) for i in range(3)]
        bg = [int(base[i] * .07 * v) for i in range(3)]
        s = Style(color=Color.from_rgb(*fg), bgcolor=Color.from_rgb(*bg))
        _STY[k] = s
    return s


# ───────────────────────── braille canvas ─────────────────────────
class Canvas:
    """Draw with dots (2 across x 4 down per terminal cell). Each dot carries brightness v and colour hue (0-1)."""
    def __init__(self, w, h):
        self.w, self.h, self.DW, self.DH = w, h, w * 2, h * 4
        n = w * h
        self.bits, self.val, self.hue = [0] * n, [0.0] * n, [0.0] * n
        self.n = 0

    def dot(self, x, y, v=1.0, hue=0.0):
        x, y = int(x), int(y)
        if 0 <= x < self.DW and 0 <= y < self.DH:
            c = (y >> 2) * self.w + (x >> 1)
            self.bits[c] |= BR[x & 1][y & 3]
            self.n += 1
            if v >= self.val[c]:
                self.val[c], self.hue[c] = v, hue

    def line(self, x0, y0, x1, y1, v=1.0, hue=0.0):
        n = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
        for i in range(n + 1):
            f = i / n
            self.dot(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, v, hue)

    def arc(self, cx, cy, r, a0, a1, v=1.0, hue=0.0):
        n = max(8, int(abs(a1 - a0) * r / .8))
        c, s = math.cos, math.sin
        for i in range(n + 1):
            a = a0 + (a1 - a0) * i / n
            self.dot(cx + r * c(a), cy + r * s(a), v, hue)

    def text(self, state):
        out = Text(no_wrap=True)
        w, bits, val, hue = self.w, self.bits, self.val, self.hue
        for y in range(self.h):
            for x in range(w):
                c = y * w + x
                b = bits[c]
                if b:
                    out.append(chr(0x2800 + b), style=_csty(state, int(min(1.0, val[c]) * 11),
                                                           int(min(1.0, max(0.0, hue[c])) * 5)))
                else:
                    out.append(" ")
            out.append("\n")
        return out


PI2 = 2 * math.pi


# ── reactor: concentric rings, tick marks, spinning arc segments, glowing core ──
def draw_reactor(cv, t, now, state):
    sin, cos = math.sin, math.cos
    cx, cy = cv.DW / 2, cv.DH / 2
    R = min(cv.DW, cv.DH) / 2 * .94
    pulse = (.5 + .5 * sin(now * 6)) if state == "speaking" else (.5 + .5 * sin(now * 1.6))
    for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):            # dashed crosshair arms
        for d in range(int(R * .16), int(R * 1.12)):
            if (d // 4) % 3 != 2:
                cv.dot(cx + d * cos(ang), cy + d * sin(ang), .3, .2)
    for rf, v in ((.97, .5), (.86, .35), (.72, .45), (.5, .3), (.3, .9)):  # thin rings
        cv.arc(cx, cy, R * rf, 0, PI2, v, 1 - rf * .7)
    rot = t * .05
    for i in range(96):                                              # tick ring
        a = PI2 * i / 96 + rot
        r1 = R * (.82 if i % 4 == 0 else .78)
        cv.line(cx + R * .75 * cos(a), cy + R * .75 * sin(a), cx + r1 * cos(a), cy + r1 * sin(a),
                .6 if i % 4 == 0 else .35, .5)
    for i in range(120):                                             # outer speckles
        a = PI2 * i / 120 - t * .03
        r = R * (1.0 + .05 * ((i * 7) % 5) / 5)
        cv.dot(cx + r * cos(a), cy + r * sin(a), .25, .1)
    for off, span, rf, k, th in ((0, 1.0, .79, 1.0, 3), (2.3, .62, .79, 1.0, 3), (4.1, .36, .79, 1.0, 3),
                                 (1.0, 1.1, .63, -1.4, 2), (4.0, .7, .63, -1.4, 2), (.5, .5, .93, .6, 2)):
        a0 = off + t * k                                             # spinning arc segments
        for j in range(th):
            cv.arc(cx, cy, R * rf + (j - th / 2) * .9, a0, a0 + span, 1.0, .85)
    cr = R * (.09 + .025 * pulse)                                    # core
    ic = int(cr) + 1
    for dy in range(-ic, ic + 1):
        for dx in range(-ic, ic + 1):
            d2 = dx * dx + dy * dy
            if d2 <= cr * cr:
                cv.dot(cx + dx, cy + dy, 1.0 - .35 * d2 / (cr * cr + 1e-6), 1.0)
    cv.arc(cx, cy, R * .17, 0, PI2, .6 + .3 * pulse, .95)
    cv.arc(cx, cy, R * .22, 0, PI2, .25, .8)
    if state == "speaking":                                          # outgoing ripple
        rp = (now * .7) % 1
        cv.arc(cx, cy, R * (.2 + .8 * rp), 0, PI2, (1 - rp) * .8, .9)
    if state == "alert":
        for _ in range(40):
            a, r = random.random() * PI2, R * random.random()
            cv.dot(cx + r * cos(a), cy + r * sin(a), .5, .5)


# ── radar: rotating sweep with fading trail and blips ──
_BLIPS = [(random.Random(i).random() * PI2, .25 + .7 * random.Random(i + 40).random()) for i in range(9)]


def draw_radar(cv, t, now, state):
    sin, cos = math.sin, math.cos
    cx, cy = cv.DW / 2, cv.DH / 2
    R = min(cv.DW, cv.DH) / 2 * .94
    for rf in (.25, .5, .75, 1.0):
        cv.arc(cx, cy, R * rf, 0, PI2, .6 if rf == 1.0 else .3, 1 - rf * .6)
    for i in range(72):
        a = PI2 * i / 72
        r0 = R * (.92 if i % 6 == 0 else .96)
        cv.line(cx + r0 * cos(a), cy + r0 * sin(a), cx + R * cos(a), cy + R * sin(a), .5, .3)
    for d in range(int(R * .1), int(R), 3):
        for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d)):
            cv.dot(cx + dx, cy + dy, .25, .3)
    a = t * 1.8
    for k in range(26):
        f = 1 - k / 26
        ang = a - k * .05
        cv.line(cx, cy, cx + R * cos(ang), cy + R * sin(ang), f * f, .25 + .75 * f)
    for ang, rad in _BLIPS:
        v = 1 - ((a - ang) % PI2) / (PI2 * .85)
        if v > .1:
            x, y = cx + R * rad * cos(ang), cy + R * rad * sin(ang)
            for dx in (0, 1):
                for dy in (0, 1):
                    cv.dot(x + dx, y + dy, v, 1.0)
    cv.arc(cx, cy, 2, 0, PI2, 1, 1)
    if state == "alert":
        for _ in range(30):
            q, r = random.random() * PI2, R * random.random()
            cv.dot(cx + r * cos(q), cy + r * sin(q), .5, .5)


# ── atom: nucleus with three tilted orbits and electrons ──
def draw_atom(cv, t, now, state):
    sin, cos = math.sin, math.cos
    cx, cy = cv.DW / 2, cv.DH / 2
    R = min(cv.DW, cv.DH) / 2 * .94
    pulse = .5 + .5 * sin(now * (7 if state == "speaking" else 2))
    nr = R * (.07 + .02 * pulse)
    ic = int(nr) + 1
    for dy in range(-ic, ic + 1):
        for dx in range(-ic, ic + 1):
            if dx * dx + dy * dy <= nr * nr:
                cv.dot(cx + dx, cy + dy, 1.0, 1.0)
    cv.arc(cx, cy, R * .14, 0, PI2, .5, .9)
    rot = t * .12
    rx, ry = R * .96, R * .34
    for i in range(3):
        tilt = rot + i * math.pi / 3
        c_, s_ = cos(tilt), sin(tilt)
        for j in range(120):
            a = PI2 * j / 120
            x, y = rx * cos(a), ry * sin(a)
            cv.dot(cx + x * c_ - y * s_, cy + x * s_ + y * c_, .28, .25 + i * .1)
        ea = t * (1.3 + i * .45) + i * 2.1
        for k in range(9):
            a = ea - k * .07
            x, y = rx * cos(a), ry * sin(a)
            X, Y = cx + x * c_ - y * s_, cy + x * s_ + y * c_
            f = 1 - k / 9
            if k == 0:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        cv.dot(X + dx, Y + dy, 1.0, 1.0)
            else:
                cv.dot(X, Y, f * .8, .5 + .5 * f)


# ── hex: honeycomb with a pulse rippling out from the centre ──
def draw_hex(cv, t, now, state):
    sin, cos = math.sin, math.cos
    cx, cy = cv.DW / 2, cv.DH / 2
    R = min(cv.DW, cv.DH) / 2 * .94
    s = max(5.0, R * .17)
    hw = math.sqrt(3) * s
    rows = int(R / (1.5 * s)) + 2
    for row in range(-rows, rows + 1):
        for col in range(-rows, rows + 1):
            x = cx + col * hw + (hw / 2 if row % 2 else 0)
            y = cy + row * 1.5 * s
            d = math.hypot(x - cx, y - cy)
            if d > R * .98:
                continue
            w = .5 + .5 * sin(d * .16 - t * 2.6)
            v = .18 + .82 * w ** 3
            hue = min(1.0, d / R * .5 + w * .5)
            for k in range(6):
                a0 = math.pi / 6 + k * math.pi / 3
                a1 = a0 + math.pi / 3
                cv.line(x + s * .92 * cos(a0), y + s * .92 * sin(a0),
                        x + s * .92 * cos(a1), y + s * .92 * sin(a1), v, hue)
            if w > .75:
                cv.dot(x, y, 1.0, 1.0)


# ── warp: hyperspace streaks and tunnel rings ──
_STREAKS = [(random.Random(i).random() * PI2, random.Random(i + 50).random(), .5 + random.Random(i + 90).random())
            for i in range(64)]


def draw_warp(cv, t, now, state):
    sin, cos = math.sin, math.cos
    cx, cy = cv.DW / 2, cv.DH / 2
    R = math.hypot(cv.DW, cv.DH) / 2 * .6
    for ang, o, sp in _STREAKS:
        p = (t * .5 * sp + o) % 1
        rho = R * (.08 + 1.05 * p ** 2)
        ln = R * (.03 + .5 * p ** 2)
        cv.line(cx + rho * cos(ang), cy + rho * sin(ang), cx + (rho + ln) * cos(ang), cy + (rho + ln) * sin(ang),
                .25 + .75 * p, p)
    off = (t * .35) % 1
    for k in range(6):
        f = (k + off) / 6
        r = R * .9 * f ** 2.2
        if r >= 3:
            cv.arc(cx, cy, r, 0, PI2, .2 + .6 * f, f)
    cv.arc(cx, cy, 2.5, 0, PI2, 1.0, 1.0)


# ── storm: plasma ball with jagged lightning ──
def draw_storm(cv, t, now, state):
    sin, cos = math.sin, math.cos
    cx, cy = cv.DW / 2, cv.DH / 2
    R = min(cv.DW, cv.DH) / 2 * .94
    nb, per = {"standby": (2, .45), "listening": (3, .3), "thinking": (4, .2),
               "speaking": (6, .09), "alert": (7, .07)}[state]
    bucket = int(now / per)
    cv.arc(cx, cy, R, 0, PI2, .3, .2)
    cv.arc(cx, cy, R * .985, 0, PI2, .15, .1)
    for rr in (3, 5, 8):
        cv.arc(cx, cy, rr, 0, PI2, 1 - rr * .06, 1.0)
    for b in range(nb):
        rnd = random.Random(bucket * 31 + b)
        ang = rnd.random() * PI2
        x, y = cx, cy
        for s in range(1, 13):
            f = s / 12
            jit = (rnd.random() - .5) * 2 * R * .12 * (1 - f * .3)
            nx = cx + R * .96 * f * cos(ang) - jit * sin(ang)
            ny = cy + R * .96 * f * sin(ang) + jit * cos(ang)
            cv.line(x, y, nx, ny, 1 - f * .5, 1 - f * .6)
            x, y = nx, ny
            if rnd.random() < .18:
                q = ang + (rnd.random() - .5) * 1.4
                cv.line(x, y, x + R * .3 * cos(q), y + R * .3 * sin(q), .5, .5)


SHAPES = {"reactor": draw_reactor, "radar": draw_radar, "atom": draw_atom, "hex": draw_hex,
          "warp": draw_warp, "storm": draw_storm}


class Cloud:
    """Braille dust cloud: every dot is one speck; fixed random thresholds make specks drift in/out.
    Canvas themes (reactor, radar, atom, ...) draw through SHAPES instead."""
    def __init__(self):
        self.phase = 0.0
        self.last = time.time()
        self.thr = {}
        self.dots = 0
        self._gk = None
        self._g = None

    def _thr(self, w, h):
        k = (w, h)
        if k not in self.thr:
            rnd = random.Random(7)
            self.thr = {k: [[[rnd.random() for _ in range(8)] for _ in range(w)] for _ in range(h)]}
        return self.thr[k]

    def _geo(self, w, h):
        k = (w, h)
        if self._gk != k:
            Rr = min(w / 2, h) * 0.96
            g = []
            for y in range(h):
                v = ((y + .5 - h / 2) * 2) / Rr
                row = []
                for x in range(w):
                    u = (x + .5 - w / 2) / Rr
                    row.append((u, v, math.hypot(u, v), math.atan2(v, u)))
                g.append(row)
            self._gk, self._g = k, g
        return self._g

    def render(self, w, h, state):
        if w < 8 or h < 3:
            return Text("")
        now = time.time()
        self.phase += (now - self.last) * TSPEED[state]
        self.last = now
        t = self.phase
        if SHAPE in SHAPES:
            cv = Canvas(w, h)
            SHAPES[SHAPE](cv, t, now, state)
            self.dots = cv.n
            return cv.text(state)
        thr = self._thr(w, h)
        br = 1.0
        if state == "speaking":
            br = 1 + 0.035 * math.sin(now * 7)
        elif state == "listening":
            br = 0.93 + 0.04 * math.sin(now * 2)
        elif state == "alert":
            br = 1 + 0.05 * math.sin(now * 14)
        inv = 1 / br
        geo = self._geo(w, h)
        sin, cos, exp = math.sin, math.cos, math.exp
        out = Text(no_wrap=True)
        dots = 0
        for y in range(h):
            row_t = thr[y]
            row_g = geo[y]
            for x in range(w):
                u0, v0, r0, th0 = row_g[x]
                r = r0 * inv
                if r > 1.3:
                    out.append(" ")
                    continue
                u, v, th = u0 * inv, v0 * inv, th0
                if state == "thinking":
                    a = t * .9 * (1.2 - min(r, 1))