#!/usr/bin/env python3
"""Settle interlaced yarns as discretized cylinder chains.

The input drawdown is a rectangular binary matrix shaped ``picks x ends``.
By convention, ``1`` means the warp yarn is above the weft yarn at that
crossing, and ``0`` means the weft yarn is above the warp yarn.

This model builds every yarn as a polyline of small cylindrical segments. The
segment endpoints are particles; neighboring particles are connected by axial
springs; the first and last particle of every yarn are fixed at ``z=0``. The
initial configuration follows the drawdown over/under order, and relaxation
then lets the springs pull while segment-segment collision constraints prevent
cylinders from occupying the same space.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import html as html_lib
import json
import math
from pathlib import Path
from typing import Any
import uuid

Matrix = list[list[int]]
Vec3 = list[float]


@dataclass(frozen=True)
class SettlingConfig:
    """Parameters for the cylinder/spring settling model."""

    thread_diameter: float = 1.0
    thread_spacing: float = 1.25
    cylinders_per_cell: int = 3
    spring_constant: float = 35.0
    time_step: float = 0.012
    damping: float = 0.88
    collision_iterations: int = 4
    iterations: int = 260
    tolerance: float = 1e-5
    end_margin_cells: float = 1.0


@dataclass(frozen=True)
class ThreadPath:
    """A settled yarn centerline made from cylindrical segments."""

    kind: str
    index: int
    nodes: list[Vec3]
    fixed: list[bool]

    @property
    def cylinder_count(self) -> int:
        return max(0, len(self.nodes) - 1)


@dataclass(frozen=True)
class SettledFabric:
    drawdown: Matrix
    config: SettlingConfig
    threads: list[ThreadPath]
    iterations: int
    max_penetration: float
    max_speed: float

    @property
    def thread_diameter(self) -> float:
        return self.config.thread_diameter

    @property
    def thread_radius(self) -> float:
        return self.config.thread_diameter / 2

    @property
    def thread_spacing(self) -> float:
        return _thread_spacing(self.config)

    @property
    def cylinder_count(self) -> int:
        return sum(thread.cylinder_count for thread in self.threads)

    @property
    def spring_count(self) -> int:
        return self.cylinder_count

    @property
    def node_count(self) -> int:
        return sum(len(thread.nodes) for thread in self.threads)

    def cylinders(self) -> list[dict[str, Any]]:
        cylinders: list[dict[str, Any]] = []
        for thread in self.threads:
            for index in range(thread.cylinder_count):
                cylinders.append(
                    {
                        "kind": thread.kind,
                        "thread_index": thread.index,
                        "segment_index": index,
                        "radius": self.thread_radius,
                        "start": thread.nodes[index][:],
                        "end": thread.nodes[index + 1][:],
                    }
                )
        return cylinders

    def crossing_clearance(self, row: int, col: int) -> float:
        """Return signed vertical clearance at a drawdown crossing.

        Positive values mean the simulated over/under order still matches the
        drawdown at that crossing.
        """

        _validate_crossing_index(self.drawdown, row, col)
        warp = self._thread("warp", col)
        weft = self._thread("weft", row)
        y = row * self.thread_spacing
        x = col * self.thread_spacing
        warp_z = _sample_axis_z(warp.nodes, axis=1, coordinate=y)
        weft_z = _sample_axis_z(weft.nodes, axis=0, coordinate=x)
        sign = 1 if self.drawdown[row][col] else -1
        return sign * (warp_z - weft_z)

    def draw_3d(
        self,
        *,
        canvas_width: int = 760,
        canvas_height: int = 540,
        height_scale: float = 1.0,
        warp_color: str = "#c45f2c",
        weft_color: str = "#2f6f9f",
        background: str = "#fffdf7",
        show_fixed_ends: bool = True,
    ) -> "_HtmlDrawing":
        """Return an interactive notebook-friendly 3D drawing."""

        return _HtmlDrawing(
            self.to_html(
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                height_scale=height_scale,
                warp_color=warp_color,
                weft_color=weft_color,
                background=background,
                show_fixed_ends=show_fixed_ends,
                iframe=True,
            )
        )

    def to_html(
        self,
        *,
        canvas_width: int = 760,
        canvas_height: int = 540,
        height_scale: float = 1.0,
        warp_color: str = "#c45f2c",
        weft_color: str = "#2f6f9f",
        background: str = "#fffdf7",
        show_fixed_ends: bool = True,
        iframe: bool = True,
    ) -> str:
        """Render an interactive 3D canvas view as HTML."""

        return _fabric_to_html(
            self,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            height_scale=height_scale,
            warp_color=warp_color,
            weft_color=weft_color,
            background=background,
            show_fixed_ends=show_fixed_ends,
            iframe=iframe,
        )

    def save_html(self, path: str | Path, **kwargs: Any) -> Path:
        output_path = Path(path)
        options = dict(kwargs)
        options["iframe"] = False
        output_path.write_text(self.to_html(**options), encoding="utf-8")
        return output_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "drawdown": self.drawdown,
            "config": asdict(self.config),
            "iterations": self.iterations,
            "max_penetration": self.max_penetration,
            "max_speed": self.max_speed,
            "node_count": self.node_count,
            "cylinder_count": self.cylinder_count,
            "spring_count": self.spring_count,
            "threads": [
                {
                    "kind": thread.kind,
                    "index": thread.index,
                    "nodes": [node[:] for node in thread.nodes],
                    "fixed": thread.fixed[:],
                }
                for thread in self.threads
            ],
        }

    def _thread(self, kind: str, index: int) -> ThreadPath:
        for thread in self.threads:
            if thread.kind == kind and thread.index == index:
                return thread
        raise IndexError(f"no {kind} thread with index {index}")


@dataclass(frozen=True)
class _HtmlDrawing:
    html: str

    def _repr_html_(self) -> str:
        return self.html

    def __str__(self) -> str:
        return self.html

    def save(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.write_text(self.html, encoding="utf-8")
        return output_path


def simulate_settling(drawdown: Matrix, config: SettlingConfig | None = None) -> SettledFabric:
    """Build interlaced cylinder chains and relax them with spring forces."""

    config = config or SettlingConfig()
    _validate_drawdown(drawdown)
    _validate_config(config)

    threads = _initial_threads(drawdown, config)
    velocities = [[_vec(0.0, 0.0, 0.0) for _ in thread.nodes] for thread in threads]
    rest_lengths = [[_distance_xy(thread.nodes[i], thread.nodes[i + 1]) for i in range(thread.cylinder_count)] for thread in threads]

    completed_iterations = 0
    max_speed = 0.0
    max_penetration = _max_penetration(threads, config.thread_diameter)
    for iteration in range(1, config.iterations + 1):
        forces = [[_vec(0.0, 0.0, 0.0) for _ in thread.nodes] for thread in threads]
        _apply_spring_forces(threads, forces, rest_lengths, config.spring_constant)
        max_speed = _integrate(threads, velocities, forces, config)
        _restore_fixed_nodes(threads)
        _project_interlacing(threads, drawdown, config)
        for _ in range(config.collision_iterations):
            _project_collisions(threads, config.thread_diameter)
            _project_interlacing(threads, drawdown, config)
            _restore_fixed_nodes(threads)

        completed_iterations = iteration
        max_penetration = _max_penetration(threads, config.thread_diameter)
        if max_speed * config.time_step <= config.tolerance and max_penetration <= config.tolerance:
            break

    final_projection_limit = max(config.collision_iterations * 120, 40)
    for projection_index in range(final_projection_limit):
        _project_collisions(threads, config.thread_diameter)
        _project_interlacing(threads, drawdown, config)
        _restore_fixed_nodes(threads)
        if projection_index % 8 == 0 or projection_index == final_projection_limit - 1:
            max_penetration = _max_penetration(threads, config.thread_diameter)
            if max_penetration <= 1e-7:
                break
    if max_penetration > 1e-7:
        raise RuntimeError("settling ended with overlapping cylinders")

    return SettledFabric(
        drawdown=[row[:] for row in drawdown],
        config=config,
        threads=threads,
        iterations=completed_iterations,
        max_penetration=max_penetration,
        max_speed=max_speed,
    )


def load_drawdown(source: str) -> Matrix:
    """Load a drawdown from a JSON matrix string or a path to a JSON file."""

    text = source
    if not source.lstrip().startswith("[") and (path := Path(source)).exists():
        text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list) or not all(isinstance(row, list) for row in data):
        raise ValueError("drawdown must be a JSON array of rows")
    matrix = [[int(value) for value in row] for row in data]
    _validate_drawdown(matrix)
    return matrix


def _validate_drawdown(drawdown: Matrix) -> None:
    if not drawdown:
        raise ValueError("drawdown must have at least one row")
    if not drawdown[0]:
        raise ValueError("drawdown must have at least one column")
    width = len(drawdown[0])
    for row in drawdown:
        if len(row) != width:
            raise ValueError("drawdown rows must all have the same length")
        for value in row:
            if value not in (0, 1):
                raise ValueError("drawdown entries must be 0 or 1")


def _validate_crossing_index(drawdown: Matrix, row: int, col: int) -> None:
    if row < 0 or row >= len(drawdown) or col < 0 or col >= len(drawdown[0]):
        raise IndexError("crossing index out of range")


def _validate_config(config: SettlingConfig) -> None:
    if config.thread_diameter <= 0:
        raise ValueError("thread_diameter must be positive")
    if config.thread_spacing <= 0:
        raise ValueError("thread_spacing must be positive")
    if config.thread_spacing < config.thread_diameter:
        raise ValueError("thread_spacing must be at least thread_diameter")
    if config.cylinders_per_cell < 1:
        raise ValueError("cylinders_per_cell must be positive")
    if config.spring_constant <= 0:
        raise ValueError("spring_constant must be positive")
    if config.time_step <= 0:
        raise ValueError("time_step must be positive")
    if not 0 <= config.damping < 1:
        raise ValueError("damping must be at least 0 and less than 1")
    if config.collision_iterations < 1:
        raise ValueError("collision_iterations must be positive")
    if config.iterations < 1:
        raise ValueError("iterations must be positive")
    if config.tolerance < 0:
        raise ValueError("tolerance must be nonnegative")
    if config.end_margin_cells < 0:
        raise ValueError("end_margin_cells must be nonnegative")


def _thread_spacing(config: SettlingConfig) -> float:
    return config.thread_spacing


def _initial_threads(drawdown: Matrix, config: SettlingConfig) -> list[ThreadPath]:
    rows = len(drawdown)
    cols = len(drawdown[0])
    spacing = _thread_spacing(config)
    layer_height = config.thread_diameter
    margin = config.end_margin_cells
    threads: list[ThreadPath] = []

    warp_start = -margin * spacing
    warp_end = (rows - 1 + margin) * spacing
    warp_segments = max(1, math.ceil((rows - 1 + 2 * margin) * config.cylinders_per_cell))
    for col in range(cols):
        targets = [
            (coordinate, _warp_target_z(drawdown, row, col, layer_height))
            for row, coordinate in enumerate([r * spacing for r in range(rows)])
        ]
        targets = [(warp_start, 0.0), *targets, (warp_end, 0.0)]
        nodes = []
        for index in range(warp_segments + 1):
            y = warp_start + (warp_end - warp_start) * index / warp_segments
            nodes.append(_vec(col * spacing, y, _interpolate_targets(targets, y)))
        fixed = [False for _ in nodes]
        fixed[0] = True
        fixed[-1] = True
        threads.append(ThreadPath(kind="warp", index=col, nodes=nodes, fixed=fixed))

    weft_start = -margin * spacing
    weft_end = (cols - 1 + margin) * spacing
    weft_segments = max(1, math.ceil((cols - 1 + 2 * margin) * config.cylinders_per_cell))
    for row in range(rows):
        targets = [(col * spacing, _weft_target_z(drawdown, row, col, layer_height)) for col in range(cols)]
        targets = [(weft_start, 0.0), *targets, (weft_end, 0.0)]
        nodes = []
        for index in range(weft_segments + 1):
            x = weft_start + (weft_end - weft_start) * index / weft_segments
            nodes.append(_vec(x, row * spacing, _interpolate_targets(targets, x)))
        fixed = [False for _ in nodes]
        fixed[0] = True
        fixed[-1] = True
        threads.append(ThreadPath(kind="weft", index=row, nodes=nodes, fixed=fixed))

    return threads


def _warp_target_z(drawdown: Matrix, row: int, col: int, radius: float) -> float:
    return radius if drawdown[row][col] else -radius


def _weft_target_z(drawdown: Matrix, row: int, col: int, radius: float) -> float:
    return -radius if drawdown[row][col] else radius


def _interpolate_targets(targets: list[tuple[float, float]], coordinate: float) -> float:
    for index in range(1, len(targets)):
        left_coordinate, left_z = targets[index - 1]
        right_coordinate, right_z = targets[index]
        if coordinate <= right_coordinate:
            if right_coordinate == left_coordinate:
                return right_z
            t = (coordinate - left_coordinate) / (right_coordinate - left_coordinate)
            return left_z + t * (right_z - left_z)
    return targets[-1][1]


def _apply_spring_forces(
    threads: list[ThreadPath],
    forces: list[list[Vec3]],
    rest_lengths: list[list[float]],
    spring_constant: float,
) -> None:
    for thread_index, thread in enumerate(threads):
        for segment_index in range(thread.cylinder_count):
            left = thread.nodes[segment_index]
            right = thread.nodes[segment_index + 1]
            delta = _sub(right, left)
            length = _length(delta)
            if length <= 1e-12:
                continue
            stretch = length - rest_lengths[thread_index][segment_index]
            force = _scale(delta, spring_constant * stretch / length)
            if not thread.fixed[segment_index]:
                _add_in_place(forces[thread_index][segment_index], force)
            if not thread.fixed[segment_index + 1]:
                _sub_in_place(forces[thread_index][segment_index + 1], force)


def _integrate(
    threads: list[ThreadPath],
    velocities: list[list[Vec3]],
    forces: list[list[Vec3]],
    config: SettlingConfig,
) -> float:
    max_speed = 0.0
    for thread_index, thread in enumerate(threads):
        for node_index, node in enumerate(thread.nodes):
            if thread.fixed[node_index]:
                velocities[thread_index][node_index] = _vec(0.0, 0.0, 0.0)
                continue
            velocity = velocities[thread_index][node_index]
            force = forces[thread_index][node_index]
            for axis in range(3):
                velocity[axis] = config.damping * velocity[axis] + config.time_step * force[axis]
                node[axis] += config.time_step * velocity[axis]
            max_speed = max(max_speed, _length(velocity))
    return max_speed


def _restore_fixed_nodes(threads: list[ThreadPath]) -> None:
    for thread in threads:
        if thread.kind == "warp":
            x = thread.nodes[0][0]
            thread.nodes[0][:] = [x, thread.nodes[0][1], 0.0]
            thread.nodes[-1][:] = [x, thread.nodes[-1][1], 0.0]
        else:
            y = thread.nodes[0][1]
            thread.nodes[0][:] = [thread.nodes[0][0], y, 0.0]
            thread.nodes[-1][:] = [thread.nodes[-1][0], y, 0.0]


def _project_collisions(threads: list[ThreadPath], diameter: float) -> None:
    segments = _segments(threads)
    for left_index, right_index in _candidate_segment_pairs(segments, diameter):
        left = segments[left_index]
        right = segments[right_index]
        if left["thread"] == right["thread"] and abs(left["segment"] - right["segment"]) <= 1:
            continue
        if not _expanded_boxes_intersect(left, right, diameter):
            continue
        left_point, right_point, left_t, right_t = _closest_points_on_segments(
            left["start"],
            left["end"],
            right["start"],
            right["end"],
        )
        delta = _sub(left_point, right_point)
        distance = _length(delta)
        penetration = diameter - distance
        if penetration <= 0:
            continue
        normal = _collision_normal(delta, distance, left, right)
        _separate_segments(left, right, normal, penetration, left_t, right_t)


def _project_interlacing(threads: list[ThreadPath], drawdown: Matrix, config: SettlingConfig) -> None:
    spacing = _thread_spacing(config)
    cols = len(drawdown[0])
    for row, drawdown_row in enumerate(drawdown):
        weft = threads[cols + row]
        for col, over in enumerate(drawdown_row):
            warp = threads[col]
            warp_segment, warp_t = _axis_segment_at_coordinate(warp.nodes, axis=1, coordinate=row * spacing)
            weft_segment, weft_t = _axis_segment_at_coordinate(weft.nodes, axis=0, coordinate=col * spacing)
            warp_z = _interpolated_segment_z(warp.nodes, warp_segment, warp_t)
            weft_z = _interpolated_segment_z(weft.nodes, weft_segment, weft_t)
            sign = 1.0 if over else -1.0
            gap = sign * (warp_z - weft_z)
            correction = config.thread_diameter - gap
            if correction <= 0:
                continue
            _move_segment_z(warp, warp_segment, warp_t, sign * correction * 0.5)
            _move_segment_z(weft, weft_segment, weft_t, -sign * correction * 0.5)


def _segments(threads: list[ThreadPath]) -> list[dict[str, Any]]:
    segments = []
    for thread_index, thread in enumerate(threads):
        for segment_index in range(thread.cylinder_count):
            start = thread.nodes[segment_index]
            end = thread.nodes[segment_index + 1]
            segments.append(
                {
                    "thread": thread_index,
                    "kind": thread.kind,
                    "segment": segment_index,
                    "start_index": segment_index,
                    "end_index": segment_index + 1,
                    "start": start,
                    "end": end,
                    "fixed_start": thread.fixed[segment_index],
                    "fixed_end": thread.fixed[segment_index + 1],
                }
            )
    return segments


def _candidate_segment_pairs(segments: list[dict[str, Any]], diameter: float) -> set[tuple[int, int]]:
    cell_size = diameter
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for index, segment in enumerate(segments):
        ranges = []
        for axis in range(3):
            minimum = min(segment["start"][axis], segment["end"][axis]) - diameter
            maximum = max(segment["start"][axis], segment["end"][axis]) + diameter
            ranges.append(range(math.floor(minimum / cell_size), math.floor(maximum / cell_size) + 1))
        for x in ranges[0]:
            for y in ranges[1]:
                for z in ranges[2]:
                    buckets.setdefault((x, y, z), []).append(index)

    pairs: set[tuple[int, int]] = set()
    for bucket in buckets.values():
        for left_offset, left_index in enumerate(bucket):
            for right_index in bucket[left_offset + 1 :]:
                pairs.add((left_index, right_index) if left_index < right_index else (right_index, left_index))
    return pairs


def _expanded_boxes_intersect(left: dict[str, Any], right: dict[str, Any], clearance: float) -> bool:
    for axis in range(3):
        left_min = min(left["start"][axis], left["end"][axis]) - clearance
        left_max = max(left["start"][axis], left["end"][axis]) + clearance
        right_min = min(right["start"][axis], right["end"][axis]) - clearance
        right_max = max(right["start"][axis], right["end"][axis]) + clearance
        if left_max < right_min or right_max < left_min:
            return False
    return True


def _closest_points_on_segments(p1: Vec3, q1: Vec3, p2: Vec3, q2: Vec3) -> tuple[Vec3, Vec3, float, float]:
    d1 = _sub(q1, p1)
    d2 = _sub(q2, p2)
    r = _sub(p1, p2)
    a = _dot(d1, d1)
    e = _dot(d2, d2)
    f = _dot(d2, r)
    epsilon = 1e-12

    if a <= epsilon and e <= epsilon:
        return p1[:], p2[:], 0.0, 0.0
    if a <= epsilon:
        s = 0.0
        t = _clamp(f / e, 0.0, 1.0)
    else:
        c = _dot(d1, r)
        if e <= epsilon:
            t = 0.0
            s = _clamp(-c / a, 0.0, 1.0)
        else:
            b = _dot(d1, d2)
            denominator = a * e - b * b
            s = _clamp((b * f - c * e) / denominator, 0.0, 1.0) if denominator else 0.0
            t_numerator = b * s + f
            if t_numerator < 0.0:
                t = 0.0
                s = _clamp(-c / a, 0.0, 1.0)
            elif t_numerator > e:
                t = 1.0
                s = _clamp((b - c) / a, 0.0, 1.0)
            else:
                t = t_numerator / e

    return _add(p1, _scale(d1, s)), _add(p2, _scale(d2, t)), s, t


def _collision_normal(delta: Vec3, distance: float, left: dict[str, Any], right: dict[str, Any]) -> Vec3:
    if distance > 1e-12:
        return _scale(delta, 1 / distance)
    center_delta = _sub(_segment_center(left), _segment_center(right))
    center_distance = _length(center_delta)
    if center_distance > 1e-12:
        return _scale(center_delta, 1 / center_distance)
    return _vec(0.0, 0.0, 1.0)


def _separate_segments(
    left: dict[str, Any],
    right: dict[str, Any],
    normal: Vec3,
    penetration: float,
    left_t: float,
    right_t: float,
) -> None:
    candidates = [
        (left["start"], left["fixed_start"], 1 - left_t, 1.0),
        (left["end"], left["fixed_end"], left_t, 1.0),
        (right["start"], right["fixed_start"], 1 - right_t, -1.0),
        (right["end"], right["fixed_end"], right_t, -1.0),
    ]
    denominator = sum(weight * weight for _, fixed, weight, _ in candidates if not fixed)
    if denominator <= 1e-12:
        return
    scale = penetration / denominator
    for node, fixed, weight, sign in candidates:
        if fixed:
            continue
        correction = _scale(normal, sign * scale * weight)
        _add_in_place(node, correction)


def _max_penetration(threads: list[ThreadPath], diameter: float) -> float:
    max_penetration = 0.0
    segments = _segments(threads)
    for left_index, right_index in _candidate_segment_pairs(segments, diameter):
        left = segments[left_index]
        right = segments[right_index]
        if left["thread"] == right["thread"] and abs(left["segment"] - right["segment"]) <= 1:
            continue
        if not _expanded_boxes_intersect(left, right, diameter):
            continue
        left_point, right_point, _, _ = _closest_points_on_segments(
            left["start"],
            left["end"],
            right["start"],
            right["end"],
        )
        max_penetration = max(max_penetration, diameter - _distance(left_point, right_point))
    return max(0.0, max_penetration)


def _sample_axis_z(nodes: list[Vec3], *, axis: int, coordinate: float) -> float:
    ordered = sorted(nodes, key=lambda node: node[axis])
    if coordinate <= ordered[0][axis]:
        return ordered[0][2]
    for index in range(1, len(ordered)):
        left = ordered[index - 1]
        right = ordered[index]
        if coordinate <= right[axis]:
            span = right[axis] - left[axis]
            if abs(span) <= 1e-12:
                return right[2]
            t = (coordinate - left[axis]) / span
            return left[2] + t * (right[2] - left[2])
    return ordered[-1][2]


def _axis_segment_at_coordinate(nodes: list[Vec3], *, axis: int, coordinate: float) -> tuple[int, float]:
    if coordinate <= nodes[0][axis]:
        return 0, 0.0
    for index in range(1, len(nodes)):
        left = nodes[index - 1]
        right = nodes[index]
        if coordinate <= right[axis]:
            span = right[axis] - left[axis]
            if abs(span) <= 1e-12:
                return index - 1, 1.0
            return index - 1, _clamp((coordinate - left[axis]) / span, 0.0, 1.0)
    return len(nodes) - 2, 1.0


def _interpolated_segment_z(nodes: list[Vec3], segment_index: int, t: float) -> float:
    return nodes[segment_index][2] * (1 - t) + nodes[segment_index + 1][2] * t


def _move_segment_z(thread: ThreadPath, segment_index: int, t: float, amount: float) -> None:
    weights = [(segment_index, 1 - t), (segment_index + 1, t)]
    denominator = sum(weight * weight for node_index, weight in weights if not thread.fixed[node_index])
    if denominator <= 1e-12:
        return
    scale = amount / denominator
    for node_index, weight in weights:
        if not thread.fixed[node_index]:
            thread.nodes[node_index][2] += scale * weight


def _fabric_to_html(
    fabric: SettledFabric,
    *,
    canvas_width: int,
    canvas_height: int,
    height_scale: float,
    warp_color: str,
    weft_color: str,
    background: str,
    show_fixed_ends: bool,
    iframe: bool,
) -> str:
    scene = _fabric_3d_scene(
        fabric,
        height_scale=height_scale,
        warp_color=warp_color,
        weft_color=weft_color,
        show_fixed_ends=show_fixed_ends,
    )
    scene["canvasWidth"] = canvas_width
    scene["canvasHeight"] = canvas_height
    scene["background"] = background
    scene_json = json.dumps(scene, separators=(",", ":"))
    standalone = _standalone_3d_html().replace("__SCENE_JSON__", scene_json)
    if not iframe:
        return standalone

    drawing_id = f"settled-cylinder-fabric-3d-{uuid.uuid4().hex}"
    return (
        f'<iframe id="{drawing_id}" title="Settled cylinder fabric 3D viewer" '
        f'width="{canvas_width}" height="{canvas_height}" '
        'style="border:0;max-width:100%;" '
        f'srcdoc="{html_lib.escape(standalone, quote=True)}"></iframe>'
    )


def _fabric_3d_scene(
    fabric: SettledFabric,
    *,
    height_scale: float,
    warp_color: str,
    weft_color: str,
    show_fixed_ends: bool,
) -> dict[str, Any]:
    all_points = [node for thread in fabric.threads for node in thread.nodes]
    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)
    min_z = min(point[2] for point in all_points) * height_scale
    max_z = max(point[2] for point in all_points) * height_scale
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    center_z = (min_z + max_z) / 2
    threads = []
    fixed_points = []
    for thread in fabric.threads:
        color = warp_color if thread.kind == "warp" else weft_color
        points = [[node[0] - center_x, node[1] - center_y, node[2] * height_scale - center_z] for node in thread.nodes]
        threads.append(
            {
                "kind": thread.kind,
                "index": thread.index,
                "color": color,
                "width": fabric.thread_diameter,
                "points": points,
            }
        )
        if show_fixed_ends:
            fixed_points.append(points[0])
            fixed_points.append(points[-1])

    span_x = max_x - min_x + fabric.thread_diameter
    span_y = max_y - min_y + fabric.thread_diameter
    span_z = max_z - min_z + fabric.thread_diameter
    return {
        "threadDiameter": fabric.thread_diameter,
        "threadSpacing": fabric.thread_spacing,
        "cylinderCount": fabric.cylinder_count,
        "sceneSpan": max(span_x, span_y, span_z),
        "threads": threads,
        "fixedPoints": fixed_points,
    }


def _standalone_3d_html() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body {
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: transparent;
    }
    canvas {
      display: block;
      width: 100%;
      height: 100%;
      cursor: grab;
      touch-action: none;
    }
    canvas.dragging {
      cursor: grabbing;
    }
  </style>
</head>
<body>
<canvas id="fabric-viewer" title="Drag to rotate. Shift-drag or right-drag to pan. Scroll to zoom."></canvas>
<script>
(() => {
  const scene = __SCENE_JSON__;
  const canvas = document.getElementById("fabric-viewer");
  const ctx = canvas.getContext("2d");
  let yaw = -0.7;
  let pitch = 0.65;
  let zoom = Math.min(scene.canvasWidth, scene.canvasHeight) / Math.max(scene.sceneSpan || 2, 0.001) * 0.82;
  let panX = 0;
  let panY = 0;
  let dragging = false;
  let dragMode = "rotate";
  let lastX = 0;
  let lastY = 0;

  function resizeCanvas() {
    const ratio = window.devicePixelRatio || 1;
    canvas.style.width = scene.canvasWidth + "px";
    canvas.style.height = scene.canvasHeight + "px";
    canvas.width = Math.round(scene.canvasWidth * ratio);
    canvas.height = Math.round(scene.canvasHeight * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    draw();
  }

  function rotate(point) {
    const x = point[0];
    const y = point[1];
    const z = point[2];
    const cy = Math.cos(yaw);
    const sy = Math.sin(yaw);
    const cp = Math.cos(pitch);
    const sp = Math.sin(pitch);
    const x1 = x * cy - y * sy;
    const y1 = x * sy + y * cy;
    const y2 = y1 * cp - z * sp;
    const z2 = y1 * sp + z * cp;
    return {x: x1, y: y2, z: z2};
  }

  function project(point) {
    const rotated = rotate(point);
    const camera = 8;
    const perspective = camera / Math.max(1, camera - rotated.z);
    return {
      x: scene.canvasWidth / 2 + panX + rotated.x * zoom * perspective,
      y: scene.canvasHeight / 2 + panY - rotated.y * zoom * perspective,
      z: rotated.z,
      perspective
    };
  }

  function drawFixedPoint(point) {
    const projected = project(point);
    const radius = Math.max(3, scene.threadDiameter * zoom * projected.perspective * 0.18);
    ctx.globalAlpha = 0.58;
    ctx.fillStyle = "#1f1f1f";
    ctx.beginPath();
    ctx.arc(projected.x, projected.y, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  function catmullRom(points, index, t) {
    const p0 = points[Math.max(0, index - 1)];
    const p1 = points[index];
    const p2 = points[index + 1];
    const p3 = points[Math.min(points.length - 1, index + 2)];
    const t2 = t * t;
    const t3 = t2 * t;
    return [0, 1, 2].map((axis) => 0.5 * (
      2 * p1[axis]
      + (-p0[axis] + p2[axis]) * t
      + (2 * p0[axis] - 5 * p1[axis] + 4 * p2[axis] - p3[axis]) * t2
      + (-p0[axis] + 3 * p1[axis] - 3 * p2[axis] + p3[axis]) * t3
    ));
  }

  function smoothPoints(points) {
    if (points.length < 3) {
      return points;
    }
    const smoothed = [];
    for (let index = 0; index < points.length - 1; index += 1) {
      for (let step = 0; step < 4; step += 1) {
        smoothed.push(catmullRom(points, index, step / 4));
      }
    }
    smoothed.push(points[points.length - 1]);
    return smoothed;
  }

  function drawSmoothThread(thread) {
    const projected = smoothPoints(thread.points).map(project);
    const perspective = projected.reduce((sum, point) => sum + point.perspective, 0) / projected.length;
    const width = Math.max(2, thread.width * zoom * perspective);

    ctx.globalAlpha = 0.95;
    ctx.strokeStyle = thread.color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(projected[0].x, projected[0].y);
    for (let index = 1; index < projected.length - 1; index += 1) {
      const current = projected[index];
      const next = projected[index + 1];
      ctx.quadraticCurveTo(current.x, current.y, (current.x + next.x) / 2, (current.y + next.y) / 2);
    }
    const last = projected[projected.length - 1];
    ctx.lineTo(last.x, last.y);
    ctx.stroke();
  }

  function draw() {
    ctx.clearRect(0, 0, scene.canvasWidth, scene.canvasHeight);
    ctx.fillStyle = scene.background;
    ctx.fillRect(0, 0, scene.canvasWidth, scene.canvasHeight);

    const threads = scene.threads.map((thread) => {
      const projected = thread.points.map(project);
      const depth = projected.reduce((sum, point) => sum + point.z, 0) / projected.length;
      return {...thread, depth};
    });
    threads.sort((left, right) => left.depth - right.depth);

    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const thread of threads) {
      drawSmoothThread(thread);
    }
    for (const point of scene.fixedPoints || []) {
      drawFixedPoint(point);
    }
    ctx.globalAlpha = 1;
  }

  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    dragMode = event.shiftKey || event.button === 2 ? "pan" : "rotate";
    lastX = event.clientX;
    lastY = event.clientY;
    canvas.classList.add("dragging");
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) {
      return;
    }
    const dx = event.clientX - lastX;
    const dy = event.clientY - lastY;
    lastX = event.clientX;
    lastY = event.clientY;
    if (dragMode === "pan") {
      panX += dx;
      panY += dy;
    } else {
      yaw += dx * 0.01;
      pitch = Math.max(-1.35, Math.min(1.35, pitch + dy * 0.01));
    }
    draw();
  });

  function stopDrag(event) {
    dragging = false;
    canvas.classList.remove("dragging");
    if (event.pointerId !== undefined && canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
  }

  canvas.addEventListener("pointerup", stopDrag);
  canvas.addEventListener("pointercancel", stopDrag);
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom *= Math.exp(-event.deltaY * 0.001);
    zoom = Math.max(8, Math.min(1600, zoom));
    draw();
  }, {passive: false});

  resizeCanvas();
})();
</script>
</body>
</html>
"""


def _vec(x: float, y: float, z: float) -> Vec3:
    return [float(x), float(y), float(z)]


def _add(left: Vec3, right: Vec3) -> Vec3:
    return [left[0] + right[0], left[1] + right[1], left[2] + right[2]]


def _sub(left: Vec3, right: Vec3) -> Vec3:
    return [left[0] - right[0], left[1] - right[1], left[2] - right[2]]


def _scale(vector: Vec3, scalar: float) -> Vec3:
    return [vector[0] * scalar, vector[1] * scalar, vector[2] * scalar]


def _dot(left: Vec3, right: Vec3) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _length(vector: Vec3) -> float:
    return math.sqrt(_dot(vector, vector))


def _distance(left: Vec3, right: Vec3) -> float:
    return _length(_sub(left, right))


def _distance_xy(left: Vec3, right: Vec3) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _segment_center(segment: dict[str, Any]) -> Vec3:
    return [
        (segment["start"][0] + segment["end"][0]) / 2,
        (segment["start"][1] + segment["end"][1]) / 2,
        (segment["start"][2] + segment["end"][2]) / 2,
    ]


def _add_in_place(left: Vec3, right: Vec3) -> None:
    left[0] += right[0]
    left[1] += right[1]
    left[2] += right[2]


def _sub_in_place(left: Vec3, right: Vec3) -> None:
    left[0] -= right[0]
    left[1] -= right[1]
    left[2] -= right[2]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Settle interlaced cylinder-chain yarns from a drawdown matrix.")
    parser.add_argument("drawdown", help="JSON matrix literal or path to a JSON file.")
    parser.add_argument("--thread-diameter", type=float, default=1.0)
    parser.add_argument("--thread-spacing", type=float, default=1.25)
    parser.add_argument("--cylinders-per-cell", type=int, default=3)
    parser.add_argument("--spring-constant", type=float, default=35.0)
    parser.add_argument("--time-step", type=float, default=0.012)
    parser.add_argument("--damping", type=float, default=0.88)
    parser.add_argument("--collision-iterations", type=int, default=4)
    parser.add_argument("--iterations", type=int, default=260)
    parser.add_argument("--tolerance", type=float, default=1e-5)
    parser.add_argument("--end-margin-cells", type=float, default=1.0)
    args = parser.parse_args(argv)

    config = SettlingConfig(
        thread_diameter=args.thread_diameter,
        thread_spacing=args.thread_spacing,
        cylinders_per_cell=args.cylinders_per_cell,
        spring_constant=args.spring_constant,
        time_step=args.time_step,
        damping=args.damping,
        collision_iterations=args.collision_iterations,
        iterations=args.iterations,
        tolerance=args.tolerance,
        end_margin_cells=args.end_margin_cells,
    )
    result = simulate_settling(load_drawdown(args.drawdown), config)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
