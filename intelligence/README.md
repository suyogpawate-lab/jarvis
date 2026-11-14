# JARVIS local screen perception

JARVIS keeps its existing Android screen-cast receiver and Accessibility controller.
For an explicit screen request, the latest in-memory frame is classified locally by
MobileCLIP-S0. Only the resulting short label/score list and the fresh Accessibility
hierarchy are sent to Groq. The JPEG is not uploaded to Groq or written to disk.
Groq remains the reasoning/planning model; MobileCLIP-S0 is not a captioner,
OCR engine, object detector, or action planner.

## Install directly on Android / Termux

No PC, PyTorch, or model export is required. From the JARVIS repository root run:

```bash
bash scripts/install_mobileclip_s0_termux.sh
```

The installer downloads the community's CPU-optimised FP16 ORT image encoder,
temporarily downloads the matching FP16 text encoder and CLIP BPE vocabulary,
generates 38 UI-scene text prototypes, verifies both model contracts, and removes
the temporary text model/tokenizer files. The image model and prototype manifest
remain under `models/vision/`. The text encoder is not kept resident by JARVIS.

Community export: `usama99athar/multilingual-embedders-onnx-coreml`,
`models/mobileclip-s0/ort/Fixed/`. The export documents image input
`pixel_values` = float32 [B,3,256,256], output `image_embedding` = float32
[B,512], text input `input_ids` = int64 [B,77], and text output
`text_embedding` = float32 [B,512]. The fixed ORT variants are intended for CPU;
the repository advises against NNAPI for this graph.

## Runtime configuration

Default files:
- `models/vision/mobileclip_s0_image_fp16.ort`
- `models/vision/mobileclip_s0_prototypes.json`

Override with `JARVIS_VISION_ONNX` and `JARVIS_VISION_PROTOTYPES`.
The image model loads lazily on the first explicit screen request and stays in
the bridge process for reuse. It uses CPUExecutionProvider, bilinear shortest-edge
resize to 256, center crop, RGB float32 / 255, and no mean/std normalization.

## Privacy and control boundaries

Frames and Accessibility snapshots remain ephemeral. MobileCLIP produces global
image embeddings and candidate scene labels only; it does not localize controls.
Natural-language control therefore targets exact Accessibility element indexes.
If no unambiguous accessible target exists, JARVIS must ask for clarification
rather than invent coordinates. Consequential actions remain blocked by the
existing guard.
