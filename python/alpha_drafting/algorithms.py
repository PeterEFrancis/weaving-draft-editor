"""Implement the Alpha and Beta algorithms from the paper.

The code follows the paper's current convention:

* the final objective for every Alpha variant is raw Hamming error;
* Alpha 1 is the unweighted binary co-clustering baseline;
* Alpha 2 adds cell-impact search pressure;
* Alpha 3 adds draft-level redundancy search pressure using D = A B^T C.
* the final objective for every Beta variant is the open-boundary minimum
  movement cost Phi_beta.

Matrices are plain Python lists. Target and drawdown matrices are shaped
``picks x width``.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
import math
import os
import random
import statistics
import time
from typing import Callable, Sequence

Matrix = list[list[int]]
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class AlgorithmConfig:
    """Shared knobs for Alpha search.

    ``max_pressed`` is the maximum number of treadles pressed on a pick. Alpha 1
    and Alpha 2 use one treadle per reduced row state; Alpha 3 uses this limit
    during draft-level redundancy repair.
    """

    shafts: int
    treadles: int
    max_pressed: int = 2
    iteration_limit: int = 10
    alpha2_lambda: float = 0.05
    alpha3_lambda: float = 0.03
    alpha3_mu: float = 0.05
    beta2_lambda: float = 0.05
    beta3_lambda: float = 0.03
    beta3_mu: float = 0.05
    residual_restarts: int = 2
    random_restarts: int = 2
    beam_width: int = 4
    seed: int = 1


@dataclass
class DraftCandidate:
    """A completed draft candidate."""

    algorithm: str
    target: Matrix
    drawdown: Matrix
    threading: Matrix
    tieup: Matrix
    treadling: Matrix
    redundancy_matrix: Matrix
    hamming_error: int
    redundancy: int
    impact_residual: float
    movement_cost: int | None = None
    row_assignments: list[int] = field(default_factory=list)
    column_assignments: list[int] = field(default_factory=list)
    reduced_tieup: Matrix = field(default_factory=list)

    @property
    def picks(self) -> int:
        return len(self.target)

    @property
    def width(self) -> int:
        return len(self.target[0]) if self.target else 0

    @property
    def hamming_rate(self) -> float:
        cells = self.picks * self.width
        return self.hamming_error / cells if cells else 0.0

    @property
    def movement_rate(self) -> float | None:
        cells = self.picks * self.width
        if self.movement_cost is None:
            return None
        return self.movement_cost / cells if cells else 0.0

    @property
    def max_pressed_used(self) -> int:
        return max((sum(row) for row in self.treadling), default=0)


@dataclass
class _State:
    row_assignments: list[int]
    column_assignments: list[int]
    tieup: Matrix
    hamming_error: int
    impact_residual: float


@dataclass(frozen=True)
class _MovementPlan:
    cost: int
    moves: list[tuple[tuple[int, int], tuple[int, int], int]]
    exits: list[tuple[tuple[int, int], int]]
    entries: list[tuple[tuple[int, int], int]]


@dataclass(frozen=True)
class _BenchmarkJob:
    algorithm: str
    width: int
    picks: int
    trial: int
    trials: int
    probability: float
    target_seed: int
    run_seed: int
    config: AlgorithmConfig


@dataclass(frozen=True)
class _BenchmarkRunResult:
    algorithm: str
    width: int
    picks: int
    trial: int
    label: str
    hamming_error: int
    hamming_rate: float
    movement_cost: int | None
    movement_rate: float | None
    elapsed_ms: float


def random_target(width: int, picks: int, probability: float = 0.5, seed: int | None = None) -> Matrix:
    """Create a random ``picks x width`` binary target."""

    rng = random.Random(seed)
    return [
        [1 if rng.random() < probability else 0 for _ in range(width)]
        for _ in range(picks)
    ]


def benchmark_random_targets(
    algorithms: Sequence[str],
    sizes: Sequence[tuple[int, int]],
    config: AlgorithmConfig,
    trials: int,
    probability: float = 0.5,
    seed: int = 1,
    progress_callback: ProgressCallback | None = None,
    jobs: int = 1,
) -> list[dict[str, float | int | str]]:
    """Run Alpha benchmarks on random iid targets.

    Returns one row per ``(algorithm, size)`` with raw Hamming error and
    normalized Hamming error rate statistics.
    """

    algorithm_names = list(algorithms)
    draft_sizes = list(sizes)
    runners = _algorithm_runners()
    unknown = [name for name in algorithm_names if name not in runners]
    if unknown:
        raise ValueError(f"unknown algorithm(s): {', '.join(unknown)}")
    if trials < 1:
        raise ValueError("trials must be positive")
    if not algorithm_names or not draft_sizes:
        return []

    benchmark_jobs = _make_benchmark_jobs(algorithm_names, draft_sizes, config, trials, probability, seed)
    worker_count = min(_resolve_worker_count(jobs), len(benchmark_jobs))
    if worker_count == 1:
        run_results = _run_benchmark_jobs_serial(benchmark_jobs, progress_callback)
    else:
        run_results = _run_benchmark_jobs_parallel(benchmark_jobs, worker_count, progress_callback)

    return _summarize_benchmark_results(run_results, algorithm_names, draft_sizes, trials)


def _algorithm_runners() -> dict[str, Callable[[Matrix, AlgorithmConfig], DraftCandidate]]:
    return {
        "alpha1": run_alpha1,
        "alpha2": run_alpha2,
        "alpha3": run_alpha3,
        "beta1": run_beta1,
        "beta2": run_beta2,
        "beta3": run_beta3,
    }


def _make_benchmark_jobs(
    algorithms: Sequence[str],
    sizes: Sequence[tuple[int, int]],
    config: AlgorithmConfig,
    trials: int,
    probability: float,
    seed: int,
) -> list[_BenchmarkJob]:
    benchmark_jobs: list[_BenchmarkJob] = []
    for width, picks in sizes:
        for trial in range(trials):
            target_seed = seed + trial + width * 100_003 + picks * 1_009
            run_seed = config.seed + trial * 101
            for algorithm in algorithms:
                benchmark_jobs.append(
                    _BenchmarkJob(
                        algorithm=algorithm,
                        width=width,
                        picks=picks,
                        trial=trial,
                        trials=trials,
                        probability=probability,
                        target_seed=target_seed,
                        run_seed=run_seed,
                        config=config,
                    )
                )
    return benchmark_jobs


def _resolve_worker_count(jobs: int) -> int:
    if jobs < 0:
        raise ValueError("jobs must be nonnegative")
    if jobs == 0:
        return os.cpu_count() or 1
    return jobs


def _run_benchmark_jobs_serial(
    benchmark_jobs: Sequence[_BenchmarkJob],
    progress_callback: ProgressCallback | None,
) -> list[_BenchmarkRunResult]:
    total_runs = len(benchmark_jobs)
    run_results: list[_BenchmarkRunResult] = []
    for completed_runs, job in enumerate(benchmark_jobs, start=1):
        result = _run_benchmark_job(job)
        run_results.append(result)
        if progress_callback is not None:
            progress_callback(completed_runs, total_runs, result.label)
    return run_results


def _run_benchmark_jobs_parallel(
    benchmark_jobs: Sequence[_BenchmarkJob],
    worker_count: int,
    progress_callback: ProgressCallback | None,
) -> list[_BenchmarkRunResult]:
    total_runs = len(benchmark_jobs)
    completed_runs = 0
    run_results: list[_BenchmarkRunResult] = []
    chunk_size = _benchmark_chunk_size(total_runs, worker_count)
    chunks = list(_chunked(benchmark_jobs, chunk_size))

    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_run_benchmark_job_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            chunk_results = future.result()
            run_results.extend(chunk_results)
            if progress_callback is not None:
                for result in chunk_results:
                    completed_runs += 1
                    progress_callback(completed_runs, total_runs, result.label)

    return run_results


def _benchmark_chunk_size(total_runs: int, worker_count: int) -> int:
    return max(1, min(16, math.ceil(total_runs / (worker_count * 32))))


def _chunked(items: Sequence[_BenchmarkJob], chunk_size: int) -> list[list[_BenchmarkJob]]:
    return [list(items[index:index + chunk_size]) for index in range(0, len(items), chunk_size)]


def _run_benchmark_job_chunk(benchmark_jobs: Sequence[_BenchmarkJob]) -> list[_BenchmarkRunResult]:
    return [_run_benchmark_job(job) for job in benchmark_jobs]


def _run_benchmark_job(job: _BenchmarkJob) -> _BenchmarkRunResult:
    target = random_target(job.width, job.picks, job.probability, job.target_seed)
    run_config = AlgorithmConfig(
        shafts=job.config.shafts,
        treadles=job.config.treadles,
        max_pressed=job.config.max_pressed,
        iteration_limit=job.config.iteration_limit,
        alpha2_lambda=job.config.alpha2_lambda,
        alpha3_lambda=job.config.alpha3_lambda,
        alpha3_mu=job.config.alpha3_mu,
        beta2_lambda=job.config.beta2_lambda,
        beta3_lambda=job.config.beta3_lambda,
        beta3_mu=job.config.beta3_mu,
        residual_restarts=job.config.residual_restarts,
        random_restarts=job.config.random_restarts,
        beam_width=job.config.beam_width,
        seed=job.run_seed,
    )
    started_at = time.perf_counter()
    candidate = _algorithm_runners()[job.algorithm](target, run_config)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    return _BenchmarkRunResult(
        algorithm=job.algorithm,
        width=job.width,
        picks=job.picks,
        trial=job.trial,
        label=f"{job.algorithm} {job.width}x{job.picks} trial {job.trial + 1}/{job.trials}",
        hamming_error=candidate.hamming_error,
        hamming_rate=candidate.hamming_rate,
        movement_cost=candidate.movement_cost,
        movement_rate=candidate.movement_rate,
        elapsed_ms=elapsed_ms,
    )


def _summarize_benchmark_results(
    run_results: Sequence[_BenchmarkRunResult],
    algorithms: Sequence[str],
    sizes: Sequence[tuple[int, int]],
    trials: int,
) -> list[dict[str, float | int | str]]:
    runs_by_key: dict[tuple[int, int, str], list[_BenchmarkRunResult]] = {}
    for result in run_results:
        runs_by_key.setdefault((result.width, result.picks, result.algorithm), []).append(result)

    rows: list[dict[str, float | int | str]] = []
    for width, picks in sizes:
        for algorithm in algorithms:
            runs = sorted(runs_by_key[(width, picks, algorithm)], key=lambda result: result.trial)
            errors = [result.hamming_error for result in runs]
            rates = [result.hamming_rate for result in runs]
            movement_costs = [result.movement_cost for result in runs if result.movement_cost is not None]
            movement_rates = [result.movement_rate for result in runs if result.movement_rate is not None]
            runtimes = [result.elapsed_ms for result in runs]
            rows.append(
                {
                    "algorithm": algorithm,
                    "width": width,
                    "picks": picks,
                    "trials": trials,
                    "mean_error": statistics.fmean(errors),
                    "stdev_error": statistics.stdev(errors) if len(errors) > 1 else 0.0,
                    "mean_error_rate": statistics.fmean(rates),
                    "stdev_error_rate": statistics.stdev(rates) if len(rates) > 1 else 0.0,
                    "mean_movement": statistics.fmean(movement_costs) if len(movement_costs) == len(runs) else None,
                    "stdev_movement": statistics.stdev(movement_costs) if len(movement_costs) > 1 and len(movement_costs) == len(runs) else None,
                    "mean_movement_rate": statistics.fmean(movement_rates) if len(movement_rates) == len(runs) else None,
                    "stdev_movement_rate": statistics.stdev(movement_rates) if len(movement_rates) > 1 and len(movement_rates) == len(runs) else None,
                    "mean_runtime_ms": statistics.fmean(runtimes),
                }
            )
    return rows


def run_alpha1(target: Matrix, config: AlgorithmConfig) -> DraftCandidate:
    """Run Alpha 1: unweighted finite binary co-clustering."""

    impact = compute_impact_scores(target)
    states = _collect_coclustering_states(
        target=target,
        config=config,
        algorithm="alpha1",
        impact=None,
        lambda0=0.0,
        include_impact_initializers=False,
    )
    return min(
        (_candidate_from_state("alpha1", target, state, impact) for state in states),
        key=_candidate_key,
    )


def run_alpha2(target: Matrix, config: AlgorithmConfig) -> DraftCandidate:
    """Run Alpha 2: co-clustering with cell-impact search pressure."""

    impact = compute_impact_scores(target)
    states = _collect_coclustering_states(
        target=target,
        config=config,
        algorithm="alpha2",
        impact=impact,
        lambda0=config.alpha2_lambda,
        include_impact_initializers=True,
    )
    states.extend(_residual_restarts(target, config, states, impact, config.alpha2_lambda, "alpha2"))
    return min(
        (_candidate_from_state("alpha2", target, state, impact) for state in states),
        key=_candidate_key,
    )


def run_alpha3(target: Matrix, config: AlgorithmConfig) -> DraftCandidate:
    """Run Alpha 3: impact-guided search plus redundancy-guided draft repair."""

    impact = compute_impact_scores(target)
    base = run_alpha2(target, config)
    repaired = _redundancy_guided_repair(base, config, impact)
    return min([base, repaired], key=_candidate_key)


def run_beta1(target: Matrix, config: AlgorithmConfig) -> DraftCandidate:
    """Run Beta 1: Alpha-style co-clustering ranked by Phi_beta."""

    impact = compute_impact_scores(target)
    states = _collect_coclustering_states(
        target=target,
        config=config,
        algorithm="beta1",
        impact=None,
        lambda0=0.0,
        include_impact_initializers=False,
    )
    return min(
        (_beta_candidate_from_state("beta1", target, state, impact) for state in states),
        key=_beta_candidate_key,
    )


def run_beta2(target: Matrix, config: AlgorithmConfig) -> DraftCandidate:
    """Run Beta 2: movement-ranked co-clustering with movement residual restarts."""

    impact = compute_impact_scores(target)
    states = _collect_coclustering_states(
        target=target,
        config=config,
        algorithm="beta2",
        impact=impact,
        lambda0=config.beta2_lambda,
        include_impact_initializers=True,
    )
    states.extend(_movement_residual_restarts(target, config, states, impact, config.beta2_lambda))
    return min(
        (_beta_candidate_from_state("beta2", target, state, impact) for state in states),
        key=_beta_candidate_key,
    )


def run_beta3(target: Matrix, config: AlgorithmConfig) -> DraftCandidate:
    """Run Beta 3: movement objective plus draft-level redundancy repair."""

    impact = compute_impact_scores(target)
    base = run_beta2(target, config)
    repaired = _movement_guided_repair(base, config, impact)
    return min([base, repaired], key=_beta_candidate_key)


def phi_beta(drawdown: Matrix, target: Matrix) -> int:
    """Return the open-boundary minimum movement cost Phi_beta.

    A black cell can move to an adjacent horizontal or vertical cell at unit
    cost. It can also leave through the nearest edge, and a new black cell can
    enter from an edge. The implementation reduces the problem to an assignment
    between surplus and missing black cells with edge-entry/exit dummy choices.
    """

    return _compute_movement_plan(drawdown, target).cost


def compute_impact_scores(matrix: Matrix) -> list[list[float]]:
    """Compute the Alpha 2 cell-impact scores eta_ij from the paper."""

    picks = len(matrix)
    width = len(matrix[0]) if picks else 0
    if not picks or not width:
        return [[1.0 for _ in range(width)] for _ in range(picks)]

    row_keys = [_binary_key(row) for row in matrix]
    column_keys = [
        "".join("1" if matrix[row][column] else "0" for row in range(picks))
        for column in range(width)
    ]
    row_counts = Counter(row_keys)
    column_counts = Counter(column_keys)
    scale = max(picks, width, 1)

    impact: list[list[float]] = []
    for row in range(picks):
        impact_row: list[float] = []
        for column in range(width):
            flipped_row_count = row_counts.get(_flip_key(row_keys[row], column), 0)
            flipped_column_count = column_counts.get(_flip_key(column_keys[column], row), 0)
            merge_pressure = max(flipped_row_count, flipped_column_count)
            sigma = int(row_counts[row_keys[row]] == 1) + int(column_counts[column_keys[column]] == 1)
            edge_count = 0
            value = matrix[row][column]
            for next_row, next_column in (
                (row - 1, column),
                (row + 1, column),
                (row, column - 1),
                (row, column + 1),
            ):
                if 0 <= next_row < picks and 0 <= next_column < width:
                    edge_count += int(matrix[next_row][next_column] != value)

            impact_row.append(
                min(
                    6.0,
                    1.0
                    + math.log2(1 + merge_pressure)
                    + 0.35 * sigma
                    + 0.08 * edge_count
                    + merge_pressure / scale,
                )
            )
        impact.append(impact_row)
    return impact


def _collect_coclustering_states(
    target: Matrix,
    config: AlgorithmConfig,
    algorithm: str,
    impact: list[list[float]] | None,
    lambda0: float,
    include_impact_initializers: bool,
) -> list[_State]:
    picks, width = _shape(target)
    max_shafts = max(1, min(config.shafts, width))
    max_treadles = max(1, min(config.treadles, picks))
    states: list[_State] = []

    base_initializers = [
        ("farthest", "farthest", 11),
        ("density", "density", 23),
        ("random", "random", 31),
        ("random", "farthest", 37),
        ("farthest", "random", 41),
    ]
    impact_initializers = [
        ("impact-farthest", "impact-farthest", 53),
        ("impact-farthest", "farthest", 59),
        ("farthest", "impact-farthest", 61),
    ]
    random_initializers = [
        ("random", "random", 101 + index * 17)
        for index in range(max(0, config.random_restarts))
    ]
    initializers = base_initializers + random_initializers
    if include_impact_initializers:
        initializers += impact_initializers

    for shaft_count in range(1, max_shafts + 1):
        for treadle_count in range(1, max_treadles + 1):
            for column_strategy, row_strategy, seed_offset in initializers:
                state = _run_coclustering(
                    target=target,
                    shaft_count=shaft_count,
                    treadle_count=treadle_count,
                    column_strategy=column_strategy,
                    row_strategy=row_strategy,
                    seed=config.seed + seed_offset,
                    iteration_limit=config.iteration_limit,
                    impact=impact,
                    lambda0=lambda0,
                )
                states.append(state)

    return _dedupe_states(states, beam_width=max(config.beam_width, 1) * max_shafts * max_treadles)


def _run_coclustering(
    target: Matrix,
    shaft_count: int,
    treadle_count: int,
    column_strategy: str,
    row_strategy: str,
    seed: int,
    iteration_limit: int,
    impact: list[list[float]] | None,
    lambda0: float,
    row_assignments: list[int] | None = None,
    column_assignments: list[int] | None = None,
) -> _State:
    column_vectors = _column_vectors(target)
    row_vectors = [row[:] for row in target]
    rng = random.Random(seed)

    use_column_impact = column_strategy.startswith("impact-") and impact is not None
    use_row_impact = row_strategy.startswith("impact-") and impact is not None
    normalized_column_strategy = column_strategy.removeprefix("impact-")
    normalized_row_strategy = row_strategy.removeprefix("impact-")
    if column_assignments is None:
        column_assignments = _initial_assignments(
            column_vectors,
            shaft_count,
            normalized_column_strategy,
            rng,
            _column_weight_vectors(impact) if use_column_impact else None,
        )
    if row_assignments is None:
        row_assignments = _initial_assignments(
            row_vectors,
            treadle_count,
            normalized_row_strategy,
            rng,
            _row_weight_vectors(impact) if use_row_impact else None,
        )

    signature = ""
    tieup = _tieup_update(target, row_assignments, column_assignments, treadle_count, shaft_count, impact, lambda0)
    for iteration in range(max(1, iteration_limit)):
        lambda_value = _annealed(lambda0, iteration, iteration_limit)
        tieup = _tieup_update(target, row_assignments, column_assignments, treadle_count, shaft_count, impact, lambda_value)
        row_assignments = _row_update(target, tieup, column_assignments, treadle_count, row_assignments, impact, lambda_value)
        tieup = _tieup_update(target, row_assignments, column_assignments, treadle_count, shaft_count, impact, lambda_value)
        column_assignments = _column_update(target, tieup, row_assignments, shaft_count, column_assignments, impact, lambda_value)
        tieup = _tieup_update(target, row_assignments, column_assignments, treadle_count, shaft_count, impact, lambda_value)

        next_signature = _state_signature(row_assignments, column_assignments, tieup)
        if next_signature == signature:
            break
        signature = next_signature

    tieup = _tieup_update(target, row_assignments, column_assignments, treadle_count, shaft_count, impact, 0.0)
    drawdown = _drawdown_from_assignments(row_assignments, column_assignments, tieup)
    return _State(
        row_assignments=row_assignments,
        column_assignments=column_assignments,
        tieup=tieup,
        hamming_error=count_mismatches(target, drawdown),
        impact_residual=_impact_residual(target, drawdown, impact),
    )


def _residual_restarts(
    target: Matrix,
    config: AlgorithmConfig,
    states: list[_State],
    impact: list[list[float]],
    lambda0: float,
    algorithm: str,
) -> list[_State]:
    if not states or config.residual_restarts <= 0:
        return []

    best_states = sorted(states, key=lambda state: (state.hamming_error, state.impact_residual))[: config.residual_restarts]
    restarted: list[_State] = []
    for index, state in enumerate(best_states):
        drawdown = _drawdown_from_assignments(state.row_assignments, state.column_assignments, state.tieup)
        row_scores = [
            sum(impact[row][column] for column in range(len(target[row])) if target[row][column] != drawdown[row][column])
            for row in range(len(target))
        ]
        column_scores = [
            sum(impact[row][column] for row in range(len(target)) if target[row][column] != drawdown[row][column])
            for column in range(len(target[0]))
        ]
        row_assignments = state.row_assignments[:]
        column_assignments = state.column_assignments[:]
        rng = random.Random(config.seed + 7_919 + index)

        row_group_count = max(row_assignments) + 1
        column_group_count = max(column_assignments) + 1
        for row in _top_indices(row_scores, max(1, len(row_scores) // 5)):
            row_assignments[row] = rng.randrange(row_group_count)
        for column in _top_indices(column_scores, max(1, len(column_scores) // 5)):
            column_assignments[column] = rng.randrange(column_group_count)

        restarted.append(
            _run_coclustering(
                target=target,
                shaft_count=column_group_count,
                treadle_count=row_group_count,
                column_strategy="farthest",
                row_strategy="farthest",
                seed=config.seed + 8_123 + index,
                iteration_limit=config.iteration_limit,
                impact=impact,
                lambda0=lambda0,
                row_assignments=_rebalance(row_assignments, row_group_count),
                column_assignments=_rebalance(column_assignments, column_group_count),
            )
        )

    return restarted


def _candidate_from_state(algorithm: str, target: Matrix, state: _State, impact: list[list[float]]) -> DraftCandidate:
    row_assignments, row_map = _canonicalize_assignments(state.row_assignments)
    column_assignments, column_map = _canonicalize_assignments(state.column_assignments)
    treadles = len(row_map)
    shafts = len(column_map)
    tieup = [[0 for _ in range(shafts)] for _ in range(treadles)]
    for old_row, new_row in row_map.items():
        for old_column, new_column in column_map.items():
            tieup[new_row][new_column] = state.tieup[old_row][old_column]

    picks, width = _shape(target)
    threading = [[0 for _ in range(width)] for _ in range(shafts)]
    for column, shaft in enumerate(column_assignments):
        threading[shaft][column] = 1
    treadling = [[0 for _ in range(treadles)] for _ in range(picks)]
    for row, treadle in enumerate(row_assignments):
        treadling[row][treadle] = 1

    redundancy_matrix = _redundancy_matrix(threading, tieup, treadling)
    drawdown = _threshold(redundancy_matrix)
    return DraftCandidate(
        algorithm=algorithm,
        target=target,
        drawdown=drawdown,
        threading=threading,
        tieup=tieup,
        treadling=treadling,
        redundancy_matrix=redundancy_matrix,
        hamming_error=count_mismatches(target, drawdown),
        redundancy=_redundancy_score(redundancy_matrix, target),
        impact_residual=_impact_residual(target, drawdown, impact),
        row_assignments=row_assignments,
        column_assignments=column_assignments,
        reduced_tieup=tieup,
    )


def _beta_candidate_from_state(algorithm: str, target: Matrix, state: _State, impact: list[list[float]]) -> DraftCandidate:
    candidate = _candidate_from_state(algorithm, target, state, impact)
    candidate.movement_cost = phi_beta(candidate.drawdown, target)
    return candidate


def _movement_residual_restarts(
    target: Matrix,
    config: AlgorithmConfig,
    states: list[_State],
    impact: list[list[float]],
    lambda0: float,
) -> list[_State]:
    if not states or config.residual_restarts <= 0:
        return []

    candidates = [_beta_candidate_from_state("beta2", target, state, impact) for state in states]
    best_candidates = sorted(candidates, key=_beta_candidate_key)[: config.residual_restarts]
    restarted: list[_State] = []

    for index, candidate in enumerate(best_candidates):
        plan = _compute_movement_plan(candidate.drawdown, target)
        row_scores, column_scores = _movement_residual_scores(target, plan)
        row_assignments = candidate.row_assignments[:]
        column_assignments = candidate.column_assignments[:]
        rng = random.Random(config.seed + 12_019 + index)

        row_group_count = max(row_assignments) + 1 if row_assignments else 1
        column_group_count = max(column_assignments) + 1 if column_assignments else 1
        for row in _top_indices(row_scores, max(1, len(row_scores) // 5)):
            row_assignments[row] = rng.randrange(row_group_count)
        for column in _top_indices(column_scores, max(1, len(column_scores) // 5)):
            column_assignments[column] = rng.randrange(column_group_count)

        restarted.append(
            _run_coclustering(
                target=target,
                shaft_count=column_group_count,
                treadle_count=row_group_count,
                column_strategy="impact-farthest",
                row_strategy="impact-farthest",
                seed=config.seed + 13_027 + index,
                iteration_limit=config.iteration_limit,
                impact=impact,
                lambda0=lambda0,
                row_assignments=_rebalance(row_assignments, row_group_count),
                column_assignments=_rebalance(column_assignments, column_group_count),
            )
        )

    return restarted


def _movement_residual_scores(target: Matrix, plan: _MovementPlan) -> tuple[list[float], list[float]]:
    picks, width = _shape(target)
    row_scores = [0.0 for _ in range(picks)]
    column_scores = [0.0 for _ in range(width)]

    def add(cell: tuple[int, int], cost: int) -> None:
        row, column = cell
        row_scores[row] += cost
        column_scores[column] += cost

    for source, target_cell, cost in plan.moves:
        add(source, max(1, cost))
        add(target_cell, max(1, cost))
    for source, cost in plan.exits:
        add(source, cost)
    for target_cell, cost in plan.entries:
        add(target_cell, cost)
    return row_scores, column_scores


def _redundancy_guided_repair(candidate: DraftCandidate, config: AlgorithmConfig, impact: list[list[float]]) -> DraftCandidate:
    threading = [row[:] for row in candidate.threading]
    tieup = [row[:] for row in candidate.tieup]
    treadling = [row[:] for row in candidate.treadling]
    if not tieup or not tieup[0]:
        return candidate

    subsets = _allowed_treadle_subsets(len(tieup), max(1, config.max_pressed))
    iteration_limit = max(1, config.iteration_limit)
    best = _draft_candidate_from_matrices("alpha3", candidate.target, threading, tieup, treadling, impact)

    for iteration in range(iteration_limit):
        lambda_value = _annealed(config.alpha3_lambda, iteration, iteration_limit)
        mu_value = _annealed(config.alpha3_mu, iteration, iteration_limit)

        treadling = _update_treadling_by_redundancy(candidate.target, threading, tieup, treadling, subsets, impact, lambda_value, mu_value)
        tieup = _update_tieup_by_redundancy(candidate.target, threading, tieup, treadling, impact, lambda_value, mu_value)
        threading = _update_threading_by_redundancy(candidate.target, threading, tieup, treadling, impact, lambda_value, mu_value)

        current = _draft_candidate_from_matrices("alpha3", candidate.target, threading, tieup, treadling, impact)
        if _candidate_key(current) < _candidate_key(best):
            best = current

    return best


def _movement_guided_repair(candidate: DraftCandidate, config: AlgorithmConfig, impact: list[list[float]]) -> DraftCandidate:
    threading = [row[:] for row in candidate.threading]
    tieup = [row[:] for row in candidate.tieup]
    treadling = [row[:] for row in candidate.treadling]
    if not tieup or not tieup[0]:
        return candidate

    subsets = _allowed_treadle_subsets(len(tieup), max(1, config.max_pressed))
    iteration_limit = max(1, config.iteration_limit)
    best = _beta_draft_candidate_from_matrices("beta3", candidate.target, threading, tieup, treadling, impact)

    for iteration in range(iteration_limit):
        lambda_value = _annealed(config.beta3_lambda, iteration, iteration_limit)
        mu_value = _annealed(config.beta3_mu, iteration, iteration_limit)

        treadling = _update_treadling_by_movement(candidate.target, threading, tieup, treadling, subsets, impact, lambda_value, mu_value)
        tieup = _update_tieup_by_movement(candidate.target, threading, tieup, treadling, impact, lambda_value, mu_value)
        threading = _update_threading_by_movement(candidate.target, threading, tieup, treadling, impact, lambda_value, mu_value)

        current = _beta_draft_candidate_from_matrices("beta3", candidate.target, threading, tieup, treadling, impact)
        if _beta_candidate_key(current) < _beta_candidate_key(best):
            best = current

    return best


def _update_treadling_by_redundancy(
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    subsets: list[tuple[int, ...]],
    impact: list[list[float]],
    lambda_value: float,
    mu_value: float,
) -> Matrix:
    next_treadling = [row[:] for row in treadling]
    for row in range(len(target)):
        best_row = next_treadling[row][:]
        best_score = math.inf
        for subset in subsets:
            trial_row = [0 for _ in range(len(tieup))]
            for treadle in subset:
                trial_row[treadle] = 1
            next_treadling[row] = trial_row
            trial = _draft_candidate_from_matrices("alpha3", target, threading, tieup, next_treadling, impact)
            score = _draft_search_score(trial, lambda_value, mu_value)
            if score < best_score:
                best_score = score
                best_row = trial_row
        next_treadling[row] = best_row
    return next_treadling


def _update_treadling_by_movement(
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    subsets: list[tuple[int, ...]],
    impact: list[list[float]],
    lambda_value: float,
    mu_value: float,
) -> Matrix:
    next_treadling = [row[:] for row in treadling]
    for row in range(len(target)):
        best_row = next_treadling[row][:]
        best_score = math.inf
        for subset in subsets:
            trial_row = [0 for _ in range(len(tieup))]
            for treadle in subset:
                trial_row[treadle] = 1
            next_treadling[row] = trial_row
            trial = _beta_draft_candidate_from_matrices("beta3", target, threading, tieup, next_treadling, impact)
            score = _beta_draft_search_score(trial, lambda_value, mu_value)
            if score < best_score:
                best_score = score
                best_row = trial_row
        next_treadling[row] = best_row
    return next_treadling


def _update_tieup_by_redundancy(
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    impact: list[list[float]],
    lambda_value: float,
    mu_value: float,
) -> Matrix:
    next_tieup = [row[:] for row in tieup]
    for treadle in range(len(next_tieup)):
        for shaft in range(len(next_tieup[treadle])):
            best_value = next_tieup[treadle][shaft]
            best_score = math.inf
            for value in (0, 1):
                next_tieup[treadle][shaft] = value
                trial = _draft_candidate_from_matrices("alpha3", target, threading, next_tieup, treadling, impact)
                score = _draft_search_score(trial, lambda_value, mu_value)
                if score < best_score:
                    best_score = score
                    best_value = value
            next_tieup[treadle][shaft] = best_value
    return next_tieup


def _update_tieup_by_movement(
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    impact: list[list[float]],
    lambda_value: float,
    mu_value: float,
) -> Matrix:
    next_tieup = [row[:] for row in tieup]
    for treadle in range(len(next_tieup)):
        for shaft in range(len(next_tieup[treadle])):
            best_value = next_tieup[treadle][shaft]
            best_score = math.inf
            for value in (0, 1):
                next_tieup[treadle][shaft] = value
                trial = _beta_draft_candidate_from_matrices("beta3", target, threading, next_tieup, treadling, impact)
                score = _beta_draft_search_score(trial, lambda_value, mu_value)
                if score < best_score:
                    best_score = score
                    best_value = value
            next_tieup[treadle][shaft] = best_value
    return next_tieup


def _update_threading_by_redundancy(
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    impact: list[list[float]],
    lambda_value: float,
    mu_value: float,
) -> Matrix:
    shaft_count = len(threading)
    width = len(threading[0]) if threading else 0
    next_threading = [row[:] for row in threading]
    for column in range(width):
        best_shaft = _column_shaft(next_threading, column)
        best_score = math.inf
        for shaft in range(shaft_count):
            for candidate_shaft in range(shaft_count):
                next_threading[candidate_shaft][column] = 1 if candidate_shaft == shaft else 0
            trial = _draft_candidate_from_matrices("alpha3", target, next_threading, tieup, treadling, impact)
            score = _draft_search_score(trial, lambda_value, mu_value)
            if score < best_score:
                best_score = score
                best_shaft = shaft
        for candidate_shaft in range(shaft_count):
            next_threading[candidate_shaft][column] = 1 if candidate_shaft == best_shaft else 0
    return next_threading


def _update_threading_by_movement(
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    impact: list[list[float]],
    lambda_value: float,
    mu_value: float,
) -> Matrix:
    shaft_count = len(threading)
    width = len(threading[0]) if threading else 0
    next_threading = [row[:] for row in threading]
    for column in range(width):
        best_shaft = _column_shaft(next_threading, column)
        best_score = math.inf
        for shaft in range(shaft_count):
            for candidate_shaft in range(shaft_count):
                next_threading[candidate_shaft][column] = 1 if candidate_shaft == shaft else 0
            trial = _beta_draft_candidate_from_matrices("beta3", target, next_threading, tieup, treadling, impact)
            score = _beta_draft_search_score(trial, lambda_value, mu_value)
            if score < best_score:
                best_score = score
                best_shaft = shaft
        for candidate_shaft in range(shaft_count):
            next_threading[candidate_shaft][column] = 1 if candidate_shaft == best_shaft else 0
    return next_threading


def _draft_candidate_from_matrices(
    algorithm: str,
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    impact: list[list[float]],
) -> DraftCandidate:
    redundancy_matrix = _redundancy_matrix(threading, tieup, treadling)
    drawdown = _threshold(redundancy_matrix)
    return DraftCandidate(
        algorithm=algorithm,
        target=target,
        drawdown=drawdown,
        threading=[row[:] for row in threading],
        tieup=[row[:] for row in tieup],
        treadling=[row[:] for row in treadling],
        redundancy_matrix=redundancy_matrix,
        hamming_error=count_mismatches(target, drawdown),
        redundancy=_redundancy_score(redundancy_matrix, target),
        impact_residual=_impact_residual(target, drawdown, impact),
    )


def _beta_draft_candidate_from_matrices(
    algorithm: str,
    target: Matrix,
    threading: Matrix,
    tieup: Matrix,
    treadling: Matrix,
    impact: list[list[float]],
) -> DraftCandidate:
    candidate = _draft_candidate_from_matrices(algorithm, target, threading, tieup, treadling, impact)
    candidate.movement_cost = phi_beta(candidate.drawdown, target)
    return candidate


def count_mismatches(left: Matrix, right: Matrix) -> int:
    return sum(
        1
        for row in range(len(left))
        for column in range(len(left[row]))
        if int(left[row][column]) != int(right[row][column])
    )


def _compute_movement_plan(drawdown: Matrix, target: Matrix) -> _MovementPlan:
    _validate_same_shape(drawdown, target)
    picks, width = _shape(target)
    surplus: list[tuple[int, int]] = []
    missing: list[tuple[int, int]] = []

    for row in range(picks):
        for column in range(width):
            source_value = int(drawdown[row][column])
            target_value = int(target[row][column])
            if source_value and not target_value:
                surplus.append((row, column))
            elif target_value and not source_value:
                missing.append((row, column))

    if not surplus and not missing:
        return _MovementPlan(cost=0, moves=[], exits=[], entries=[])
    if not surplus:
        entries = [(cell, _edge_cost(cell, picks, width)) for cell in missing]
        return _MovementPlan(cost=sum(cost for _, cost in entries), moves=[], exits=[], entries=entries)
    if not missing:
        exits = [(cell, _edge_cost(cell, picks, width)) for cell in surplus]
        return _MovementPlan(cost=sum(cost for _, cost in exits), moves=[], exits=exits, entries=[])

    source_count = len(surplus)
    target_count = len(missing)
    dimension = max(source_count, target_count)
    cost_matrix: list[list[int]] = []
    for row_index in range(dimension):
        row_costs: list[int] = []
        for column_index in range(dimension):
            if row_index < source_count and column_index < target_count:
                source = surplus[row_index]
                target_cell = missing[column_index]
                row_costs.append(_open_boundary_distance(source, target_cell, picks, width))
            elif row_index < source_count:
                row_costs.append(_edge_cost(surplus[row_index], picks, width))
            elif column_index < target_count:
                row_costs.append(_edge_cost(missing[column_index], picks, width))
            else:
                row_costs.append(0)
        cost_matrix.append(row_costs)

    assignment = _hungarian_minimize(cost_matrix)
    moves: list[tuple[tuple[int, int], tuple[int, int], int]] = []
    exits: list[tuple[tuple[int, int], int]] = []
    entries: list[tuple[tuple[int, int], int]] = []
    total_cost = 0

    for row_index, column_index in enumerate(assignment):
        if row_index < source_count and column_index < target_count:
            source = surplus[row_index]
            target_cell = missing[column_index]
            direct_cost = _manhattan(source, target_cell)
            boundary_cost = _edge_cost(source, picks, width) + _edge_cost(target_cell, picks, width)
            if direct_cost <= boundary_cost:
                moves.append((source, target_cell, direct_cost))
                total_cost += direct_cost
            else:
                source_exit = _edge_cost(source, picks, width)
                target_entry = _edge_cost(target_cell, picks, width)
                exits.append((source, source_exit))
                entries.append((target_cell, target_entry))
                total_cost += source_exit + target_entry
        elif row_index < source_count:
            source = surplus[row_index]
            source_exit = _edge_cost(source, picks, width)
            exits.append((source, source_exit))
            total_cost += source_exit
        elif column_index < target_count:
            target_cell = missing[column_index]
            target_entry = _edge_cost(target_cell, picks, width)
            entries.append((target_cell, target_entry))
            total_cost += target_entry

    return _MovementPlan(cost=total_cost, moves=moves, exits=exits, entries=entries)


def _validate_same_shape(left: Matrix, right: Matrix) -> None:
    if len(left) != len(right):
        raise ValueError("matrices must have the same number of rows")
    for row, left_row in enumerate(left):
        if row >= len(right) or len(left_row) != len(right[row]):
            raise ValueError("matrices must have the same shape")


def _open_boundary_distance(source: tuple[int, int], target: tuple[int, int], picks: int, width: int) -> int:
    return min(
        _manhattan(source, target),
        _edge_cost(source, picks, width) + _edge_cost(target, picks, width),
    )


def _manhattan(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _edge_cost(cell: tuple[int, int], picks: int, width: int) -> int:
    row, column = cell
    return 1 + min(row, picks - 1 - row, column, width - 1 - column)


def _hungarian_minimize(cost: list[list[int]]) -> list[int]:
    """Return a minimum-cost column assignment for each row.

    The implementation is the standard shortest augmenting path form of the
    Hungarian algorithm. It accepts rectangular matrices, but Beta passes a
    square matrix after adding entry/exit dummy choices.
    """

    row_count = len(cost)
    if row_count == 0:
        return []
    column_count = len(cost[0])
    if any(len(row) != column_count for row in cost):
        raise ValueError("cost matrix must be rectangular")
    if row_count > column_count:
        transposed = [[cost[row][column] for row in range(row_count)] for column in range(column_count)]
        column_assignment = _hungarian_minimize(transposed)
        assignment = [-1 for _ in range(row_count)]
        for column, row in enumerate(column_assignment):
            assignment[row] = column
        return assignment

    potentials_row = [0 for _ in range(row_count + 1)]
    potentials_column = [0 for _ in range(column_count + 1)]
    matched_row_for_column = [0 for _ in range(column_count + 1)]
    previous_column = [0 for _ in range(column_count + 1)]

    for row in range(1, row_count + 1):
        matched_row_for_column[0] = row
        current_column = 0
        min_values = [math.inf for _ in range(column_count + 1)]
        used = [False for _ in range(column_count + 1)]

        while True:
            used[current_column] = True
            current_row = matched_row_for_column[current_column]
            delta = math.inf
            next_column = 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                reduced_cost = (
                    cost[current_row - 1][column - 1]
                    - potentials_row[current_row]
                    - potentials_column[column]
                )
                if reduced_cost < min_values[column]:
                    min_values[column] = reduced_cost
                    previous_column[column] = current_column
                if min_values[column] < delta:
                    delta = min_values[column]
                    next_column = column

            for column in range(column_count + 1):
                if used[column]:
                    potentials_row[matched_row_for_column[column]] += delta
                    potentials_column[column] -= delta
                else:
                    min_values[column] -= delta

            current_column = next_column
            if matched_row_for_column[current_column] == 0:
                break

        while True:
            next_column = previous_column[current_column]
            matched_row_for_column[current_column] = matched_row_for_column[next_column]
            current_column = next_column
            if current_column == 0:
                break

    assignment = [-1 for _ in range(row_count)]
    for column in range(1, column_count + 1):
        row = matched_row_for_column[column]
        if row:
            assignment[row - 1] = column - 1
    return assignment


def _candidate_key(candidate: DraftCandidate) -> tuple[float, ...]:
    return (
        candidate.hamming_error,
        len(candidate.threading) + len(candidate.tieup) + candidate.max_pressed_used,
        candidate.redundancy,
        candidate.impact_residual,
    )


def _beta_candidate_key(candidate: DraftCandidate) -> tuple[float, ...]:
    return (
        _candidate_movement_cost(candidate),
        candidate.hamming_error,
        len(candidate.threading) + len(candidate.tieup) + candidate.max_pressed_used,
        candidate.redundancy,
        candidate.impact_residual,
    )


def _candidate_movement_cost(candidate: DraftCandidate) -> int:
    if candidate.movement_cost is None:
        candidate.movement_cost = phi_beta(candidate.drawdown, candidate.target)
    return candidate.movement_cost


def _draft_search_score(candidate: DraftCandidate, lambda_value: float, mu_value: float) -> float:
    return candidate.hamming_error + lambda_value * candidate.impact_residual + mu_value * candidate.redundancy


def _beta_draft_search_score(candidate: DraftCandidate, lambda_value: float, mu_value: float) -> float:
    return _candidate_movement_cost(candidate) + lambda_value * candidate.impact_residual + mu_value * candidate.redundancy


def _shape(matrix: Matrix) -> tuple[int, int]:
    return len(matrix), len(matrix[0]) if matrix else 0


def _binary_key(row: Sequence[int]) -> str:
    return "".join("1" if value else "0" for value in row)


def _flip_key(key: str, index: int) -> str:
    flipped = "0" if key[index] == "1" else "1"
    return f"{key[:index]}{flipped}{key[index + 1:]}"


def _column_vectors(matrix: Matrix) -> Matrix:
    picks, width = _shape(matrix)
    return [[matrix[row][column] for row in range(picks)] for column in range(width)]


def _column_weight_vectors(impact: list[list[float]] | None) -> list[list[float]] | None:
    if impact is None:
        return None
    picks, width = _shape(impact)
    return [[impact[row][column] for row in range(picks)] for column in range(width)]


def _row_weight_vectors(impact: list[list[float]] | None) -> list[list[float]] | None:
    return [row[:] for row in impact] if impact is not None else None


def _hamming_distance(left: Sequence[int], right: Sequence[int], weights: Sequence[float] | None = None) -> float:
    distance = 0.0
    for index, left_value in enumerate(left):
        if int(left_value) != int(right[index]):
            distance += weights[index] if weights is not None else 1.0
    return distance


def _initial_assignments(
    vectors: Matrix,
    group_count: int,
    strategy: str,
    rng: random.Random,
    weight_vectors: list[list[float]] | None = None,
) -> list[int]:
    count = len(vectors)
    group_count = max(1, min(group_count, count or 1))
    if count == 0:
        return [0]

    unique_indices: list[int] = []
    seen: set[str] = set()
    for index, vector in enumerate(vectors):
        key = _binary_key(vector)
        if key not in seen:
            seen.add(key)
            unique_indices.append(index)

    if len(unique_indices) <= group_count:
        lookup = {_binary_key(vectors[index]): group for group, index in enumerate(unique_indices)}
        return [lookup[_binary_key(vector)] for vector in vectors]

    centers: list[list[int]] = []
    if strategy == "density":
        ordered = sorted(unique_indices, key=lambda index: (-sum(vectors[index]), index))
        centers = [vectors[index][:] for index in ordered[:group_count]]
    elif strategy == "random":
        ordered = unique_indices[:]
        rng.shuffle(ordered)
        centers = [vectors[index][:] for index in ordered[:group_count]]
    else:
        centers.append(vectors[unique_indices[0]][:])
        while len(centers) < group_count:
            best_index = unique_indices[0]
            best_distance = -1.0
            for index in unique_indices:
                weights = weight_vectors[index] if weight_vectors is not None else None
                distance = min(_hamming_distance(vectors[index], center, weights) for center in centers)
                if distance > best_distance:
                    best_distance = distance
                    best_index = index
            centers.append(vectors[best_index][:])

    assignments: list[int] = []
    for index, vector in enumerate(vectors):
        weights = weight_vectors[index] if weight_vectors is not None else None
        distances = [_hamming_distance(vector, center, weights) for center in centers]
        assignments.append(min(range(group_count), key=lambda group: (distances[group], group)))
    return _rebalance(assignments, group_count)


def _rebalance(assignments: list[int], group_count: int) -> list[int]:
    assignments = assignments[:]
    counts = [0 for _ in range(group_count)]
    for group in assignments:
        counts[group] += 1
    for group in range(group_count):
        if counts[group]:
            continue
        donor = next((index for index, count in enumerate(counts) if count > 1), None)
        if donor is None:
            break
        row = assignments.index(donor)
        assignments[row] = group
        counts[donor] -= 1
        counts[group] += 1
    return assignments


def _tieup_update(
    target: Matrix,
    row_assignments: list[int],
    column_assignments: list[int],
    treadle_count: int,
    shaft_count: int,
    impact: list[list[float]] | None,
    lambda_value: float,
) -> Matrix:
    ones = [[0 for _ in range(shaft_count)] for _ in range(treadle_count)]
    zeros = [[0 for _ in range(shaft_count)] for _ in range(treadle_count)]
    impact_ones = [[0.0 for _ in range(shaft_count)] for _ in range(treadle_count)]
    impact_zeros = [[0.0 for _ in range(shaft_count)] for _ in range(treadle_count)]

    for row, target_row in enumerate(target):
        treadle = row_assignments[row]
        for column, value in enumerate(target_row):
            shaft = column_assignments[column]
            weight = impact[row][column] if impact is not None else 1.0
            if value:
                ones[treadle][shaft] += 1
                impact_ones[treadle][shaft] += weight
            else:
                zeros[treadle][shaft] += 1
                impact_zeros[treadle][shaft] += weight

    tieup = [[0 for _ in range(shaft_count)] for _ in range(treadle_count)]
    for treadle in range(treadle_count):
        for shaft in range(shaft_count):
            score_zero = ones[treadle][shaft] + lambda_value * impact_ones[treadle][shaft]
            score_one = zeros[treadle][shaft] + lambda_value * impact_zeros[treadle][shaft]
            tieup[treadle][shaft] = 1 if score_one <= score_zero else 0
    return tieup


def _row_update(
    target: Matrix,
    tieup: Matrix,
    column_assignments: list[int],
    treadle_count: int,
    current: list[int],
    impact: list[list[float]] | None,
    lambda_value: float,
) -> list[int]:
    next_assignments = current[:]
    for row in range(len(target)):
        scores = []
        for treadle in range(treadle_count):
            mismatches = 0
            impact_mismatches = 0.0
            for column in range(len(target[row])):
                if target[row][column] != tieup[treadle][column_assignments[column]]:
                    mismatches += 1
                    impact_mismatches += impact[row][column] if impact is not None else 1.0
            scores.append((mismatches + lambda_value * impact_mismatches, mismatches, impact_mismatches, treadle))
        next_assignments[row] = min(scores)[3]
    return _rebalance(next_assignments, treadle_count)


def _column_update(
    target: Matrix,
    tieup: Matrix,
    row_assignments: list[int],
    shaft_count: int,
    current: list[int],
    impact: list[list[float]] | None,
    lambda_value: float,
) -> list[int]:
    _, width = _shape(target)
    next_assignments = current[:]
    for column in range(width):
        scores = []
        for shaft in range(shaft_count):
            mismatches = 0
            impact_mismatches = 0.0
            for row in range(len(target)):
                if target[row][column] != tieup[row_assignments[row]][shaft]:
                    mismatches += 1
                    impact_mismatches += impact[row][column] if impact is not None else 1.0
            scores.append((mismatches + lambda_value * impact_mismatches, mismatches, impact_mismatches, shaft))
        next_assignments[column] = min(scores)[3]
    return _rebalance(next_assignments, shaft_count)


def _drawdown_from_assignments(row_assignments: list[int], column_assignments: list[int], tieup: Matrix) -> Matrix:
    return [
        [tieup[row_assignments[row]][column_assignments[column]] for column in range(len(column_assignments))]
        for row in range(len(row_assignments))
    ]


def _redundancy_matrix(threading: Matrix, tieup: Matrix, treadling: Matrix) -> Matrix:
    picks = len(treadling)
    width = len(threading[0]) if threading else 0
    warp_to_shaft = [_column_shaft(threading, column) for column in range(width)]
    matrix = [[0 for _ in range(width)] for _ in range(picks)]
    for row in range(picks):
        pressed = [treadle for treadle, value in enumerate(treadling[row]) if value]
        for column, shaft in enumerate(warp_to_shaft):
            matrix[row][column] = sum(1 for treadle in pressed if tieup[treadle][shaft])
    return matrix


def _threshold(redundancy_matrix: Matrix) -> Matrix:
    return [[1 if value > 0 else 0 for value in row] for row in redundancy_matrix]


def _redundancy_score(redundancy_matrix: Matrix, target: Matrix) -> int:
    return sum(
        max(0, redundancy_matrix[row][column] - 1)
        for row in range(len(target))
        for column in range(len(target[row]))
        if target[row][column]
    )


def _impact_residual(target: Matrix, drawdown: Matrix, impact: list[list[float]] | None) -> float:
    if impact is None:
        return float(count_mismatches(target, drawdown))
    return sum(
        impact[row][column]
        for row in range(len(target))
        for column in range(len(target[row]))
        if target[row][column] != drawdown[row][column]
    )


def _annealed(value: float, iteration: int, iteration_limit: int) -> float:
    if iteration_limit <= 1:
        return 0.0
    return max(0.0, value * (1.0 - iteration / (iteration_limit - 1)))


def _state_signature(row_assignments: list[int], column_assignments: list[int], tieup: Matrix) -> str:
    return f"{','.join(map(str, row_assignments))}|{','.join(map(str, column_assignments))}|{_binary_key([value for row in tieup for value in row])}"


def _canonicalize_assignments(assignments: list[int]) -> tuple[list[int], dict[int, int]]:
    mapping: dict[int, int] = {}
    next_assignments: list[int] = []
    for value in assignments:
        if value not in mapping:
            mapping[value] = len(mapping)
        next_assignments.append(mapping[value])
    return next_assignments, mapping


def _dedupe_states(states: list[_State], beam_width: int) -> list[_State]:
    state_map: dict[str, _State] = {}
    for state in states:
        signature = _state_signature(state.row_assignments, state.column_assignments, state.tieup)
        existing = state_map.get(signature)
        if existing is None or (state.hamming_error, state.impact_residual) < (existing.hamming_error, existing.impact_residual):
            state_map[signature] = state
    return sorted(state_map.values(), key=lambda state: (state.hamming_error, state.impact_residual))[:beam_width]


def _allowed_treadle_subsets(treadle_count: int, max_pressed: int) -> list[tuple[int, ...]]:
    subsets: list[tuple[int, ...]] = [()]
    for size in range(1, min(treadle_count, max_pressed) + 1):
        subsets.extend(combinations(range(treadle_count), size))
    return subsets


def _column_shaft(threading: Matrix, column: int) -> int:
    for shaft, row in enumerate(threading):
        if row[column]:
            return shaft
    return 0


def _top_indices(values: Sequence[float], count: int) -> list[int]:
    return [index for index, _ in sorted(enumerate(values), key=lambda item: (-item[1], item[0]))[:count]]
