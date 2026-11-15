# Kokoro-82M FP16 TTS for JARVIS (Android / Termux)

Kokoro is an additional local TTS provider. It does not replace Edge, Piper,
Sherpa, or Phonon. JARVIS integrates both official ONNX voice packs:

- Kokoro v1.0: 54 multilingual voices
- Kokoro v1.1-zh: 103 Chinese/English voices
- Total: 157 unique voice IDs

## Install

From the JARVIS repository root in Termux:

\`\`\`bash
pkg install python curl coreutils espeak-ng sox
bash scripts/install_kokoro82m_termux.sh
\`\`\`

The installer downloads and SHA-256 verifies both FP16 ONNX models and both
voice archives. The combined download is approximately 390 MB. It validates
that the archives contain exactly 54 + 103 = 157 unique voice IDs.

No PC, PyTorch, or cloud inference is required. The ONNX models and voice
archives remain on local storage.

## Select one of the 157 voices

Run the guided setup:

\`\`\`bash
python setup.py
\`\`\`

Choose option 6 (Kokoro). Setup reads the installed voice archives and prints
every available voice, grouped by language and speaker gender. Enter the voice
ID to select it. The selected ID is saved as
\`JARVIS_KOKORO_NORMAL_VOICE\`.

The catalog includes American and British English, Spanish, French, Hindi,
Italian, Japanese, Brazilian Portuguese, and Mandarin Chinese voices. The
three English voices shipped inside the v1.1-zh pack are included in the
catalog and use that pack's matching model.

Japanese and Mandarin use the matching Misaki G2P frontends when the
installed Python version supports them. Misaki 0.9.4 currently declares
Python versions below 3.14. On Python 3.14 (the current Termux setup), JARVIS
falls back to eSpeak NG using the \`ja\` or \`cmn\` language frontend, following
the supplied direct Kokoro script. This fallback needs real-device
pronunciation and vocabulary-coverage validation for those languages; if the
phonemes do not match the model vocabulary, synthesis reports an error rather
than silently claiming a valid result. Other languages use Termux eSpeak NG.

## Context-aware matching-voice whisper

Kokoro uses the selected stock voice for ordinary speech. Whispering is an
occasional delivery style, selected only when the user's latest request
clearly calls for it. The policy is deterministic and local; it makes no
extra Groq or OmniRoute request.

- Ordinary conversation, explanations, coding, instructions, and alerts use
  the selected stock voice.
- Explicit requests to whisper, speak softly, lower the voice, or avoid waking
  someone select the whisper rendering of that same voice.
- Explicit requests to return to a normal voice take priority over whisper
  cues in the same prompt.
- Unclear context defaults to normal. Time of day alone never triggers
  whisper.
- Clearly urgent or emergency responses stay on the normal voice.

The whisper path retains the selected voice embedding and applies the
LPC/formant-preserving whisper DSP from the supplied \`3direct_kokoro.py\`.
It no longer substitutes a fixed male voice or blends in a separate Nicole
voice. The normal and whisper style arrays are both cached during startup.

## Configuration

Example \`.env\` settings:

\`\`\`dotenv
JARVIS_TTS_PROVIDER=kokoro
JARVIS_KOKORO_VOICE_MODE=auto
JARVIS_KOKORO_NORMAL_VOICE=am_eric
JARVIS_KOKORO_WHISPER_VOICE=jarvis_whisper
JARVIS_KOKORO_BREATH_MIX=0.82
JARVIS_KOKORO_THREADS=2
\`\`\`

Set \`JARVIS_KOKORO_VOICE_MODE=normal\` to disable automatic whisper selection,
or \`whisper\` to force the whisper preset. In \`auto\` mode, the user's latest
prompt selects the style. The selected stock voice ID can be any of the 157
IDs displayed by setup.

## Persistent preload and memory

When Kokoro is selected, TTSManager starts a background preload thread. One
persistent worker scans both voice catalogs, selects the model pack matching
the configured voice, loads only that ONNX model, and copies the selected
voice embedding into normal and whisper style caches. It then runs a real
inference warmup for the selected language and exercises the whisper DSP.

The unused ONNX model and all voice archives remain on disk; they are not
loaded into RAM. This avoids holding both approximately 156 MB model files
resident at once. The selected model still has a significant runtime memory
cost, so measure peak RSS and synthesis latency on the TB-X606V before
keeping the provider enabled permanently. If memory pressure is excessive,
switch \`JARVIS_TTS_PROVIDER\` back to an existing provider; downloaded assets
can remain on disk.
