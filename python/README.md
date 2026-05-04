# Drafting Benchmarks

This folder contains a plain-Python implementation of the Alpha and Beta
algorithms from `math/weaving-structures.tex`. Alpha algorithms optimize raw
Hamming error. Beta algorithms optimize the open-boundary minimum movement
metric `phi_beta`, where black cells may move by adjacent transpositions or
exit and enter through the grid edge.

Run a small smoke benchmark:

```sh
python3 python/benchmark.py --trials 10 --sizes 10x10 --shafts 4 --treadles 6 --max-pressed 2
```

Run the 4-shaft benchmark table settings:

```sh
python3 python/benchmark.py \
  --trials 10000 \
  --sizes 10x10 20x20 30x30 40x40 \
  --shafts 4 \
  --treadles 6 \
  --max-pressed 2 \
  --probability 0.5 \
  --seed 1
```

Run the 8-shaft benchmark table settings:

```sh
python3 python/benchmark.py \
  --trials 10000 \
  --sizes 10x10 20x20 30x30 40x40 \
  --shafts 8 \
  --treadles 10 \
  --max-pressed 2 \
  --probability 0.5 \
  --seed 1
```

Use `--csv` to emit machine-readable results. Progress is shown on stderr, so
stdout remains clean for Markdown or CSV redirection; pass `--no-progress` to
disable it. Printed benchmark output reports normalized Hamming error first:
`mean_normalized_error` is divided by the number of target cells, while
`mean_raw_error` preserves the raw Hamming count. Beta rows also include
movement-cost statistics.

Run Beta algorithms explicitly:

```sh
python3 python/benchmark.py \
  --trials 10 \
  --sizes 10x10 \
  --shafts 4 \
  --treadles 6 \
  --max-pressed 2 \
  --algorithms beta1 beta2 beta3
```

## Parallel Benchmarks

Benchmark trials are independent: each algorithm run for each random target can
be evaluated separately and then averaged at the end. That makes the benchmark
a good fit for process-based parallelism. Python threads are not ideal here
because the algorithms are CPU-bound, so `--jobs N` uses worker processes.

Use `--jobs 1` for serial execution, `--jobs 8` for eight worker processes, or
`--jobs 0` to use all available CPUs.

```sh
python3 python/benchmark.py \
  --trials 10000 \
  --sizes 10x10 20x20 30x30 40x40 \
  --shafts 4 \
  --treadles 6 \
  --max-pressed 2 \
  --probability 0.5 \
  --seed 1 \
  --jobs 8
```

The benchmark uses deterministic seeds derived from the global seed, draft size,
and trial number, so normalized error statistics match between serial and
parallel runs. Runtime columns can differ because processes contend for CPU
resources differently than the serial path.
