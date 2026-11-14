#!/usr/bin/env python3
"""Build JARVIS UI text prototypes using the matching community MobileCLIP-S0 ORT tower."""
from __future__ import annotations
import argparse, gzip, html, json, re
from pathlib import Path
import numpy as np
import onnxruntime as ort

LABELS = [
    "an Android home screen with app icons", "an Android app drawer",
    "an Android Settings screen", "an Android quick settings panel",
    "an Android notification shade", "an Android lock screen",
    "an Android permission dialog", "an Android system confirmation dialog",
    "a mobile web browser showing a webpage", "a webpage with text and links",
    "a YouTube video player screen", "a video playback control panel",
    "a mobile messaging conversation", "a mobile email inbox",
    "an on-screen Android keyboard", "a text entry form on a phone",
    "a mobile camera viewfinder", "a photo gallery on a phone",
    "a mobile file manager", "a terminal command line interface",
    "a PDF or document viewer", "a map and navigation application",
    "a music player interface", "a mobile game screen",
    "a shopping application", "a banking application",
    "a system update screen", "an app installation screen",
    "a blank or mostly empty mobile screen", "an unknown mobile application interface",
    "a video streaming application", "a social media feed",
    "a web search results page", "a Wi-Fi settings page",
    "a Bluetooth settings page", "a battery and power settings page",
    "a file download progress screen", "an app crash or error dialog",
]

def byte_encoder():
    bs = list(range(ord("!"), ord("~")+1)) + list(range(ord("¡"), ord("¬")+1)) + list(range(ord("®"), ord("ÿ")+1))
    cs = bs[:]; n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b); cs.append(256+n); n += 1
    return dict(zip(bs, map(chr, cs)))

def make_tokenizer(vocab_path):
    lines = gzip.open(vocab_path, "rt", encoding="utf-8").read().splitlines()
    merges = [tuple(x.split()) for x in lines[1:49152-256-2+1] if x.strip()]
    enc = byte_encoder()
    vocab = list(enc.values()) + [v+"</w>" for v in enc.values()] + ["".join(x) for x in merges] + ["<|startoftext|>", "<|endoftext|>"]
    encoder = {v:i for i,v in enumerate(vocab)}
    ranks = {pair:i for i,pair in enumerate(merges)}
    cache = {}
    pat = re.compile(r"[a-z]+|[0-9]+|[^a-z0-9\s]+")
    def bpe(token):
        if token in cache: return cache[token]
        word = tuple(token[:-1]) + (token[-1]+"</w>",)
        while len(word) > 1:
            pairs = set(zip(word[:-1], word[1:]))
            best = min(pairs, key=lambda p:ranks.get(p, 10**12))
            if best not in ranks: break
            first, second = best; new=[]; i=0
            while i < len(word):
                try: j=word.index(first, i)
                except ValueError: new.extend(word[i:]); break
                new.extend(word[i:j]); i=j
                if i < len(word)-1 and word[i] == first and word[i+1] == second:
                    new.append(first+second); i += 2
                else:
                    new.append(word[i]); i += 1
            word = tuple(new)
        cache[token] = tuple(word)
        return cache[token]
    def tokenize(text):
        text = html.unescape(html.unescape(text)).strip().lower()
        ids = [49406]
        for token in pat.findall(text):
            token = "".join(enc[b] for b in token.encode("utf-8"))
            ids.extend(encoder[x] for x in bpe(token))
        ids = ids[:76] + [49407]
        return ids + [0] * (77-len(ids))
    return tokenize

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--text-model", required=True)
    p.add_argument("--vocab", required=True)
    p.add_argument("--output", required=True)
    a=p.parse_args()
    tok=make_tokenizer(a.vocab)
    prompts=["a screenshot of "+x for x in LABELS]
    ids=np.asarray([tok(x) for x in prompts], dtype=np.int64)
    opts=ort.SessionOptions(); opts.intra_op_num_threads=2; opts.inter_op_num_threads=1
    sess=ort.InferenceSession(a.text_model, sess_options=opts, providers=["CPUExecutionProvider"])
    inp=sess.get_inputs()
    if len(inp)!=1 or inp[0].name!="input_ids":
        raise RuntimeError("Unexpected MobileCLIP text encoder input contract.")
    out=sess.run(["text_embedding"], {"input_ids":ids})[0]
    vectors=np.asarray(out,dtype=np.float32)
    if vectors.shape!=(len(LABELS),512):
        raise RuntimeError(f"Unexpected text embedding shape: {vectors.shape}")
    norms=np.linalg.norm(vectors,axis=1,keepdims=True)
    vectors=vectors/np.maximum(norms,1e-12)
    manifest={"schema_version":2,"model":"MobileCLIP-S0","source":"usama99athar/multilingual-embedders-onnx-coreml","input_size":[256,256],"resize":"shortest-edge","crop":"center","interpolation":"bilinear","scale":"divide_by_255","mean":[0,0,0],"std":[1,1,1],"labels":[{"label":label,"embedding":vec.tolist()} for label,vec in zip(LABELS,vectors)]}
    outpath=Path(a.output); outpath.parent.mkdir(parents=True,exist_ok=True)
    outpath.write_text(json.dumps(manifest,separators=(",",":")),encoding="utf-8")
    print(f"Wrote {outpath} with {len(LABELS)} matching 512-d text prototypes.")
if __name__=="__main__": main()
