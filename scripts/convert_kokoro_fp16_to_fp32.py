#!/usr/bin/env python3
"""Create a separate FP32 Kokoro ONNX copy from the installed FP16 model.

FP16 values are widened to FP32 without quantization. The source model is never
modified. This is intended for testing providers (such as XNNPACK) that reject
FP16 fully-connected tensors.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import onnx
from onnx import AttributeProto, TensorProto, helper, numpy_helper

FLOAT16 = TensorProto.FLOAT16
FLOAT = TensorProto.FLOAT


def convert_tensor(tensor: onnx.TensorProto) -> None:
    if tensor.data_type == FLOAT16:
        array = numpy_helper.to_array(tensor).astype("float32")
        converted = numpy_helper.from_array(array, name=tensor.name)
        tensor.CopyFrom(converted)


def convert_type(type_proto: onnx.TypeProto) -> None:
    kind = type_proto.WhichOneof("value")
    if kind == "tensor_type" and type_proto.tensor_type.elem_type == FLOAT16:
        type_proto.tensor_type.elem_type = FLOAT
    elif kind == "sequence_type":
        convert_type(type_proto.sequence_type.elem_type)
    elif kind == "optional_type":
        convert_type(type_proto.optional_type.elem_type)
    elif kind == "map_type":
        convert_type(type_proto.map_type.value_type)


def convert_graph(graph: onnx.GraphProto) -> None:
    for tensor in graph.initializer:
        convert_tensor(tensor)
    for sparse in graph.sparse_initializer:
        convert_tensor(sparse.values)
        convert_tensor(sparse.indices)
    for value in (*graph.input, *graph.output, *graph.value_info):
        convert_type(value.type)
    for node in graph.node:
        for attr in node.attribute:
            if attr.type == AttributeProto.TENSOR:
                convert_tensor(attr.t)
            elif attr.type == AttributeProto.TENSORS:
                for tensor in attr.tensors:
                    convert_tensor(tensor)
            elif attr.type == AttributeProto.GRAPH:
                convert_graph(attr.g)
            elif attr.type == AttributeProto.GRAPHS:
                for nested in attr.graphs:
                    convert_graph(nested)
            elif attr.type == AttributeProto.SPARSE_TENSOR:
                convert_tensor(attr.sparse_tensor.values)
                convert_tensor(attr.sparse_tensor.indices)
            elif attr.type == AttributeProto.SPARSE_TENSORS:
                for sparse in attr.sparse_tensors:
                    convert_tensor(sparse.values)
                    convert_tensor(sparse.indices)
            if node.op_type == "Cast" and attr.name == "to" and attr.i == FLOAT16:
                attr.i = FLOAT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"source model does not exist: {args.source}")
    if args.source.resolve() == args.destination.resolve():
        parser.error("destination must differ from source; original model is protected")

    model = onnx.load(str(args.source), load_external_data=True)
    convert_graph(model.graph)
    onnx.checker.check_model(model)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    onnx.save_model(model, str(args.destination))
    # Re-open and validate the exact serialized artifact.
    check = onnx.load(str(args.destination), load_external_data=True)
    onnx.checker.check_model(check)
    fp16_tensors = sum(
        1 for tensor in check.graph.initializer if tensor.data_type == FLOAT16
    )
    print(f"source={args.source}")
    print(f"destination={args.destination}")
    print(f"bytes={args.destination.stat().st_size}")
    print(f"remaining_fp16_initializers={fp16_tensors}")
    print("onnx_check=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
