#!/usr/bin/env python3
"""JARVIS terminal UI for Termux: dust-cloud presence + prompt box. No localhost.
Setup : pip install rich   (put jarvis_ui.py next to jarvis.py in ~/jarvis)
Run   : python jarvis_ui.py        (the plain CLI is still: python jarvis.py)
Typing = LISTENING, JARVIS working = THINKING, reply/TTS = SPEAKING, error = ALERT.
Preview a mode: /listening /thinking /speaking /alert /standby   |   /q or Ctrl-C quits.
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


# ───────────────────────── dust cloud ─────────────────────────
# per state: (dim speck rgb, bright speck rgb, haze rgb)
TINT = {
    "standby":   ((44, 62, 56), (190, 208, 200), (14, 28, 24)),
    "listening": ((50, 84, 84), (222, 246, 246), (14, 38, 42)),
    "thinking":  ((72, 62, 98), (236, 226, 252), (30, 22, 48)),
    "speaking":  ((58, 82, 66), (232, 241, 235), (20, 42, 28)),
    "alert":     ((104, 40, 40), (255, 222, 212), (52, 12, 12)),
}
TSPEED = {"standby": .35, "listening": .8, "thinking": 1.8, "speaking": 1.4, "alert": 2.6}
BIT = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
_STY = {}


def _sty(state, bi, hi):
    k = (state, bi, hi)
    s = _STY.get(k)
    if s is None:
        dim, br, hz = TINT[state]
        f, hf = bi / 9, hi / 5
        fg = [int(dim[i] + (br[i] - dim[i]) * f) for i in range(3)]
        bg = [int(hz[i] * hf) for i in range(3)]
        s = Style(color=Color.from_rgb(*fg), bgcolor=Color.from_rgb(*bg))
        _STY[k] = s
    return s


class Cloud:
    """Braille dust cloud: every dot is one speck; fixed random thresholds make specks drift in/out."""
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
                    u, v = u * cos(a) - v * sin(a), u * sin(a) + v * cos(a)
                    th = th0 + a
                re = .86 + .09 * sin(3 * th + t * .5) + .06 * sin(5 * th - t * .7) + .04 * sin(9 * th + t)
                mask = (re + .12 - r) / .42
                if mask <= 0:
                    out.append(" ")
                    continue
                if mask > 1:
                    mask = 1
                n = .5 + .5 * (.5 * sin(u * 5.1 + t * .3 + sin(v * 3.3 + t * .2) * 1.7)
                               + .3 * sin(v * 6.7 - t * .25 + sin(u * 4.1) * 1.3)
                               + .2 * sin((u + v) * 9.3 + t * .4))
                rim = exp(-((r - re * .82) / .22) ** 2)
                wisp = 0.0
                if u > -.1 and abs(v - .12) < .5:
                    wisp = exp(-(((u - .52) / .38) ** 2 + ((v - .12 - .14 * sin(u * 6 + t)) / .09) ** 2)) \
                        * (.55 + .45 * sin(u * 15 + t * 1.3))
                rip = 0.0
                if state == "speaking":
                    rip = .12 * sin(r * 14 - now * 9)
                elif state == "listening":
                    rip = .12 * sin(r * 12 + now * 5)
                d = mask * (.16 + .42 * n * n + .5 * rim + .7 * wisp + rip)
                if state == "alert":
                    d += .15 * random.random() - .05
                bits = 0
                if d > .02:
                    tc = row_t[x]
                    for k in range(8):
                        if d > tc[k]:
                            bits |= BIT[k]
                            dots += 1
                bi = int(min(1.0, .25 + .5 * d + .6 * wisp) * 9)
                hi = min(5, int(mask * (.12 + .3 * n) * 12))
                out.append(chr(0x2800 + bits) if bits else " ", style=_sty(state, bi, hi))
            out.append("\n")
        self.dots = dots
        return out


core = Cloud()


# ───────────────────────── UI pieces ─────────────────────────
class Dyn:
    """Renderable that receives the real width/height of its slot."""
    def __init__(self, fn):
        self.fn = fn

    def __rich_console__(self, console, options):
        yield self.fn(options.max_width, options.height or 12)


def grad(txt, c1=(183, 220, 160), c2=(122, 199, 154)):
    t = Text()
    n = max(1, len(txt) - 1)
    for i, ch in enumerate(txt):
        f = i / n
        c = [int(c1[k] + (c2[k] - c1[k]) * f) for k in range(3)]
        t.append(ch, style=f"bold rgb({c[0]},{c[1]},{c[2]})")
    return t


def tabs():
    g = Table.grid(expand=True)
    for _ in range(4):
        g.add_column(ratio=1, justify="center")
    cells = []
    for s in ("listening", "thinking", "speaking", "alert"):
        if S["state"] == s:
            st = "bold white on #d64545" if s == "alert" else "bold #0d1510 on #7fc79a"
        else:
            st = "#aab0ac"
        cells.append(Text(f" {s.capitalize()} ", style=st))
    g.add_row(*cells)
    return Panel(g, box=box.ROUNDED, border_style="#26292b", style="on #141618", padding=0)


def wrap_hard(s, w):
    return [s[i:i + w] for i in range(0, len(s), w)] or [""]


def input_line(w, h):
    prompt = "› "
    blink = int(time.time() * 2) % 2 == 0
    buf = S["buf"]
    cur = max(0, min(S["cur"], len(buf)))
    if not buf:
        t = Text(no_wrap=True, overflow="crop")
        t.append(prompt, style="bold #7fc79a")
        t.append("█" if blink else " ", style="#7fc79a")
        t.append(" Jarvis is working..." if S["busy"] else " Ask Jarvis anything", style="#555b57")
        return t
    w = max(4, w)
    full = prompt + buf + " "              # trailing cell so the cursor can sit after the last char
    pos = len(prompt) + cur
    lines = wrap_hard(full, w)
    cl = pos // w                          # line holding the cursor
    h = max(1, h)
    first = max(0, min(cl - h + 1, len(lines) - h)) if len(lines) > h else 0
    t = Text()
    for li in range(first, min(len(lines), first + h)):
        ln = lines[li]
        base = li * w
        for ci, chr_ in enumerate(ln):
            idx = base + ci
            if idx == pos:
                t.append(chr_ if chr_ != " " or idx < len(full) - 1 else " ",
                         style="reverse #7fc79a" if blink else "bright_white")
            elif idx < len(prompt):
                t.append(chr_, style="bold #7fc79a")
            else:
                t.append(chr_, style="bright_white")
        if li < min(len(lines), first + h) - 1:
            t.append("\n")
    return t


_wrap = {"k": None, "lines": []}


def reply_line(w, h):
    txt = S["reply"]
    h = max(1, h)
    S["rh"] = h
    if S.get("_rt") != S["reply_t"]:  # new reply: jump to the newest text
        S["_rt"] = S["reply_t"]
        S["scroll"] = 0
    if not txt:
        S["sc"] = None
        return Text("…" if S["busy"] else "", style="#555b57")
    shown = txt[:max(0, int((time.time() - S["reply_t"]) * 70))]  # typewriter reveal
    if _wrap["k"] != (shown, w):
        lines = []
        for para in shown.split("\n"):
            lines += textwrap.wrap(para, max(4, w)) or [""]
        _wrap["k"], _wrap["lines"] = (shown, w), lines
    lines = _wrap["lines"]
    n = len(lines)
    off = max(0, min(S["scroll"], n - h))
    S["scroll"] = off
    end = n - off
    S["sc"] = (end - h + 1, end, n) if n > h else None
    return Text("\n".join(lines[end - h:end] if n > h else lines), style="#b7d4c0")


def input_box():
    active = bool(S["buf"]) or S["busy"]
    return Panel(Dyn(input_line), box=box.ROUNDED, padding=(0, 1),
                 border_style="#7fc79a" if active else "#2e3a33",
                 title=Text(" YOU ", style="bold #7fc79a"), title_align="left",
                 subtitle=Text(f" {_fps['v']:.0f} fps ", style="#555b57"), subtitle_align="right")


def response_box():
    st = S["state"]
    border = "#d64545" if st == "alert" else "#7fc79a" if st == "speaking" else "#2e3a33"
    sc = S.get("sc")
    sub = Text(f" {sc[0]}-{sc[1]}/{sc[2]}  Ctrl+↑↓ PgUp PgDn ", style="#7fc79a") if sc else None
    return Panel(Dyn(reply_line), box=box.ROUNDED, padding=(0, 1), border_style=border,
                 title=Text(" J.A.R.V.I.S. ", style="bold #7fc79a"), title_align="left",
                 subtitle=sub, subtitle_align="right")


def build():
    now = time.time()
    _fps["v"] = _fps["v"] * .9 + (1 / max(now - _fps["t"], 1e-3)) * .1
    _fps["t"] = now
    W, H = CON.size
    parts = []
    if H >= 30:
        g = Table.grid(expand=True)
        g.add_column(ratio=1)
        g.add_column(justify="right")
        g.add_row(Group(Text("Your AI needs", style="bold white"), grad("a presence.")),
                  Text(f" {core.dots:,} specks of dust ", style="#c8cdc9 on #16181a"))
        parts.append(Layout(g, size=2))
    parts.append(Layout(tabs(), size=3))
    parts.append(Layout(Dyn(lambda w, h: core.render(w, h, S["state"])), ratio=1))
    if W >= 70:  # prompt and response side by side
        bot = Layout(size=6 if H < 30 else 9)
        bot.split_row(Layout(input_box(), ratio=1), Layout(response_box(), ratio=1))
        parts.append(bot)
    else:  # stacked: prompt, then response below it
        parts.append(Layout(input_box(), size=3))
        parts.append(Layout(response_box(), size=5 if H < 30 else 7))
    lay = Layout()
    lay.split_column(*parts)
    return lay


CON = Console(file=sys.__stdout__)


def cursor(show):
    """The terminal's own cursor is the white block that sweeps over the screen while it redraws."""
    try:
        sys.__stdout__.write("\x1b[?25h" if show else "\x1b[?25l")
        sys.__stdout__.flush()
    except Exception:
        pass


def main():
    import termios, tty, codecs
    global _ev_pos, BRAIN, BRAIN_ERR
    print("Starting JARVIS...")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import jarvis as brain
        brain.init_services()
        BRAIN = brain
    except Exception as e:
        BRAIN_ERR = f"Could not load jarvis.py: {type(e).__name__}: {e}"
        print(BRAIN_ERR)
        time.sleep(2)
    try:
        _ev_pos = os.path.getsize(EV_FILE)
    except OSError:
        _ev_pos = 0
    os.makedirs(os.path.join(HOME, "data"), exist_ok=True)
    logf = open(os.path.join(HOME, "data", "ui.log"), "a", buffering=1)
    out_o, err_o = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = logf  # keep module prints off the screen
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    dec = codecs.getincrementaldecoder("utf-8")("ignore")
    try:
        tty.setcbreak(fd)
        threading.Thread(target=speech_watch, daemon=True).start()
        with Live(get_renderable=build, console=CON, screen=True, refresh_per_second=FPS):
            last_hide = 0.0
            while not S["quit"]:
                if time.time() - last_hide > 0.1:  # keep it hidden, whatever re-shows it
                    cursor(False)
                    last_hide = time.time()
                pump_events()
                if S["state"] == "alert" and S["alert_until"] and time.time() > S["alert_until"] and not S["busy"]:
                    S["alert_until"] = 0.0
                    settle()
                if BRAIN is not None and not S["busy"]:
                    item = BRAIN.pop_notification()
                    if item:
                        notify(item)
                if select.select([fd], [], [], 0.02)[0]:
                    for ch in dec.decode(os.read(fd, 4096)):
                        handle_key(ch)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        cursor(True)
        sys.stdout, sys.stderr = out_o, err_o
        if BRAIN is not None:
            BRAIN.shutdown()
        print("JARVIS OFFLINE")


if __name__ == "__main__":
    main()
