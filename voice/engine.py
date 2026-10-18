"""
JARVIS local voice engine.

Pipeline:

    microphone
        ↓
    offline STT
        ↓
    wake-word detection
        ↓
    command
        ↓
    JARVIS callback
        ↓
    local TTS
"""

from pathlib import Path

from .config import MODEL_DIR
from .wakeword import WakeWordDetector
from .stt import OfflineSTT
from .tts import LocalTTS
from .audio import AudioInput


class VoiceEngine:

    def __init__(
        self,
        command_handler=None,
        model_path=None,
    ):

        self.command_handler = command_handler

        self.model_path = Path(
            model_path
            if model_path
            else MODEL_DIR / "vosk-model"
        )

        self.audio = AudioInput()

        self.wakeword = WakeWordDetector(
            "jarvis"
        )

        self.stt = OfflineSTT(
            self.model_path
        )

        self.tts = LocalTTS()

        self.running = False
        self.awake = False

    def load(self):

        print("[VOICE] Loading offline STT...")

        self.stt.load()

        print("[VOICE] Offline STT loaded")

    def start(self):

        if self.running:
            return

        self.running = True

        self.audio.start()

        print("[VOICE] Local voice engine active")
        print("[VOICE] Wake word: JARVIS")
        print("[VOICE] Cloud voice: DISABLED")

        try:

            while self.running:

                audio = self.audio.read(
                    timeout=0.5
                )

                if audio is None:
                    continue

                text = self.stt.accept_audio(
                    audio
                )

                if not text:
                    continue

                self.process_text(text)

        except KeyboardInterrupt:

            self.stop()

    def process_text(self, text):

        print(
            f"[VOICE/STT] {text}"
        )

        if not self.awake:

            if self.wakeword.detect(text):

                self.awake = True

                command = (
                    self.wakeword
                    .remove_wake_word(text)
                )

                print(
                    "[WAKE] JARVIS ACTIVATED"
                )

                self.tts.speak(
                    "Yes?"
                )

                if command:
                    self.execute_command(
                        command
                    )

            return

        self.execute_command(
            text
        )

    def execute_command(self, command):

        command = command.strip()

        if not command:
            return

        print(
            f"[VOICE/CMD] {command}"
        )

        if self.command_handler:

            try:

                response = self.command_handler(
                    command
                )

                if response:
                    self.tts.speak(
                        response
                    )

            except Exception as exc:

                print(
                    f"[VOICE/ERROR] {exc}"
                )

                self.tts.speak(
                    "I encountered an error."
                )

        self.awake = False

    def stop(self):

        self.running = False

        self.audio.stop()

        print(
            "[VOICE] Voice engine stopped"
        )
