"""Benchmark the face-swap model on each CoreML compute unit and on the CPU.

    venv/bin/python scripts/benchmark.py [--runs 30] [--units ALL,CPUAndNeuralEngine]

Runs inswapper on random inputs (no camera, no UI) and prints median / p90
latency and the fps that latency allows. Use it to check which compute unit
is fastest on your Mac; Mirage defaults to CPUAndNeuralEngine.
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "models"
UNITS = ("ALL", "CPUAndNeuralEngine", "CPUAndGPU", "CPU")
COREML = "CoreMLExecutionProvider"


@dataclass
class Result:
    unit: str
    load_s: float
    median_ms: float
    p90_ms: float
    fps: float
    coreml_active: bool


def default_model() -> Path:
    """Prefer the CoreML-rewritten model the app caches, else the plain fp16 one."""
    exact = MODELS / "inswapper_128_fp16_coreml.onnx"
    if exact.is_file():
        return exact
    rewritten = sorted(MODELS.glob("inswapper_128_fp16_coreml*.onnx"))
    rewritten = [p for p in rewritten if ".tmp" not in p.name]
    return rewritten[0] if rewritten else MODELS / "inswapper_128_fp16.onnx"


def parse_units(text: str) -> list[str]:
    lookup = {u.lower(): u for u in UNITS}
    units: list[str] = []
    for raw in text.replace(" ", ",").split(","):
        if not raw:
            continue
        unit = lookup.get(raw.lower())
        if unit is None:
            raise argparse.ArgumentTypeError(f"unknown unit {raw!r}; choose from {', '.join(UNITS)}")
        if unit not in units:
            units.append(unit)
    if not units:
        raise argparse.ArgumentTypeError("no units given")
    return units


def providers_for(unit: str) -> list:
    if unit == "CPU":
        return ["CPUExecutionProvider"]
    # Same options the app's face swapper uses, with only the compute unit varied.
    return [
        (COREML, {
            "ModelFormat": "MLProgram",
            "MLComputeUnits": unit,
            "SpecializationStrategy": "FastPrediction",
            "AllowLowPrecisionAccumulationOnGPU": "1",
            "EnableOnSubgraphs": "1",
        }),
        "CPUExecutionProvider",
    ]


def make_inputs(session: ort.InferenceSession, rng: np.random.Generator) -> dict[str, np.ndarray]:
    feeds: dict[str, np.ndarray] = {}
    for spec in session.get_inputs():
        shape = [d if isinstance(d, int) and d > 0 else 1 for d in spec.shape]
        data = rng.random(shape, dtype=np.float32)
        if spec.name == "source":   # face embeddings are L2-normalised
            data /= np.linalg.norm(data)
        feeds[spec.name] = data
    return feeds


def bench(model: Path, unit: str, runs: int, warmup: int) -> Result:
    options = ort.SessionOptions()
    options.log_severity_level = 3
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    started = time.perf_counter()
    session = ort.InferenceSession(str(model), options, providers=providers_for(unit))
    feeds = make_inputs(session, np.random.default_rng(0))
    session.run(None, feeds)  # first run finishes CoreML compilation
    load_s = time.perf_counter() - started

    for _ in range(warmup):
        session.run(None, feeds)
    samples: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        session.run(None, feeds)
        samples.append((time.perf_counter() - t0) * 1000.0)

    coreml_active = COREML in session.get_providers()
    del session
    gc.collect()

    median = statistics.median(samples)
    p90 = float(np.percentile(samples, 90))
    return Result(unit, load_s, median, p90, 1000.0 / median, coreml_active)


def label(r: Result) -> str:
    if r.unit == "CPU":
        return "CPU"
    return f"CoreML {r.unit}" + ("" if r.coreml_active else " (fell back)")


def print_table(results: list[Result]) -> None:
    width = max(len("config"), *(len(label(r)) for r in results))
    header = f"{'config':<{width}} {'load':>7} {'median':>9} {'p90':>9} {'fps':>6}"
    print(header)
    print("─" * len(header))
    best = min(results, key=lambda r: r.median_ms)
    for r in results:
        mark = "  ◀ fastest" if r is best and len(results) > 1 else ""
        print(f"{label(r):<{width}} {r.load_s:>6.1f}s {r.median_ms:>7.1f}ms "
              f"{r.p90_ms:>7.1f}ms {r.fps:>6.1f}{mark}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=30, help="timed runs per config (default 30)")
    parser.add_argument("--warmup", type=int, default=3, help="untimed runs after loading (default 3)")
    parser.add_argument("--units", type=parse_units, default=list(UNITS),
                        help=f"comma-separated subset of {','.join(UNITS)} (default: all)")
    parser.add_argument("--model", type=Path, default=None, help="ONNX model (default: inswapper from ./models)")
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    model: Path = args.model or default_model()
    if not model.is_file():
        print(f"Model not found: {model}\nRun `make install` to download it.", file=sys.stderr)
        return 1

    units: list[str] = args.units
    if COREML not in ort.get_available_providers():
        skipped = [u for u in units if u != "CPU"]
        if skipped:
            print(f"CoreML is not available in this onnxruntime; skipping {', '.join(skipped)}", file=sys.stderr)
        units = [u for u in units if u == "CPU"]
        if not units:
            return 1

    if not args.json:
        print(f"model   {model.relative_to(REPO) if model.is_relative_to(REPO) else model}")
        print(f"runtime onnxruntime {ort.__version__}, {args.runs} runs + {args.warmup} warm-up per config\n")

    progress = sys.stdout.isatty() and not args.json
    results: list[Result] = []
    for unit in units:
        if progress:
            print(f"  measuring {unit}…", end="\r", flush=True)
        try:
            results.append(bench(model, unit, args.runs, args.warmup))
        except Exception as error:  # one broken config should not hide the others
            print(f"{unit}: failed: {error}", file=sys.stderr)
        if progress:
            print("\033[K", end="", flush=True)

    if not results:
        return 1
    if args.json:
        print(json.dumps({"model": str(model), "runs": args.runs,
                          "results": [asdict(r) for r in results]}, indent=2))
    else:
        print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
