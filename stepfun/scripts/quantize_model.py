#!/usr/bin/env python3
"""Reproduce the INT8 ONNX artifact from the pinned FP32 BGE-small-zh model.

The submission loads a weight-only dynamic-quantized ONNX graph. This script
documents and reproduces that transformation with ONNX Runtime's quantizer.

Usage:
  python scripts/quantize_model.py
  python scripts/quantize_model.py --weight-type quint8 --per-channel
  python scripts/quantize_model.py --replace   # replace model_quantized.onnx
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnxruntime.quantization import QuantType, quantize_dynamic


ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "public" / "models" / "Xenova" / "bge-small-zh-v1.5"
DEFAULT_INPUT = MODEL_DIR / "onnx" / "model.onnx"
DEFAULT_OUTPUT = MODEL_DIR / "onnx" / "model_quantized_custom.onnx"
PINNED_OUTPUT = MODEL_DIR / "onnx" / "model_quantized.onnx"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def synthetic_inputs(session: ort.InferenceSession):
    rng = np.random.default_rng(20261031)
    batch, seq = 2, 24
    vocab = 30522
    input_ids = rng.integers(2000, 9000, size=(batch, seq), dtype=np.int64)
    attention = np.ones((batch, seq), dtype=np.int64)
    feed = {}
    for item in session.get_inputs():
        if item.name == "input_ids":
            feed[item.name] = input_ids
        elif item.name == "attention_mask":
            feed[item.name] = attention
        elif item.name == "token_type_ids":
            feed[item.name] = np.zeros((batch, seq), dtype=np.int64)
        else:
            raise SystemExit(f"Unexpected model input: {item.name}")
    return feed


def pooled_output(session: ort.InferenceSession, feed: dict[str, np.ndarray]):
    output = session.run(None, feed)[0]
    # Mean pooling over tokens, then L2 normalization.
    vector = output.mean(axis=1)
    vector = vector / np.linalg.norm(vector, axis=1, keepdims=True)
    return vector


def verify(fp32_path: Path, int8_path: Path) -> None:
    options = ort.SessionOptions()
    options.log_severity_level = 3
    fp32 = ort.InferenceSession(str(fp32_path), sess_options=options)
    int8 = ort.InferenceSession(str(int8_path), sess_options=options)
    feed = synthetic_inputs(fp32)
    a = pooled_output(fp32, feed)
    b = pooled_output(int8, feed)
    cosine = np.sum(a * b, axis=1)
    print(f"[verify] synthetic cosine similarity: {cosine.tolist()}")
    print(f"[verify] mean cosine: {float(cosine.mean()):.6f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--weight-type", choices=["qint8", "quint8"], default="quint8")
    parser.add_argument("--per-channel", action="store_true", default=True)
    parser.add_argument("--no-per-channel", dest="per_channel", action="store_false")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--verify", action="store_true", default=True)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(
            f"FP32 model not found: {args.input}\nRun `npm run setup:model` first."
        )

    weight_type = QuantType.QInt8 if args.weight_type == "qint8" else QuantType.QUInt8
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(f"[quantize] {args.input} -> {args.output}")
    print(f"[quantize] dynamic weight-only · {args.weight_type} · per_channel={args.per_channel}")

    # ONNX Runtime writes an intermediate model-inferred.onnx next to the input.
    # Some Windows builds fail on Unicode paths (e.g. a OneDrive-encoded folder),
    # so stage the graph in an ASCII temporary directory and copy the result back.
    with tempfile.TemporaryDirectory(prefix="edge-atlas-quant-") as work:
        work_dir = Path(work)
        staged_input = work_dir / "input.onnx"
        staged_output = work_dir / "output.onnx"
        shutil.copyfile(args.input, staged_input)
        quantize_dynamic(
            model_input=str(staged_input),
            model_output=str(staged_output),
            weight_type=weight_type,
            per_channel=args.per_channel,
            reduce_range=False,
        )
        onnx.checker.check_model(str(staged_output))
        shutil.copyfile(staged_output, args.output)

    before = args.input.stat().st_size
    after = args.output.stat().st_size
    print(f"[size] FP32: {before:,} bytes ({before / 1024 / 1024:.2f} MiB)")
    print(f"[size] INT8: {after:,} bytes ({after / 1024 / 1024:.2f} MiB)")
    print(f"[size] compression: {before / after:.3f}x")
    print(f"[sha256] {sha256(args.output)}")

    if args.verify:
        verify(args.input, args.output)

    print(f"[pinned] official artifact: {PINNED_OUTPUT}")
    print(
        f"[next] to use the reproduced artifact, rerun with --replace or copy it to "
        f"{PINNED_OUTPUT}"
    )
    if args.replace:
        shutil.copyfile(args.output, PINNED_OUTPUT)
        print(f"[replace] wrote {PINNED_OUTPUT}")


if __name__ == "__main__":
    main()
