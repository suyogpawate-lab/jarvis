# Kokoro-82M TTS for JARVIS (Android / Termux)

Kokoro is an additional selectable local TTS provider. It does not replace Edge,
Piper, Sherpa, or Phonon. Set `JARVIS_TTS_PROVIDER=kokoro` to select it.

## Install

Run in Termux from the repository root:

```bash
bash scripts/install_kokoro82m_termux.sh
```

The installer downloads the Apache-2.0 ONNX Community Kokoro v1.0 model in
Q8F16 quantization (~86 MB) and all 54 stock voice packs (~0.5 MB each), creates
one additional voice pack, and compiles a persistent Rust worker. It requires
Termux Rust/Cargo, Python, and curl. No PyTorch, PC, or cloud inference is used.

## Voices

All 54 stock voice IDs are installed and loaded into the same model worker:
American English (11 female, 9 male), British English (4 female, 4 male),
Spanish (2 female, 1 male), French (1 female), Hindi (2 female, 2 male),
Italian (1 female, 1 male), Japanese (4 female, 1 male), Brazilian Portuguese
(1 female, 2 male), and Mandarin Chinese (4 female, 4 male).

Default JARVIS voice is `jarvis_nicole30`: a style-embedding interpolation of
70% `am_onyx` and 30% `af_nicole`. This is not waveform mixing or a claim
that the result will sound exactly like a male whisper. It blends the model's
per-token style vectors; timbre, breathiness and perceived gender may not
interpolate linearly, so listen and adjust after the first on-device samples.
The original `am_onyx` and `af_nicole` packs remain unchanged.

Change voice with `JARVIS_KOKORO_VOICE`; change speed with the existing TTS
speed argument. The custom voice can be regenerated with:

```bash
python scripts/build_kokoro_voice_blend.py --voices models/kokoro82m/voices --base am_onyx --donor af_nicole --weight 0.30 --output jarvis_nicole30
```

## Preloading and memory

When Kokoro is selected as `JARVIS_TTS_PROVIDER`, TTSManager starts its
preload thread at startup. The persistent Rust worker loads the quantized ONNX
session and all voice packs once, runs a real short synthesis warmup, then
stays resident. Subsequent chunks reuse the same model session. Other providers
are not automatically loaded in parallel; this avoids needlessly keeping several
large TTS engines resident on a low-memory tablet.

Kokoro inference is CPU-only in this Termux integration. The worker returns
24 kHz WAV chunks to the existing buffered mpv pipeline. Raw audio and temporary
WAV files are removed after playback by the existing pipeline.

## Runtime requirements / limitations

The worker uses `kokoro-en` 0.1.5 with its Misaki-lean G2P feature and ONNX
Runtime CPU execution. Its crate documents multiple languages/voices but notes
that English is the most thoroughly tested language. Test each non-English
language before relying on it for important speech. Peak RAM and synthesis
speed must be measured on the actual TB-X606V; the 86 MB model file size is not
a peak-RAM estimate.

Model: `onnx-community/Kokoro-82M-v1.0-ONNX`, Apache-2.0. The model and
voice assets are downloaded to the device and are not committed to this repo.
