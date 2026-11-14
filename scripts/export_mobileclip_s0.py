#!/usr/bin/env python3
"""Export Apple MobileCLIP-S0 image encoder and matching Android UI prototypes.

Run on a desktop/Linux machine with PyTorch installed, not on a low-RAM Android
device. The generated artifacts are consumed by intelligence/vision_engine.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_LABELS = [
    "an Android home screen with app icons",
    "an Android app drawer",
    "an Android Settings screen",
    "an Android quick settings panel",
    "an Android notification shade",
    "an Android lock screen",
    "an Android permission dialog",
    "an Android system confirmation dialog",
    "a mobile web browser showing a webpage",
    "a webpage with text and links",
    "a YouTube video player screen",
    "a video playback control panel",
    "a mobile messaging conversation",
    "a mobile email inbox",
    "an on-screen Android keyboard",
    "a text entry form on a phone",
    "a mobile camera viewfinder",
    "a photo gallery on a phone",
    "a mobile file manager",
    "a terminal command line interface",
    "a PDF or document viewer",
    "a map and navigation application",
    "a music player interface",
    "a mobile game screen",
    "a shopping application",
    "a banking application",
    "a system update screen",
    "an app installation screen",
    "a blank or mostly empty mobile screen",
    "an unknown mobile application interface",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="models/vision")
    parser.add_argument("--checkpoint", help="Optional local mobileclip_s0.pt checkpoint")
    args = parser.parse_args()

    try:
        import onnx
        import torch
        import mobileclip
        from huggingface_hub import hf_hub_download
        from mobileclip.modules.common.mobileone import reparameterize_model
    except ImportError as exc:
        raise SystemExit(
            "Missing export dependencies. Use a desktop Python environment and "
            "install PyTorch, ONNX, huggingface_hub, and Apple's ml-mobileclip package."
        ) from exc

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.checkpoint or hf_hub_download(
        repo_id="apple/MobileCLIP-S0",
        filename="mobileclip_s0.pt",
    )

    model, _, _ = mobileclip.create_model_and_transforms(
        "mobileclip_s0",
        pretrained=checkpoint,
        image_mean=(0.0, 0.0, 0.0),
        image_std=(1.0, 1.0, 1.0),
    )
    model.eval()
    model = reparameterize_model(model)

    class ImageEncoder(torch.nn.Module):
        def __init__(self, wrapped):
            super().__init__()
            self.wrapped = wrapped

        def forward(self, pixel_values):
            return self.wrapped.encode_image(pixel_values)

    image_model = ImageEncoder(model).eval()
    image_path = output_dir / "mobileclip_s0_image.onnx"
    dummy = torch.zeros(1, 3, 256, 256, dtype=torch.float32)
    torch.onnx.export(
        image_model,
        (dummy,),
        str(image_path),
        input_names=["pixel_values"],
        output_names=["image_embeds"],
        dynamic_axes={
            "pixel_values": {0: "batch_size"},
            "image_embeds": {0: "batch_size"},
        },
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )
    onnx.checker.check_model(onnx.load(str(image_path)))

    tokenizer = mobileclip.get_tokenizer("mobileclip_s0")
    prompts = [f"a screenshot of {label}" for label in DEFAULT_LABELS]
    with torch.no_grad():
        tokens = tokenizer(prompts)
        features = model.encode_text(tokens)
        features = torch.nn.functional.normalize(features.float(), dim=-1)
    vectors = features.cpu().tolist()

    manifest = {
        "schema_version": 1,
        "model": "MobileCLIP-S0",
        "source": "apple/MobileCLIP-S0",
        "input_size": [256, 256],
        "mean": [0.0, 0.0, 0.0],
        "std": [1.0, 1.0, 1.0],
        "resize": "shortest_edge",
        "crop": "center",
        "interpolation": "bicubic",
        "labels": [
            {"label": label, "embedding": vector}
            for label, vector in zip(DEFAULT_LABELS, vectors)
        ],
    }
    prototype_path = output_dir / "mobileclip_s0_prototypes.json"
    prototype_path.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(f"Image encoder: {image_path} ({image_path.stat().st_size:,} bytes)")
    print(f"Text prototypes: {prototype_path} ({prototype_path.stat().st_size:,} bytes)")
    print("Export complete. Copy both files into JARVIS models/vision/.")


if __name__ == "__main__":
    main()
