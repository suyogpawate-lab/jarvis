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

The installer downloads and SHA-256 verifies:
- `kokoro-v1.0.fp16.onnx` (~156 MB)
- `voices-v1.0.bin` (~27 MB; all 54 voice presets)

It uses the existing Termux `python-numpy` and `python-onnxruntime`
installations. It does not require Rust, PyTorch, a PC, or cloud inference.

## Whisper voice based on the supplied implementation

The default preset is `jarvis_whisper`, built from the uploaded
`2direct_kokoro.py` logic:

- **Formant mode (default):** 90% `af_nicole` + 10% selected male style
  (`am_eric` by default), followed by the supplied SoX vocal-tract pitch/
  formant shift and bass/treble shaping.
- **LPC mode:** 75% male style + 25% `af_nicole`, followed by the supplied
  cepstral-envelope / aspirated-noise whisper vocoder.
- The original 54 voice vectors are never overwritten. Any stock voice ID can
  be selected directly to bypass the custom whisper processing.

The 90/10 and 75/25 ratios are the ratios in your supplied script; they replace
the earlier proposed 70/30 embedding mix. The two modes are alternatives, not
a promise that a particular timbre will be achieved on every device.

## Configuration

Set these in `.env`:

```dotenv
JARVIS_TTS_PROVIDER=kokoro
JARVIS_KOKORO_VOICE=jarvis_whisper
JARVIS_KOKORO_MODE=formant
JARVIS_KOKORO_MALE_VOICE=am_eric
JARVIS_KOKORO_FORMANT_DEPTH=-300
JARVIS_KOKORO_BREATH_MIX=0.82
JARVIS_KOKORO_THREADS=2
```

Use `JARVIS_KOKORO_MODE=lpc` to use the alternate LPC whisper path.
Use any of the 54 stock voice IDs as `JARVIS_KOKORO_VOICE` to use that voice
without the custom whisper DSP. Use `bm_george` as the male base for British
English.

## Persistent preload and memory

When Kokoro is selected, TTSManager starts a background preload thread. A
persistent Python worker loads the FP16 ONNX session and the full voice archive
once, runs a real inference warmup, and stays resident. Sentence chunks reuse
that session; they do not reload the model. CPU thread count defaults to 2 to
limit contention on the Android tablet.

The FP16 model file is about 156 MB, but this is not the peak-RAM requirement.
ONNX Runtime's session, activations, voice vectors, and JARVIS services add
memory overhead. The actual peak RSS and synthesis latency must be measured on
the TB-X606V before keeping this provider enabled permanently. If memory
pressure is excessive, switch `JARVIS_TTS_PROVIDER` back to the existing
provider; the downloaded assets can remain on disk.

Model release: `thewh1teagle/kokoro-onnx`, model-files-v1.1. The worker checks
that the archive contains all 54 voices and that the embedded model vocabulary
is present before advertising readiness.
