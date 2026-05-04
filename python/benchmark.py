#!/usr/bin/env python3
"""Run random-target benchmarks for Alpha and Beta inverse-drafting algorithms."""

from __future__ import annotations

import argparse
import csv
import sys

from alpha_drafting import AlgorithmConfig, benchmark_random_targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Alpha and Beta algorithms on iid Bernoulli target drawdowns."
    )
    parser.add_argument("--trials", type=int, default=100, help="Number of random targets per size.")
    parser.add_argument("--sizes", nargs="+", default=["20x20"], help="Draft sizes as WIDTHxPICKS, e.g. 10x10 20x20.")
    parser.add_argument("--shafts", type=int, default=4, help="Shaft limit.")
    parser.add_argument("--treadles", type=int, default=6, help="Treadle limit.")
    parser.add_argument("--max-pressed", type=int, default=2, help="Maximum pressed treadles per pick for Alpha 3.")
    parser.add_argument("--probability", type=float, default=0.5, help="Probability that a target cell is 1.")
    parser.add_argument("--seed", type=int, default=1, help="Random seed.")
    parser.add_argument(
        "--algorithms",
        nargs="+",
        default=["alpha1", "alpha2", "alpha3"],
        choices=["alpha1", "alpha2", "alpha3", "beta1", "beta2", "beta3"],
        help="Algorithms to benchmark.",
    )
    parser.add_argument("--iteration-limit", type=int, default=10, help="Alternating minimization iteration limit.")
    parser.add_argument("--random-restarts", type=int, default=2, help="Additional random restarts per size.")
    parser.add_argument("--residual-restarts", type=int, default=2, help="Alpha 2 residual restarts.")
    parser.add_argument("--beam-width", type=int, default=4, help="Number of retained co-clustering states per size grid.")
    parser.add_argument("--alpha2-lambda", type=float, default=0.05, help="Initial Alpha 2 impact pressure.")
    parser.add_argument("--alpha3-lambda", type=float, default=0.03, help="Initial Alpha 3 impact pressure.")
    parser.add_argument("--alpha3-mu", type=float, default=0.05, help="Initial Alpha 3 redundancy pressure.")
    parser.add_argument("--beta2-lambda", type=float, default=0.05, help="Initial Beta 2 impact pressure during co-clustering.")
    parser.add_argument("--beta3-lambda", type=float, default=0.03, help="Initial Beta 3 impact pressure during repair.")
    parser.add_argument("--beta3-mu", type=float, default=0.05, help="Initial Beta 3 redundancy pressure.")
    parser.add_argument("--csv", action="store_true", help="Emit CSV instead of a Markdown table.")
    parser.add_argument("--no-progress", action="store_true", help="Disable the stderr progress bar.")
    parser.add_argument(
        "--jobs",
        type=_parse_jobs,
        default=1,
        help="Worker processes for benchmark runs. Use 1 for serial execution or 0 for all CPUs.",
    )
    args = parser.parse_args(argv)

    sizes = [_parse_size(value) for value in args.sizes]
    config = AlgorithmConfig(
        shafts=args.shafts,
        treadles=args.treadles,
        max_pressed=args.max_pressed,
        iteration_limit=args.iteration_limit,
        alpha2_lambda=args.alpha2_lambda,
        alpha3_lambda=args.alpha3_lambda,
        alpha3_mu=args.alpha3_mu,
        beta2_lambda=args.beta2_lambda,
        beta3_lambda=args.beta3_lambda,
        beta3_mu=args.beta3_mu,
        residual_restarts=args.residual_restarts,
        random_restarts=args.random_restarts,
        beam_width=args.beam_width,
        seed=args.seed,
    )
    progress = _ProgressBar(enabled=not args.no_progress)
    rows = benchmark_random_targets(
        algorithms=args.algorithms,
        sizes=sizes,
        config=config,
        trials=args.trials,
        probability=args.probability,
        seed=args.seed,
        progress_callback=progress.update,
        jobs=args.jobs,
    )

    if args.csv:
        _print_csv(rows)
    else:
        _print_markdown(rows)
    return 0


def _parse_size(value: str) -> tuple[int, int]:
    normalized = value.lower().replace(" ", "")
    if "x" not in normalized:
        raise argparse.ArgumentTypeError(f"size must look like WIDTHxPICKS: {value}")
    width_text, picks_text = normalized.split("x", 1)
    width = int(width_text)
    picks = int(picks_text)
    if width <= 0 or picks <= 0:
        raise argparse.ArgumentTypeError(f"size dimensions must be positive: {value}")
    return width, picks


def _parse_jobs(value: str) -> int:
    jobs = int(value)
    if jobs < 0:
        raise argparse.ArgumentTypeError("jobs must be nonnegative")
    return jobs


class _ProgressBar:
    def __init__(self, enabled: bool, width: int = 32) -> None:
        self.enabled = enabled
        self.width = width

    def update(self, completed: int, total: int, label: str) -> None:
        if not self.enabled:
            return

        ratio = completed / total if total else 1.0
        filled = min(self.width, max(0, int(self.width * ratio)))
        bar = "#" * filled + "-" * (self.width - filled)
        percent = ratio * 100
        clipped_label = label[:44]
        print(
            f"\r[{bar}] {completed}/{total} {percent:5.1f}% {clipped_label:<44}",
            end="",
            file=sys.stderr,
            flush=True,
        )
        if completed >= total:
            print(file=sys.stderr)


def _print_csv(rows: list[dict[str, float | int | str]]) -> None:
    fieldnames = [
        "algorithm",
        "width",
        "picks",
        "trials",
        "mean_normalized_error",
        "stdev_normalized_error",
        "mean_raw_error",
        "stdev_raw_error",
        "mean_runtime_ms",
        "mean_movement",
        "stdev_movement",
        "mean_movement_rate",
        "stdev_movement_rate",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(_printable_row(row))


def _print_markdown(rows: list[dict[str, float | int | str]]) -> None:
    print("| Algorithm | Size | Trials | Mean normalized error | Std normalized error | Mean raw error | Std raw error | Mean movement | Mean movement rate | Mean ms |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        printable = _printable_row(row)
        print(
            "| {algorithm} | {width}x{picks} | {trials} | {mean_normalized_error:.4f} | "
            "{stdev_normalized_error:.4f} | {mean_raw_error:.3f} | {stdev_raw_error:.3f} | "
            "{mean_movement} | {mean_movement_rate} | "
            "{mean_runtime_ms:.2f} |".format(**printable)
        )


def _printable_row(row: dict[str, float | int | str]) -> dict[str, float | int | str]:
    return {
        "algorithm": row["algorithm"],
        "width": row["width"],
        "picks": row["picks"],
        "trials": row["trials"],
        "mean_normalized_error": row["mean_error_rate"],
        "stdev_normalized_error": row["stdev_error_rate"],
        "mean_raw_error": row["mean_error"],
        "stdev_raw_error": row["stdev_error"],
        "mean_runtime_ms": row["mean_runtime_ms"],
        "mean_movement": _format_optional(row.get("mean_movement"), precision=3),
        "stdev_movement": _format_optional(row.get("stdev_movement"), precision=3),
        "mean_movement_rate": _format_optional(row.get("mean_movement_rate"), precision=4),
        "stdev_movement_rate": _format_optional(row.get("stdev_movement_rate"), precision=4),
    }


def _format_optional(value: object, precision: int) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
