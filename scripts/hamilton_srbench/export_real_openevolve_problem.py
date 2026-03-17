#!/usr/bin/env python3
"""SRBENCH_ANCHOR_REAL_EXPORT_SCRIPT

SRBENCH_ANCHOR_SYNC_EXPORT

Export one official OpenEvolve symbolic-regression problem pack and stage it for Hamilton.

This script prefers OpenEvolve's own `data_api.py` helpers when available, but it
also has a local fallback code generator so exports remain reproducible after the
temporary `/tmp/openevolve` checkout disappears. It stages either:
- a train-visible pack into `playground/hamilton_srbench/problems/`
- or a full pack with test/OOD arrays into `playground/hamilton_srbench/full_problems/`
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from contextlib import contextmanager
import hashlib
from pathlib import Path
from types import ModuleType
import re

import datasets
import h5py
import numpy as np
from huggingface_hub import snapshot_download


DEFAULT_OPENEVOLVE_ROOT = Path("/tmp/openevolve/examples/symbolic_regression")
DEFAULT_EXPORT_ROOT = Path("/tmp/hamilton_srbench_exports")
DEFAULT_PRIMARY_REPO_ID = "nnheui/llm-srbench"
DEFAULT_FALLBACK_REPO_ID = "pkuHaowei/llm-srbench"
DEFAULT_VISIBLE_DST_ROOT = Path("playground/hamilton_srbench/problems")
DEFAULT_FULL_DST_ROOT = Path("playground/hamilton_srbench/full_problems")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export and stage one real OpenEvolve symbolic-regression problem."
    )
    parser.add_argument("--split", required=True, help="LLM-SRBench split, e.g. phys_osc")
    parser.add_argument(
        "--problem",
        required=True,
        help="Problem equation name (e.g. PO10) or integer problem index",
    )
    parser.add_argument(
        "--openevolve-root",
        default=str(DEFAULT_OPENEVOLVE_ROOT),
        help="Path to OpenEvolve examples/symbolic_regression directory; optional if local fallback is acceptable",
    )
    parser.add_argument(
        "--export-root",
        default=str(DEFAULT_EXPORT_ROOT),
        help="Scratch directory where the full official pack will be generated",
    )
    parser.add_argument(
        "--dst-root",
        default=None,
        help="Destination root for Hamilton staging, defaults to playground/hamilton_srbench/problems",
    )
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_PRIMARY_REPO_ID,
        help="Primary Hugging Face dataset repo id for LLM-SRBench",
    )
    parser.add_argument(
        "--fallback-repo-id",
        default=DEFAULT_FALLBACK_REPO_ID,
        help="Fallback dataset repo id to try if the primary repo is gated or unavailable",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Also stage held-out test/OOD arrays into the Hamilton-visible directory",
    )
    parser.add_argument(
        "--sync-both",
        action="store_true",
        help="Stage both train-visible and full packs from one generated source snapshot",
    )
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_module(module_name: str, module_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to create module spec for: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_openevolve_root(path_arg: str) -> Path | None:
    root = Path(path_arg).resolve()
    if (root / "data_api.py").is_file():
        return root
    candidate = root / "examples" / "symbolic_regression"
    if (candidate / "data_api.py").is_file():
        return candidate
    return None


def load_dependencies(openevolve_root: Path | None) -> tuple[ModuleType | None, ModuleType, ModuleType]:
    data_api = None
    if openevolve_root is not None:
        if str(openevolve_root) not in sys.path:
            sys.path.insert(0, str(openevolve_root))
        data_api = load_module("openevolve_symbolic_data_api", openevolve_root / "data_api.py")

    fallback_codegen = load_module(
        "hamilton_srbench_local_codegen",
        repo_root() / "scripts" / "hamilton_srbench" / "openevolve_codegen_fallback.py",
    )
    stage_helper = load_module(
        "hamilton_srbench_stage_helper",
        repo_root() / "scripts" / "hamilton_srbench" / "stage_openevolve_problem.py",
    )
    return data_api, fallback_codegen, stage_helper


@contextmanager
def pushd(path: Path):
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def is_gated_repo_error(exc: Exception) -> bool:
    message = str(exc).lower()
    gated_markers = (
        "gatedrepoerror",
        "gated dataset",
        "401",
        "restricted",
        "authenticated",
        "must be authenticated",
        "access it",
    )
    return any(marker in message for marker in gated_markers)


def canonical_dataset_identifier(split_name: str) -> str:
    if split_name == "lsrtransform":
        return "lsr_transform"
    return split_name


def dataset_config_name(split_name: str, dataset_identifier: str) -> str:
    if split_name == "lsrtransform":
        return "lsr_transform"
    return f"lsr_synth_{dataset_identifier}"


def hdf5_group_prefix(split_name: str, dataset_identifier: str) -> str:
    if split_name == "lsrtransform":
        return "/lsr_transform"
    return f"/lsr_synth/{dataset_identifier}"


def row_candidates(row: dict) -> list[str]:
    candidates = []
    for key in ("name", "equation_idx", "instance_id"):
        value = row.get(key)
        if value is not None:
            candidates.append(str(value))

    instance_id = str(row.get("instance_id", ""))
    if instance_id:
        candidates.append(instance_id.split("_")[-1])
        match = re.search(r"([a-z]+[0-9]+)$", instance_id, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1))
    return candidates


def resolve_problem_row(metadata_rows, problem_ref: str) -> dict:
    try:
        problem_id = int(problem_ref)
    except ValueError:
        problem_id = None

    if problem_id is not None:
        if problem_id < 0 or problem_id >= len(metadata_rows):
            raise SystemExit(
                f"Problem index out of range: {problem_id}. Available range: 0..{len(metadata_rows) - 1}"
            )
        return metadata_rows[problem_id]

    wanted = problem_ref.upper()
    for row in metadata_rows:
        for candidate in row_candidates(row):
            if candidate.upper() == wanted:
                return row

    raise SystemExit(f"Unknown problem '{problem_ref}'. Use a valid equation name or integer index.")


def infer_equation_idx(row: dict) -> str:
    for key in ("name", "equation_idx"):
        value = row.get(key)
        if value:
            return str(value)

    candidates = row_candidates(row)
    if candidates:
        return candidates[-1].upper()
    raise RuntimeError("Could not infer equation identifier from dataset row.")


def parse_symbol_descs(description: str) -> dict[str, str]:
    desc_map = {}
    for line in description.splitlines():
        line = line.strip()
        if not line or ":" not in line or " - " not in line:
            continue
        _, payload = line.split(":", 1)
        symbol_name, symbol_desc = payload.split(" - ", 1)
        desc_map[symbol_name.strip()] = symbol_desc.strip()
    return desc_map


def to_symbol_list(value) -> list[str]:
    if isinstance(value, np.ndarray):
        return [str(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def normalize_input_matrix(raw) -> np.ndarray:
    if raw is None:
        return np.empty((0, 0), dtype=np.float64)
    arr = np.asarray(raw)
    if arr.size == 0:
        return np.empty((0, 0), dtype=np.float64)
    if arr.dtype == object:
        arr = np.vstack([np.asarray(item, dtype=np.float64) for item in arr.tolist()])
    else:
        arr = arr.astype(np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
    return arr


def normalize_output_vector(raw) -> np.ndarray:
    if raw is None:
        return np.empty((0,), dtype=np.float64)
    arr = np.asarray(raw)
    if arr.size == 0:
        return np.empty((0,), dtype=np.float64)
    if arr.dtype == object:
        arr = np.vstack([np.asarray(item, dtype=np.float64) for item in arr.tolist()])
    else:
        arr = arr.astype(np.float64)
    if arr.ndim == 2 and arr.shape[1] == 1:
        arr = arr[:, 0]
    return arr.reshape(-1)


def build_sample_matrix(
    symbols: list[str], input_vars: list[str], output_vars: list[str], input_matrix, output_vector
) -> np.ndarray:
    if len(output_vars) != 1:
        raise RuntimeError(f"Expected exactly one output variable, got: {output_vars}")

    symbol_data = {}
    for idx, symbol_name in enumerate(input_vars):
        symbol_data[symbol_name] = input_matrix[:, idx]
    symbol_data[output_vars[0]] = output_vector

    return np.column_stack([symbol_data[symbol] for symbol in symbols]).astype(np.float64)


def build_problem_data_from_row(
    split_name: str, snapshot_dir: Path, row: dict
) -> dict:
    dataset_identifier = canonical_dataset_identifier(split_name)
    equation_idx = infer_equation_idx(row)
    symbols = to_symbol_list(row.get("symbols"))
    input_vars = to_symbol_list(row.get("input_vars"))
    output_vars = to_symbol_list(row.get("output_vars"))
    desc_map = parse_symbol_descs(str(row.get("description", "")))

    symbol_properties = ["O" if symbol in output_vars else "V" for symbol in symbols]
    symbol_descs = [desc_map.get(symbol, symbol) for symbol in symbols]

    has_inline_arrays = "train_input" in row and "train_output" in row
    if has_inline_arrays:
        train_samples = build_sample_matrix(
            symbols,
            input_vars,
            output_vars,
            normalize_input_matrix(row.get("train_input")),
            normalize_output_vector(row.get("train_output")),
        )
        test_samples = build_sample_matrix(
            symbols,
            input_vars,
            output_vars,
            normalize_input_matrix(row.get("test_input")),
            normalize_output_vector(row.get("test_output")),
        )

        ood_input = normalize_input_matrix(row.get("ood_input"))
        ood_output = normalize_output_vector(row.get("ood_output"))
        ood_test_samples = None
        if ood_input.size > 0 and ood_output.size > 0:
            ood_test_samples = build_sample_matrix(
                symbols, input_vars, output_vars, ood_input, ood_output
            )
    else:
        sample_h5file_path = snapshot_dir / "lsr_bench_data.hdf5"
        hdf5_prefix = hdf5_group_prefix(split_name, dataset_identifier)
        with h5py.File(sample_h5file_path, "r") as sample_file:
            sample_group = sample_file[f"{hdf5_prefix}/{equation_idx}"]
            train_samples = sample_group["train"][...].astype(np.float64)
            test_samples = sample_group["test"][...].astype(np.float64)
            ood_test_samples = (
                sample_group["ood_test"][...].astype(np.float64)
                if "ood_test" in sample_group
                else None
            )

    return {
        "train": train_samples,
        "test": test_samples,
        "ood_test": ood_test_samples,
        "symbols": symbols,
        "symbol_descs": symbol_descs,
        "symbol_properties": symbol_properties,
        "expression": str(row.get("gt_expression") or row.get("expression") or ""),
        "dataset_identifier": dataset_identifier,
        "equation_idx": equation_idx,
    }


def load_problem_data(
    split_name: str, problem_ref: str, repo_ids: list[str]
) -> tuple[str, dict]:
    last_error: Exception | None = None
    dataset_identifier = canonical_dataset_identifier(split_name)
    config_name = dataset_config_name(split_name, dataset_identifier)

    for repo_id in repo_ids:
        try:
            snapshot_dir = Path(snapshot_download(repo_id=repo_id, repo_type="dataset"))
            metadata_rows = datasets.load_dataset(repo_id, config_name, split="train")
            problem_row = resolve_problem_row(metadata_rows, problem_ref)
            return repo_id, build_problem_data_from_row(split_name, snapshot_dir, problem_row)
        except Exception as exc:  # pragma: no cover - exercised through runtime integration
            last_error = exc
            if is_gated_repo_error(exc):
                continue
            raise

    if last_error is None:
        raise RuntimeError("No dataset repo ids were provided for initialization.")
    raise last_error


def generate_official_pack(
    data_api: ModuleType | None,
    fallback_codegen: ModuleType,
    split_name: str,
    problem_ref: str,
    export_root: Path,
    repo_ids: list[str],
) -> tuple[str, Path, str]:
    repo_id, problem_data = load_problem_data(split_name, problem_ref, repo_ids)

    export_root.mkdir(parents=True, exist_ok=True)
    if data_api is not None:
        with pushd(export_root):
            data_api.create_program(problem_data)
            data_api.create_evaluator(problem_data)
            data_api.create_config(problem_data)
        generated_dir = (
            export_root
            / "problems"
            / problem_data["dataset_identifier"]
            / str(problem_data["equation_idx"])
        )
        return repo_id, generated_dir, "openevolve_data_api"

    generated_dir = fallback_codegen.materialize_problem_pack(problem_data, export_root)
    return repo_id, generated_dir, "local_codegen_fallback"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_export_inventory(stage_helper: ModuleType, generated_src: Path) -> dict[str, dict[str, int | str]]:
    tracked = stage_helper.VISIBLE_FILES | stage_helper.HIDDEN_FILES | stage_helper.METADATA_FILES
    inventory = {}
    for file_name in sorted(tracked):
        source = generated_src / file_name
        if source.exists():
            inventory[file_name] = {
                "sha256": sha256_file(source),
                "size_bytes": source.stat().st_size,
            }
    return inventory


def write_export_manifest(
    stage_helper: ModuleType,
    generated_src: Path,
    *,
    split_name: str,
    problem_ref: str,
    used_repo_id: str,
    generator_backend: str,
) -> None:
    inventory = build_export_inventory(stage_helper, generated_src)
    canonical = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    manifest = {
        "split": split_name,
        "problem": problem_ref,
        "source_dir": str(generated_src.resolve()),
        "dataset_source_repo": used_repo_id,
        "generator_backend": generator_backend,
        "train_hashes": {
            name: inventory[name]["sha256"]
            for name in ("X_train_for_eval.npy", "y_train_for_eval.npy")
            if name in inventory
        },
        "inventory": inventory,
        "pack_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
    (generated_src / "export_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def stage_generated_pack(
    stage_helper: ModuleType, src_dir: Path, dst_root: Path, include_hidden: bool
) -> Path:
    dst_dir = stage_helper.infer_destination(src_dir, dst_root)
    stage_helper.stage_problem(src_dir, dst_dir, include_hidden=include_hidden)
    return dst_dir


def main() -> None:
    args = parse_args()

    openevolve_root = resolve_openevolve_root(args.openevolve_root)
    export_root = Path(args.export_root).resolve()
    if args.sync_both and args.dst_root:
        raise SystemExit("--dst-root cannot be combined with --sync-both; use the default synced destinations.")

    if args.dst_root:
        dst_root = Path(args.dst_root).resolve()
    else:
        default_dst = DEFAULT_FULL_DST_ROOT if args.include_hidden else DEFAULT_VISIBLE_DST_ROOT
        dst_root = (repo_root() / default_dst).resolve()
    repo_ids = [args.repo_id]
    if args.fallback_repo_id and args.fallback_repo_id not in repo_ids:
        repo_ids.append(args.fallback_repo_id)

    data_api, fallback_codegen, stage_helper = load_dependencies(openevolve_root)
    used_repo_id, generated_src, generator_backend = generate_official_pack(
        data_api, fallback_codegen, args.split, args.problem, export_root, repo_ids
    )
    write_export_manifest(
        stage_helper,
        generated_src,
        split_name=args.split,
        problem_ref=args.problem,
        used_repo_id=used_repo_id,
        generator_backend=generator_backend,
    )

    if args.sync_both:
        visible_dst = stage_generated_pack(
            stage_helper,
            generated_src,
            (repo_root() / DEFAULT_VISIBLE_DST_ROOT).resolve(),
            include_hidden=False,
        )
        full_dst = stage_generated_pack(
            stage_helper,
            generated_src,
            (repo_root() / DEFAULT_FULL_DST_ROOT).resolve(),
            include_hidden=True,
        )
    else:
        staged_dst = stage_generated_pack(
            stage_helper, generated_src, dst_root, include_hidden=args.include_hidden
        )

    if openevolve_root is None:
        print("OpenEvolve root not found; used local fallback code generator.")
    print(f"Dataset source repo: {used_repo_id}")
    print(f"Generator backend: {generator_backend}")
    print(f"Generated official source pack: {generated_src}")
    if args.sync_both:
        print(f"Staged visible pack: {visible_dst}")
        print(f"Staged full pack: {full_dst}")
    else:
        print(f"Staged Hamilton-visible pack: {staged_dst}")


if __name__ == "__main__":
    main()
