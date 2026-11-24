import io

from terminal_utils import clear_scrollback


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_clear_scrollback_only_emits_terminal_control_sequences():
    stream = TTY()
    assert clear_scrollback(stream) is True
    assert stream.getvalue() == "\x1b[3J\x1b[2J\x1b[H"


def test_clear_scrollback_does_nothing_for_non_tty_output():
    stream = io.StringIO()
    assert clear_scrollback(stream) is False
    assert stream.getvalue() == ""
