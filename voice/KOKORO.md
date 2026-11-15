# Kokoro-82M FP16 TTS for JARVIS (Android / Termux)

Kokoro is an additional local TTS provider. It does not replace Edge, Piper,
Sherpa, or Phonon. The integration uses the FP16 ONNX model and one NPZ-style
voice archive containing all 54 stock voices.

## Install

From the JARVIS repository root in Termux:

```bash
pkg install python curl espeak-ng sox
bash scripts/install_kokoro82m_termux.sh
```

The installer downloads and SHA-256 verifies the FP16 model (~156 MB) and the
voice archive (~27 MB). It uses the existing Termux NumPy and ONNX Runtime
installations; no PC, PyTorch, or cloud inference is required.

## Context-aware voice selection

Kokoro uses a normal stock voice by default. Whispering is an occasional
delivery style, selected only when the user's latest request clearly calls
for it. The policy is deterministic and local; it makes no extra Groq or
OmniRoute request.

- Ordinary conversation, explanations, coding, instructions, and alerts use
  the configured normal voice.
- Explicit requests to whisper, speak softly, lower the voice, or avoid waking
  someone select the custom `jarvis_whisper` voice.
- Explicit requests to return to a normal voice take priority over whisper
  cues in the same prompt.
- Unclear context defaults to normal. Time of day alone never triggers whisper.
- Clearly urgent or emergency responses stay on the normal voice, even when
  whisper mode is forced.

The normal voice defaults to `am_eric`. The whisper preset retains the supplied
`2direct_kokoro.py` formant/LPC processing and the original 54 stock voice
vectors remain untouched.

## Configuration

Add these optional settings to `.env`:

```dotenv
JARVIS_TTS_PROVIDER=kokoro
JARVIS_KOKORO_VOICE_MODE=auto
JARVIS_KOKORO_NORMAL_VOICE=am_eric
JARVIS_KOKORO_WHISPER_VOICE=jarvis_whisper
JARVIS_KOKORO_MODE=formant
JARVIS_KOKORO_MALE_VOICE=am_eric
JARVIS_KOKORO_NICOLE_MIX=0.90
JARVIS_KOKORO_FORMANT_DEPTH=-300
JARVIS_KOKORO_BREATH_MIX=0.82
JARVIS_KOKORO_THREADS=2
```

Set `JARVIS_KOKORO_VOICE_MODE=normal` to disable automatic whisper selection,
or `whisper` to force the whisper preset. In `auto` mode, the user's latest
prompt selects the style. Set `JARVIS_KOKORO_NORMAL_VOICE` to any of the 54
stock voice IDs; `bm_george` selects a British male voice. The old
`JARVIS_KOKORO_VOICE` setting remains a compatibility fallback for the
normal voice, except that its former `jarvis_whisper` default is deliberately
ignored.

## Persistent preload and memory

When Kokoro is selected, TTSManager starts a background preload thread. One
persistent worker loads the FP16 ONNX session and all 54 voice vectors once,
runs an inference warmup, and stays resident. Normal and whisper styles reuse
that same session; switching styles does not load a second model. The CPU
thread count defaults to 2.

The model file is about 156 MB, but this is not the peak-RAM requirement.
Measure actual peak RSS and synthesis latency on the TB-X606V before keeping
the provider enabled permanently. If memory pressure is excessive, switch
`JARVIS_TTS_PROVIDER` back to an existing provider; downloaded assets can
remain on disk.
