#!/usr/bin/env python3
"""Normalize a legacy Gemma 4 MTP GGUF for current llama.cpp.

Early Gemma 4 assistant conversions used the ``gemma4_mtp`` architecture,
architecture-prefixed metadata, and ``mtp_*_proj`` tensor names.  Current
llama.cpp calls the architecture ``gemma4-assistant`` and its official
converter also emits a small ``rope_freqs.weight`` tensor for the global
attention layer.

This utility never edits the source file.  It writes a new GGUF, verifies
that every source tensor is present under its mapped name with identical raw
bytes, verifies the generated RoPE tensor, and then atomically publishes the
candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


LEGACY_ARCH = "gemma4_mtp"
CURRENT_ARCH = "gemma4-assistant"
LEGACY_PREFIX = f"{LEGACY_ARCH}."
CURRENT_PREFIX = f"{CURRENT_ARCH}."
NEXTN_LAYERS_KEY = f"{CURRENT_PREFIX}nextn_predict_layers"
ROPE_FREQS_TENSOR = "rope_freqs.weight"
PROPORTIONAL_ROTARY_FACTOR = 0.25

METADATA_KEY_OVERRIDES = {
    f"{LEGACY_PREFIX}backbone_embedding_length": (
        f"{CURRENT_PREFIX}embedding_length_out"
    ),
}

TENSOR_NAME_OVERRIDES = {
    "mtp_pre_proj.weight": "nextn.pre_projection.weight",
    "mtp_post_proj.weight": "nextn.post_projection.weight",
}


def load_gguf(path: Path) -> Any:
    sys.path.insert(0, str(path))
    import gguf  # type: ignore[import-not-found]

    return gguf


def field_value(reader: Any, key: str) -> Any:
    field = reader.get_field(key)
    return field.contents() if field else None


def mapped_metadata_key(key: str) -> str:
    if key in METADATA_KEY_OVERRIDES:
        return METADATA_KEY_OVERRIDES[key]
    if key.startswith(LEGACY_PREFIX):
        return f"{CURRENT_PREFIX}{key.removeprefix(LEGACY_PREFIX)}"
    return key


def mapped_tensor_name(name: str) -> str:
    return TENSOR_NAME_OVERRIDES.get(name, name)


def build_rope_freqs(rope_dimension_count: int) -> np.ndarray[Any, np.dtype[np.float32]]:
    if rope_dimension_count <= 0 or rope_dimension_count % 2:
        raise ValueError("rope dimension count must be a positive even integer")
    half_dimension = rope_dimension_count // 2
    rotary_dimension = int(
        rope_dimension_count * PROPORTIONAL_ROTARY_FACTOR / 2
    )
    values = np.empty(half_dimension, dtype=np.float32)
    values[:rotary_dimension] = 1.0
    values[rotary_dimension:] = 1e30
    return values


def tensor_digest(tensor: Any) -> str:
    return hashlib.sha256(memoryview(tensor.data)).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def comparable_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return comparable_value(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [comparable_value(item) for item in value]
    return value


def source_schema(reader: Any, gguf: Any) -> tuple[int, np.ndarray[Any, Any]]:
    block_count = field_value(reader, f"{LEGACY_PREFIX}block_count")
    rope_dimension_count = field_value(
        reader, f"{LEGACY_PREFIX}rope.dimension_count"
    )
    if not isinstance(block_count, (int, np.integer)) or int(block_count) <= 0:
        raise ValueError("legacy GGUF has no valid block_count")
    if not isinstance(rope_dimension_count, (int, np.integer)):
        raise ValueError("legacy GGUF has no valid rope.dimension_count")
    tensor_names = {tensor.name for tensor in reader.tensors}
    missing = set(TENSOR_NAME_OVERRIDES) - tensor_names
    if missing:
        raise ValueError(f"legacy GGUF is missing tensors: {sorted(missing)}")
    if ROPE_FREQS_TENSOR in tensor_names:
        raise ValueError(f"legacy GGUF already contains {ROPE_FREQS_TENSOR}")
    return int(block_count), build_rope_freqs(int(rope_dimension_count))


def copy_with_current_schema(source: Path, temporary: Path, gguf: Any) -> None:
    reader = gguf.GGUFReader(source, "r")
    architecture = field_value(reader, gguf.Keys.General.ARCHITECTURE)
    if architecture != LEGACY_ARCH:
        raise ValueError(
            f"expected {LEGACY_ARCH!r}, found {architecture!r} in {source}"
        )
    block_count, rope_freqs = source_schema(reader, gguf)

    writer = gguf.GGUFWriter(
        temporary,
        arch=CURRENT_ARCH,
        endianess=reader.endianess,
    )
    alignment = field_value(reader, gguf.Keys.General.ALIGNMENT)
    if alignment is not None:
        writer.data_alignment = int(alignment)

    mapped_keys: set[str] = set()
    for field in reader.fields.values():
        if field.name == gguf.Keys.General.ARCHITECTURE or field.name.startswith(
            "GGUF."
        ):
            continue
        key = mapped_metadata_key(field.name)
        if key in mapped_keys or key == NEXTN_LAYERS_KEY:
            raise ValueError(f"mapped metadata key collision: {key}")
        mapped_keys.add(key)
        value_type = field.types[0]
        sub_type = (
            field.types[-1]
            if value_type == gguf.GGUFValueType.ARRAY
            else None
        )
        writer.add_key_value(
            key,
            field.contents(),
            value_type,
            sub_type=sub_type,
        )
    writer.add_uint32(NEXTN_LAYERS_KEY, block_count)

    mapped_tensor_names: set[str] = set()
    for tensor in reader.tensors:
        name = mapped_tensor_name(tensor.name)
        if name in mapped_tensor_names or name == ROPE_FREQS_TENSOR:
            raise ValueError(f"mapped tensor name collision: {name}")
        mapped_tensor_names.add(name)
        writer.add_tensor_info(
            name,
            tensor.data.shape,
            tensor.data.dtype,
            tensor.data.nbytes,
            tensor.tensor_type,
        )
    writer.add_tensor_info(
        ROPE_FREQS_TENSOR,
        rope_freqs.shape,
        rope_freqs.dtype,
        rope_freqs.nbytes,
    )

    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    for tensor in reader.tensors:
        writer.write_tensor_data(tensor.data, tensor_endianess=reader.endianess)
    writer.write_tensor_data(rope_freqs)
    writer.close()


def expected_metadata(reader: Any, gguf: Any) -> dict[str, Any]:
    ignored = {
        "GGUF.version",
        "GGUF.tensor_count",
        "GGUF.kv_count",
        gguf.Keys.General.ARCHITECTURE,
    }
    expected = {
        mapped_metadata_key(name): comparable_value(field.contents())
        for name, field in reader.fields.items()
        if name not in ignored
    }
    expected[NEXTN_LAYERS_KEY] = int(
        field_value(reader, f"{LEGACY_PREFIX}block_count")
    )
    return expected


def actual_metadata(reader: Any, gguf: Any) -> dict[str, Any]:
    ignored = {
        "GGUF.version",
        "GGUF.tensor_count",
        "GGUF.kv_count",
        gguf.Keys.General.ARCHITECTURE,
    }
    return {
        name: comparable_value(field.contents())
        for name, field in reader.fields.items()
        if name not in ignored
    }


def verify_copy(source: Path, candidate: Path, gguf: Any) -> dict[str, Any]:
    original = gguf.GGUFReader(source, "r")
    rewritten = gguf.GGUFReader(candidate, "r")
    if field_value(rewritten, gguf.Keys.General.ARCHITECTURE) != CURRENT_ARCH:
        raise ValueError("rewritten GGUF has the wrong architecture")
    if len(rewritten.tensors) != len(original.tensors) + 1:
        raise ValueError("candidate must contain exactly one generated tensor")

    candidate_tensors = {tensor.name: tensor for tensor in rewritten.tensors}
    for before in original.tensors:
        expected_name = mapped_tensor_name(before.name)
        after = candidate_tensors.get(expected_name)
        if after is None:
            raise ValueError(f"mapped tensor is missing: {expected_name}")
        if before.tensor_type != after.tensor_type:
            raise ValueError(f"tensor type changed: {before.name}")
        if tuple(before.data.shape) != tuple(after.data.shape):
            raise ValueError(f"tensor shape changed: {before.name}")
        if tensor_digest(before) != tensor_digest(after):
            raise ValueError(f"tensor bytes changed: {before.name}")

    generated = candidate_tensors.get(ROPE_FREQS_TENSOR)
    if generated is None:
        raise ValueError(f"generated tensor is missing: {ROPE_FREQS_TENSOR}")
    _, expected_rope_freqs = source_schema(original, gguf)
    if generated.tensor_type != gguf.GGMLQuantizationType.F32:
        raise ValueError("generated RoPE tensor is not F32")
    if tuple(generated.data.shape) != tuple(expected_rope_freqs.shape):
        raise ValueError("generated RoPE tensor has the wrong shape")
    if not np.array_equal(generated.data, expected_rope_freqs):
        raise ValueError("generated RoPE tensor has the wrong values")

    expected_fields = expected_metadata(original, gguf)
    actual_fields = actual_metadata(rewritten, gguf)
    if expected_fields.keys() != actual_fields.keys():
        missing = sorted(expected_fields.keys() - actual_fields.keys())
        extra = sorted(actual_fields.keys() - expected_fields.keys())
        raise ValueError(f"metadata key mismatch: missing={missing}, extra={extra}")
    for key, before in expected_fields.items():
        if before != actual_fields[key]:
            raise ValueError(f"metadata changed: {key}")

    return {
        "source": str(source),
        "candidate": str(candidate),
        "source_architecture": LEGACY_ARCH,
        "candidate_architecture": CURRENT_ARCH,
        "source_tensor_count": len(original.tensors),
        "candidate_tensor_count": len(rewritten.tensors),
        "renamed_tensors": TENSOR_NAME_OVERRIDES,
        "generated_tensor": {
            "name": ROPE_FREQS_TENSOR,
            "shape": list(expected_rope_freqs.shape),
            "dtype": "float32",
        },
        "candidate_sha256": file_digest(candidate),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--gguf-py",
        type=Path,
        required=True,
        help="path to the matching llama.cpp gguf-py directory",
    )
    args = parser.parse_args()
    if args.source.resolve() == args.candidate.resolve():
        raise SystemExit("source and candidate must be different files")
    if args.candidate.exists():
        raise SystemExit(f"refusing to overwrite {args.candidate}")

    gguf = load_gguf(args.gguf_py)
    temporary = args.candidate.with_name(f".{args.candidate.name}.tmp-{os.getpid()}")
    try:
        copy_with_current_schema(args.source, temporary, gguf)
        report = verify_copy(args.source, temporary, gguf)
        temporary.replace(args.candidate)
        report["candidate"] = str(args.candidate)
    finally:
        temporary.unlink(missing_ok=True)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
