"""Seeded, offline studies for the shared pane-study verdict rule (T231)."""

from __future__ import annotations

import json
import math
import operator
import os
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray
from pydantic import Field, field_validator

from swreview.benchmark import digest, stats, verdict
from swreview.findings import ReviewModel

RateDraw = Callable[[np.random.Generator, tuple[int, int]], ArrayLike]


def _sim_integer(value: int, name: str, minimum: int = 0) -> int:
    try:
        if isinstance(value, (bool, np.bool_)):
            raise TypeError
        result = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer at least {minimum}") from exc
    if result < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}")
    return result


def _sim_number(value: float, name: str, *, probability: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite and nonnegative") from exc
    if not math.isfinite(result) or result < 0 or (probability and result > 1):
        suffix = " inside [0, 1]" if probability else " and nonnegative"
        raise ValueError(f"{name} must be finite{suffix}")
    return result


@dataclass(frozen=True)
class Layout:
    """Held-out model defects per package and the packages in one growth unit."""

    packages: tuple[int, ...] = (2,) * 17 + (0,) * 34
    growth_unit: tuple[int, ...] = (2, 0, 0)

    def __post_init__(self) -> None:
        for name in ("packages", "growth_unit"):
            values = tuple(_sim_integer(value, name) for value in getattr(self, name))
            if not values or any(value > 2 for value in values):
                raise ValueError(f"{name} must contain package defect counts from 0 to 2")
            object.__setattr__(self, name, values)
        if not any(self.packages):
            raise ValueError("packages must hold at least one defect")
        if not any(self.growth_unit):
            raise ValueError("growth_unit must add at least one defect")

    @property
    def defects(self) -> int:
        return sum(self.packages)

    @property
    def package_count(self) -> int:
        return len(self.packages)

    def grown(self, units: int) -> Layout:
        units = _sim_integer(units, "units")
        return Layout(self.packages + self.growth_unit * units, self.growth_unit)


REFERENCE_LAYOUT = Layout()


@dataclass(frozen=True)
class Scenario:
    """Simulation inputs, with optional per-defect code and clearance rates.

    Scalar code_rate and clearance_rate apply to every selected defect. A tuple
    supplies one probability per defect, in the simulator's selected-defect
    order, and must match code_count or clearance_count respectively.
    Explicit clearance tuples may include held-out known defects with measured
    clearances but no completed-run detection estimate; these have no code-rate
    or recall-rate slot and still enter the cleared guard.
    When growth_clearance_rate is given, search gives every added model
    defect that pooled clearance probability, independently per arm and
    repetition, alongside the original per-defect clearance estimates.
    """

    name: str
    rates: str | RateDraw
    sd: float
    fa_mean: float
    fa_size: float | None
    stop_rate: float = 0
    clearance_count: int = 0
    clearance_rate: float | tuple[float, ...] = 0
    code_count: int = 0
    code_rate: float | tuple[float, ...] = 0.95
    growth_clearance_rate: float | None = None

    def __post_init__(self) -> None:
        if not callable(self.rates) and self.rates not in ("half", "uniform", "polar"):
            raise ValueError("rates must be half, uniform, polar or a rate draw")
        for name in ("sd", "fa_mean"):
            _sim_number(getattr(self, name), name)
        if self.fa_size is not None and _sim_number(self.fa_size, "fa_size") == 0:
            raise ValueError("fa_size must be positive or None")
        _sim_number(self.stop_rate, "stop_rate", probability=True)
        if self.growth_clearance_rate is not None:
            _sim_number(self.growth_clearance_rate, "growth_clearance_rate", probability=True)
        for name in ("clearance_count", "code_count"):
            _sim_integer(getattr(self, name), name)
        for name, count_name in (
            ("clearance_rate", "clearance_count"), ("code_rate", "code_count"),
        ):
            rate = getattr(self, name)
            if isinstance(rate, tuple):
                if len(rate) != getattr(self, count_name):
                    raise ValueError(f"{name} must contain {count_name} probabilities")
                for value in rate:
                    _sim_number(value, name, probability=True)
            else:
                _sim_number(rate, name, probability=True)


def _reference_scenarios() -> dict[str, Scenario]:
    scenarios: dict[str, Scenario] = {}
    for distribution in ("half", "uniform", "polar"):
        for sd in (0, 1.0):
            for mean in (0.2, 1, 3):
                for size in (0.5, None):
                    suffix = "poisson" if size is None else "nb0.5"
                    name = f"{distribution}-sd{sd}-fa{mean}-{suffix}"
                    scenarios[name] = Scenario(name, distribution, sd, mean, size)
    base = scenarios["uniform-sd1.0-fa1-nb0.5"]
    for suffix, values in (
        ("stop", {"stop_rate": 0.05}),
        ("clear", {"clearance_count": 10, "clearance_rate": 0.05}),
        ("code", {"code_count": 10, "code_rate": 0.95}),
    ):
        name = f"{base.name}-{suffix}"
        scenarios[name] = replace(base, name=name, **values)
    return scenarios


SCENARIOS = _reference_scenarios()


def _sim_rates(rates: ArrayLike) -> NDArray[np.float64]:
    try:
        result = np.asarray(rates, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("rates must be finite probabilities inside [0, 1]") from exc
    if (
        result.ndim not in (1, 2)
        or result.shape[-1] == 0
        or not np.all(np.isfinite(result))
        or np.any((result < 0) | (result > 1))
    ):
        raise ValueError("rates must be a nonempty vector or matrix of probabilities inside [0, 1]")
    return result


def drop_rates(rates: ArrayLike, drop: float, shape: str) -> NDArray[np.float64] | None:
    """Remove a marginal mean drop, separately along each row's last axis.

    Room redistribution is water filling: after sorting, the first rate above
    the remaining equal share fixes the common removal threshold. A short row
    in a mixed matrix is NaN; None means no row can attain the drop.
    """
    values = _sim_rates(rates)
    drop = _sim_number(drop, "drop", probability=True)
    if shape not in ("room", "proportional"):
        raise ValueError("shape must be room or proportional")
    if drop == 0:
        return values.copy()
    count = values.shape[-1]
    means = np.mean(values, axis=-1, keepdims=True)
    short = means < drop
    exhausted = np.zeros_like(short)
    rows = np.atleast_2d(values)
    # A rounded mean can cross the attainability boundary in either direction.
    # Only near it, sum rates and the per-defect drop together: separately
    # rounded totals can hide even a one-ulp shortage.
    near_boundary = np.abs(means - drop) <= 4 * math.ulp(drop)
    near_indices = np.flatnonzero(near_boundary)
    if near_indices.size:
        remaining = stats._fsum_last(np.concatenate((
            rows[near_indices], np.full((near_indices.size, count), -drop),
        ), axis=-1))
        short.flat[near_indices] = remaining < 0
        exhausted.flat[near_indices] = remaining == 0
    if np.all(short):
        return None
    if shape == "proportional":
        multiplier = np.divide(drop, means, out=np.zeros_like(means), where=means > 0)
        result = np.maximum(values * (1 - multiplier), 0)
    else:
        ordered = np.sort(values, axis=-1)
        prefix = np.cumsum(ordered, axis=-1) - ordered
        shares = (count * drop - prefix) / (count - np.arange(count))
        fits = shares <= ordered
        index = np.where(np.any(fits, axis=-1), np.argmax(fits, axis=-1), count - 1)
        threshold = np.take_along_axis(shares, np.expand_dims(index, -1), axis=-1)
        result = np.maximum(values - threshold, 0)
    if np.any(exhausted):
        result = np.where(exhausted, 0, result)
    return np.where(short, np.nan, result) if np.any(short) else result


def draw_false_alarms(
    rng: np.random.Generator, m: float, k: float | None, n: int | tuple[int, ...]
) -> NDArray[np.int64]:
    """Poisson counts, mixed by Gamma(k, m/k) for the negative-binomial branch."""
    mean = _sim_number(m, "m")
    if k is None:
        return rng.poisson(mean, size=n)
    size = _sim_number(k, "k")
    if size == 0:
        raise ValueError("k must be positive or None")
    return rng.poisson(rng.gamma(size, mean / size, size=n))


def stress_case(rates: ArrayLike, reps: int) -> float | NDArray[np.float64]:
    """Code guard's unbounded stress rate when both arms have the stated rates."""
    values = _sim_rates(rates)
    reps = _sim_integer(reps, "reps", minimum=1)
    all_detected = values**reps
    result = 1 - np.prod(1 - all_detected * (1 - all_detected), axis=-1)
    return float(result) if result.ndim == 0 else result


def cleared_null_rate(q: float | tuple[float, ...], count: int, reps: int) -> float:
    """Chance the cleared guard fires at least once under identical arms."""
    if isinstance(q, tuple):
        count = _sim_integer(count, "count")
        reps = _sim_integer(reps, "reps", minimum=1)
        if len(q) != count:
            raise ValueError("q must contain count probabilities")
        rates = [_sim_number(value, "q", probability=True) for value in q]
        never_cleared_rates = [(1 - rate) ** reps for rate in rates]
        return 1 - math.prod(
            1 - (1 - never_cleared) * never_cleared
            for never_cleared in never_cleared_rates
        )
    q = _sim_number(q, "q", probability=True)
    count = _sim_integer(count, "count")
    reps = _sim_integer(reps, "reps", minimum=1)
    never_cleared = (1 - q) ** reps
    return 1 - (1 - (1 - never_cleared) * never_cleared) ** count


class NotAttainable(ValueError):
    """A requested marginal drop exceeds the rates' total available detection."""


@dataclass(frozen=True)
class Draws:
    """Optional run-level draws used to compare direct counts with scorecards.

    Item arrays have axes study, arm, repetition, item; package arrays replace
    item with package. Detections are the underlying Bernoulli draws, while
    false alarms already include the stopped-run thinning. The shared verdict
    receives the completion masks through ``stats``.
    """

    stats: verdict.StudyStats
    detections: NDArray[np.bool_]
    code_detections: NDArray[np.bool_]
    clears: NDArray[np.bool_]
    stopped: NDArray[np.bool_]
    false_alarms: NDArray[np.int64]
    defect_packages: NDArray[np.int64]
    code_packages: NDArray[np.int64]
    off_rates: NDArray[np.float64]
    on_rates: NDArray[np.float64]
    layout: Layout


def _draw_rates(
    rng: np.random.Generator, scenario: Scenario, sims: int, defects: int
) -> NDArray[np.float64]:
    shape = (sims, defects)
    if callable(scenario.rates):
        values = _sim_rates(scenario.rates(rng, shape))
        if values.shape != shape:
            raise ValueError("rates draw must return the requested (sims, defects) shape")
    elif scenario.rates == "half":
        values = np.full(shape, 0.5)
    elif scenario.rates == "uniform":
        values = rng.random(shape)
    elif defects < 34:
        values = rng.choice((0.0, 1.0, 0.5), size=shape, p=(3 / 8, 3 / 8, 1 / 4))
    else:
        original = np.broadcast_to(np.array((0.0,) * 13 + (1.0,) * 13 + (0.5,) * 8), (sims, 34))
        extra = rng.choice(
            (0.0, 1.0, 0.5), size=(sims, defects - 34), p=(3 / 8, 3 / 8, 1 / 4)
        )
        values = np.concatenate((original, extra), axis=-1)
    return rng.permuted(values, axis=1)


def _draw_detections(rng, intercepts, sd, package_shape, defect_packages):
    """One repetition, sharing shocks and uniforms across any leading variants."""
    shocks = rng.normal(0, sd, size=package_shape) if sd else 0
    logits = intercepts + (shocks[..., defect_packages] if sd else 0)
    probabilities = np.exp(-np.logaddexp(0, -logits))
    draw_shape = (*package_shape[:-1], len(defect_packages))
    return rng.random(draw_shape) < probabilities


def _main_figure_stats(
    detected, package_runs, defect_packages, false_alarms, *,
    code_detections=None, code_runs=None, clears=None, clear_held_out=None,
):
    """Assemble shared recall figures and optional simulator guard counts."""
    empty = np.zeros((*detected.shape[:-1], 0), dtype=np.int64)
    return verdict.StudyStats(
        detections=np.stack((detected, detected), axis=2),
        counted_runs=package_runs[..., defect_packages],
        defect_packages=defect_packages,
        false_alarms=false_alarms,
        package_runs=package_runs,
        code_detections=empty if code_detections is None else code_detections,
        code_runs=empty if code_runs is None else code_runs,
        clears=empty if clears is None else clears,
        clear_held_out=np.zeros(0, dtype=bool) if clear_held_out is None else clear_held_out,
    )


class _StudyDrawStream:
    """Accumulate seeded repetitions, sharing unchanged draws across drop shapes.

    Every RNG call keeps the scalar engine's dimensions and order. Only the
    deterministic probability/count arrays carry a leading variant axis.
    """

    def __init__(
        self, scenario, *, seed, sims, layout, requests, return_draws=False,
    ):
        seed = _sim_integer(seed, "seed")
        self.sims = sims = _sim_integer(sims, "sims", minimum=1)
        if (
            not isinstance(scenario.clearance_rate, tuple)
            and scenario.clearance_count > layout.defects + scenario.code_count
        ):
            raise ValueError("clearance_count exceeds the layout's model and code defects")
        self.scenario, self.layout = scenario, layout
        self.rng = np.random.Generator(np.random.PCG64(seed))
        self.off_rates = _draw_rates(self.rng, scenario, sims, layout.defects)
        self.on_rates = {
            name: drop_rates(self.off_rates, drop, shape)
            for name, (drop, shape) in requests.items()
        }
        self.eligible = {
            name: np.all(np.isfinite(rates), axis=-1)
            for name, rates in self.on_rates.items() if rates is not None
        }
        self.variants = {
            name: index for index, name in enumerate(
                name for name, rates in self.on_rates.items() if rates is not None
            )
        }
        table = stats.intercept_table(scenario.sd)
        off_intercepts = stats.intercept(table, self.off_rates)
        intercepts = [
            np.stack((
                off_intercepts,
                off_intercepts if requests[name][0] == 0
                else stats.intercept(table, np.nan_to_num(self.on_rates[name])),
            ), axis=1)
            for name in self.variants
        ]
        self.intercepts = np.stack(intercepts) if intercepts else None
        self.defect_packages = np.repeat(np.arange(layout.package_count), layout.packages)
        self.code_packages = np.resize(np.flatnonzero(layout.packages), scenario.code_count)
        self.package_shape = (sims, 2, layout.package_count)
        self.detected_counts = np.zeros(
            (len(self.variants), sims, 2, layout.defects), dtype=np.int64,
        )
        self.main_runs = np.zeros(self.package_shape, dtype=np.int64)
        self.main_alarms = np.zeros(self.package_shape, dtype=np.int64)
        self.sensitivity_alarms = np.zeros(self.package_shape, dtype=np.int64)
        self.code_counts = np.zeros((sims, 2, scenario.code_count), dtype=np.int64)
        self.cleared_counts = np.zeros((sims, 2, scenario.clearance_count), dtype=np.int64)
        self.uncleared_count = max(
            0, layout.defects + scenario.code_count - scenario.clearance_count,
        )
        self.return_draws, self.reps = return_draws, 0
        self.captured: dict[str, list[NDArray]] = {
            name: [] for name in (
                "detections", "code_detections", "clears", "stopped", "false_alarms",
            )
        }

    def advance(self, reps):
        """Extend this layout's prefix; previous sizes need no retained snapshots."""
        reps = _sim_integer(reps, "reps", minimum=1)
        if reps < self.reps:
            raise ValueError("reps cannot decrease within a draw stream")
        if self.intercepts is None:
            raise NotAttainable("drop is not attainable for these rates")
        scenario, rng = self.scenario, self.rng
        for _ in range(self.reps, reps):
            detections = _draw_detections(
                rng, self.intercepts, scenario.sd, self.package_shape, self.defect_packages,
            )
            stopped = (
                rng.random(self.package_shape) < scenario.stop_rate
                if scenario.stop_rate else np.zeros(self.package_shape, dtype=bool)
            )
            complete = ~stopped
            alarms = draw_false_alarms(
                rng, scenario.fa_mean, scenario.fa_size, self.package_shape,
            )
            if scenario.stop_rate:
                thinned = rng.binomial(alarms, rng.random(self.package_shape))
                alarms = np.where(stopped, thinned, alarms)
            self.detected_counts += detections & complete[..., self.defect_packages]
            self.main_runs += complete
            self.main_alarms += alarms * complete
            self.sensitivity_alarms += alarms
            code_detections = np.stack((
                rng.random((self.sims, scenario.code_count)) < scenario.code_rate,
                np.ones((self.sims, scenario.code_count), dtype=bool),
            ), axis=1)
            self.code_counts += code_detections & complete[..., self.code_packages]
            clears = rng.random(self.cleared_counts.shape) < scenario.clearance_rate
            self.cleared_counts += clears
            if self.return_draws:
                self.captured["detections"].append(detections)
                self.captured["code_detections"].append(code_detections)
                self.captured["stopped"].append(stopped)
                self.captured["false_alarms"].append(alarms)
                self.captured["clears"].append(np.concatenate((
                    clears, np.zeros((self.sims, 2, self.uncleared_count), dtype=bool),
                ), axis=-1))
        self.reps = reps

    def snapshot(self, name):
        """Read one shape at the current size without retaining earlier sizes."""
        if name not in self.variants:
            return None
        eligible = self.eligible[name]
        # Keep every study in the RNG stream, and exclude only from this shape's
        # measurements. Thus an ineligible row cannot change other seeded draws.
        selected = slice(None) if np.all(eligible) else eligible
        detected = self.detected_counts[self.variants[name], selected]
        main_runs = self.main_runs[selected]
        sensitivity_runs = np.full(main_runs.shape, self.reps, dtype=np.int64)
        package_runs = np.stack((main_runs, sensitivity_runs), axis=2)
        return _main_figure_stats(
            detected, package_runs, self.defect_packages,
            np.stack((
                self.main_alarms[selected], self.sensitivity_alarms[selected],
            ), axis=2),
            code_detections=self.code_counts[selected].copy(),
            code_runs=main_runs[..., self.code_packages],
            clears=np.concatenate((
                self.cleared_counts[selected],
                np.zeros((main_runs.shape[0], 2, self.uncleared_count), dtype=np.int64),
            ), axis=-1),
            clear_held_out=np.ones(
                max(self.layout.defects + self.scenario.code_count, self.scenario.clearance_count),
                dtype=bool,
            ),
        )

    def raw(self, name):
        variant = self.variants[name]
        eligible = self.eligible[name]
        selected = slice(None) if np.all(eligible) else eligible
        return Draws(
            stats=self.snapshot(name),
            **{
                key: np.stack(
                    [draw[variant] for draw in values] if key == "detections" else values,
                    axis=2,
                )[selected]
                for key, values in self.captured.items()
            },
            defect_packages=self.defect_packages,
            code_packages=self.code_packages,
            off_rates=self.off_rates[selected],
            on_rates=self.on_rates[name][selected],
            layout=self.layout,
        )


def draw_studies(
    scenario: Scenario,
    *,
    seed: int,
    sims: int,
    reps: int,
    layout: Layout = REFERENCE_LAYOUT,
    drop: float = 0,
    shape: str = "room",
    return_draws: bool = False,
) -> verdict.StudyStats | Draws:
    """Draw studies in the original seeded call order, one repetition at a time."""
    reps = _sim_integer(reps, "reps", minimum=1)
    stream = _StudyDrawStream(
        scenario, seed=seed, sims=sims, layout=layout,
        requests={"only": (drop, shape)}, return_draws=return_draws,
    )
    stream.advance(reps)
    return stream.raw("only") if return_draws else stream.snapshot("only")


# The same simulation data are reused across levels: alpha never changes the draws.
ALPHA_LADDER = (0.025, 0.02, 0.015, 0.01, 0.005, 0.0025)
DEFAULT_SEED = 20261016
DEFAULT_SIMS = 4000
NOISE_FLOOR_SIMS = 4000
NOISE_FLOOR_GRID = verdict.NOISE_FLOOR_GRID
DEFAULT_CAP = 10
SHAPES = ("proportional", "room")


@dataclass(frozen=True)
class SizeResult:
    reps: int
    packages: int
    defects: int
    growth_units: int
    alpha: float | None
    power_proportional: float | None
    power_room: float | None
    identical_loss: float
    identical_loss_upper: float
    no_loss_at_drop: float | None
    no_loss_at_drop_upper: float | None
    excluded_proportional: float = 0
    excluded_room: float = 0


@dataclass(frozen=True)
class SearchResult:
    tried: tuple[SizeResult, ...]
    result: SizeResult | None
    cleared_guard_decides: bool
    cleared_guard_reason: str
    stress_case: float | None
    state: str

    def as_dict(self) -> dict:
        result = asdict(self)
        # Zero exclusions are implicit, preserving the approved reference output.
        for row in (*result["tried"], result["result"]):
            if row is not None:
                for key in ("excluded_proportional", "excluded_room"):
                    if row[key] == 0:
                        del row[key]
        return result


def level_search(
    upper_bounds: Callable[[float], tuple[float, float]],
) -> float | None:
    """Return the first ladder level whose two Wilson upper bounds hold."""
    for alpha in ALPHA_LADDER:
        identical, at_drop = upper_bounds(alpha)
        if identical <= 0.05 and at_drop <= 0.05:
            return alpha
    return None


class _SizeEvaluation:
    """Lazy, size-local draws and judge results; no statistical rule lives here."""

    def __init__(self, scenario, layout, *, reps, seed, sims, drop, floor, draw_stream=None):
        self.scenario, self.layout = scenario, layout
        self.reps, self.seed, self.sims, self.drop, self.floor = reps, seed, sims, drop, floor
        self.stream = draw_stream or _StudyDrawStream(
            scenario, seed=seed, sims=sims, layout=layout,
            requests={"null": (0, "room"), **{shape: (drop, shape) for shape in SHAPES}},
        )
        self.stream.advance(reps)
        self.draws: dict[str, verdict.PreparedJudge | None] = {}
        self.judged: dict[tuple[str, float, bool], verdict.JudgeCounts] = {}

    def outcomes(self, shape, alpha, decides):
        if shape not in self.draws:
            drawn = self.stream.snapshot(shape)
            self.draws[shape] = None if drawn is None else verdict.prepare_judge(drawn)
        prepared = self.draws[shape]
        if prepared is None:
            return None
        key = (shape, alpha, decides)
        if key not in self.judged:
            self.judged[key] = verdict.judge(
                prepared, verdict.VerdictRules(alpha, decides, floor=self.floor), named=False,
            )
        return self.judged[key]

    def null(self, alpha, decides):
        outcomes = self.outcomes("null", alpha, decides)
        hits = int(np.count_nonzero(outcomes.quality_loss))
        return hits / self.sims, stats.mc_upper_bound(hits, self.sims)

    def measure(self, alpha, decides, growth_units):
        identical, identical_upper = self.null(alpha, decides)
        powers = []
        no_loss_rates = []
        no_loss_bounds = []
        exclusions = []
        for shape in SHAPES:
            outcomes = self.outcomes(shape, alpha, decides)
            if outcomes is None:
                powers.append(None)
                exclusions.append(1.0)
            else:
                eligible = len(outcomes.quality_loss)
                exclusions.append((self.sims - eligible) / self.sims)
                powers.append(
                    np.count_nonzero(outcomes.main_recall_loss) / eligible,
                )
                hits = int(np.count_nonzero(outcomes.no_loss))
                no_loss_rates.append(hits / eligible)
                no_loss_bounds.append(stats.mc_upper_bound(hits, eligible))
        return SizeResult(
            reps=self.reps, packages=self.layout.package_count, defects=self.layout.defects,
            growth_units=growth_units, alpha=alpha,
            power_proportional=powers[0], power_room=powers[1],
            identical_loss=identical, identical_loss_upper=identical_upper,
            no_loss_at_drop=max(no_loss_rates, default=None),
            no_loss_at_drop_upper=max(no_loss_bounds, default=None),
            excluded_proportional=exclusions[0], excluded_room=exclusions[1],
        )

    def choose(self, decides, growth_units):
        def bounds(alpha):
            _, upper = self.null(alpha, decides)
            if upper > 0.05:
                return upper, math.inf
            measured = self.measure(alpha, decides, growth_units)
            return upper, (
                math.inf if measured.no_loss_at_drop_upper is None
                else measured.no_loss_at_drop_upper
            )

        alpha = level_search(bounds)
        # Even a failed size reports both powers and rates at the tightest level.
        measured = self.measure(
            ALPHA_LADDER[-1] if alpha is None else alpha, decides, growth_units,
        )
        return replace(measured, alpha=alpha)


def _enough_power(measured: SizeResult) -> bool:
    powers = (measured.power_proportional, measured.power_room)
    return any(power is not None for power in powers) and all(
        power is None or power >= 0.8 for power in powers
    )


def search(
    scenario: Scenario, *, seed: int = DEFAULT_SEED, sims: int = DEFAULT_SIMS,
    cap: int = DEFAULT_CAP, layout: Layout = REFERENCE_LAYOUT,
    drop: float = verdict.LOSS_BOUND, floor: int = verdict.FLOOR,
) -> SearchResult:
    """Search repetitions, then growth units, using judge alone for all outcomes."""
    for name, value, minimum in (
        ("cap", cap, 3), ("sims", sims, 1), ("floor", floor, verdict.FLOOR),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer at least {minimum}")
    growth_defects = sum(layout.growth_unit)
    initial_units = max(0, math.ceil((floor - layout.defects) / growth_defects))
    first_layout = layout.grown(initial_units)
    sizes = [(rep, initial_units, first_layout) for rep in range(3, cap + 1)]
    units = initial_units + 1
    while layout.grown(units).defects <= 200:
        sizes.append((cap, units, layout.grown(units)))
        units += 1
    tried = []
    found = None
    evaluation = None
    prefix_stream = None
    for reps, growth_units, current in sizes:
        if current.defects > 200:
            break
        grown_scenario = scenario
        growth_count = current.defects - layout.defects
        if scenario.growth_clearance_rate is not None and growth_count:
            original_rates = (
                scenario.clearance_rate if isinstance(scenario.clearance_rate, tuple)
                else (scenario.clearance_rate,) * scenario.clearance_count
            )
            grown_scenario = replace(
                scenario, clearance_count=scenario.clearance_count + growth_count,
                clearance_rate=original_rates + (scenario.growth_clearance_rate,) * growth_count,
            )
        evaluation = _SizeEvaluation(
            grown_scenario, current, reps=reps, seed=seed, sims=sims, drop=drop, floor=floor,
            draw_stream=prefix_stream if growth_units == initial_units else None,
        )
        prefix_stream = evaluation.stream if growth_units == initial_units else None
        measured = evaluation.choose(False, growth_units)
        tried.append(measured)
        if measured.alpha is not None and _enough_power(measured):
            found = measured
            break

    decides = False
    reason = "no size reached both bounds and 80% power under every attainable shape"
    if found is not None:
        if (
            evaluation.scenario.clearance_count == 0
            or not np.any(evaluation.scenario.clearance_rate)
        ):
            # With no possible clear, enabling the guard changes no outcome.
            decides = True
            reason = "the guard cannot fire; both bounds and powers hold at the chosen level"
        else:
            deciding = evaluation.choose(True, found.growth_units)
            if deciding.alpha is not None and _enough_power(deciding):
                decides = True
                found = deciding
                reason = "both 5% bounds and both powers hold with the guard deciding"
            else:
                reason = (
                    "no ladder level holds both 5% bounds and 80% power "
                    "with the cleared guard deciding"
                )
    state = "reached" if found is not None else "not reached"
    if tried and all(
        row.power_proportional is None and row.power_room is None for row in tried
    ):
        state = "not attainable"
    return SearchResult(
        tried=tuple(tried), result=found, cleared_guard_decides=decides,
        cleared_guard_reason=reason,
        stress_case=(
            stress_case(
                np.full(scenario.code_count, scenario.code_rate),
                found.reps if found is not None else tried[-1].reps,
            ) if scenario.code_count and tried else None
        ),
        state=state,
    )


def scenario_inputs(
    scenario: Scenario, *, seed: int = DEFAULT_SEED, sims: int = DEFAULT_SIMS,
    cap: int = DEFAULT_CAP, layout: Layout = REFERENCE_LAYOUT,
    drop: float = verdict.LOSS_BOUND, floor: int = verdict.FLOOR,
) -> dict:
    """Every input or its source, shared by the text and JSON command outputs."""
    return {
        "rate_distribution": (
            scenario.rates if isinstance(scenario.rates, str)
            else getattr(scenario.rates, "__name__", "supplied rate draw")
        ),
        "shock_sd": scenario.sd,
        "marginal_rate_rule": (
            "E[logistic(a + sigma*Z)] = p; 40-node Gauss-Hermite, "
            "3,999-rate intercept table; identical arms share intercepts"
        ),
        "layout": {
            "packages": list(layout.packages), "growth_unit": list(layout.growth_unit),
            "defects": layout.defects, "package_count": layout.package_count,
            "placement": "rates shuffled among defects independently per simulated study",
        },
        "false_alarm_model": {
            "distribution": "poisson" if scenario.fa_size is None else "gamma-poisson",
            "mean": scenario.fa_mean, "size": scenario.fa_size,
            "variance": (
                scenario.fa_mean if scenario.fa_size is None
                else scenario.fa_mean + scenario.fa_mean**2 / scenario.fa_size
            ),
        },
        "stops": {
            "probability": scenario.stop_rate,
            "source": "Bernoulli per package run and arm; stopped alarms thinned by U(0,1)",
        },
        "clearances": {
            "defects": scenario.clearance_count, "probability": scenario.clearance_rate,
            "source": "independent Bernoulli per chosen defect, run and arm",
        },
        "code_produced_defects": {
            "defects": scenario.code_count, "off_rate": scenario.code_rate, "on_rate": 1,
        },
        "drop": drop,
        "shapes": list(SHAPES),
        "alpha_ladder": list(ALPHA_LADDER),
        "deciding_rules": [
            "recall loss: main and sensitivity", "false-alarm rise: main and sensitivity",
            "code-defect guard: main", "cleared guard: only if both bounds and powers hold",
        ],
        "sims": sims,
        "seed": seed,
        "cap": cap,
        "floor": floor,
        "numpy_version": np.__version__,
    }


def _printed_number(value):
    return "not attainable" if value is None else f"{value:.6f}"


def _size_line(row: SizeResult) -> str:
    return (
        f"reps={row.reps} packages={row.packages} defects={row.defects} "
        f"growth_units={row.growth_units} alpha={'none' if row.alpha is None else row.alpha} "
        f"evaluated_alpha={ALPHA_LADDER[-1] if row.alpha is None else row.alpha} "
        f"power_proportional={_printed_number(row.power_proportional)} "
        f"power_room={_printed_number(row.power_room)} "
        f"identical_loss={row.identical_loss:.6f} "
        f"identical_loss_upper={row.identical_loss_upper:.6f} "
        f"no_loss_at_drop={_printed_number(row.no_loss_at_drop)} "
        f"no_loss_at_drop_upper={_printed_number(row.no_loss_at_drop_upper)}"
        + "".join(
            f" excluded_{shape}={getattr(row, f'excluded_{shape}'):.6f}"
            for shape in SHAPES if getattr(row, f"excluded_{shape}")
        )
    )


def render_result(
    scenario: Scenario, result: SearchResult, *, seed: int = DEFAULT_SEED,
    sims: int = DEFAULT_SIMS, cap: int = DEFAULT_CAP, layout: Layout = REFERENCE_LAYOUT,
    drop: float = verdict.LOSS_BOUND, floor: int = verdict.FLOOR,
) -> str:
    inputs = scenario_inputs(
        scenario, seed=seed, sims=sims, cap=cap, layout=layout, drop=drop, floor=floor,
    )
    lines = [f"Scenario {scenario.name}"]
    lines.extend(f"{name}: {json.dumps(value, sort_keys=True)}" for name, value in inputs.items())
    lines.extend(_size_line(row) for row in result.tried)
    place = "deciding" if result.cleared_guard_decides else "named only"
    lines.append(f"cleared guard: {place}; {result.cleared_guard_reason}")
    if scenario.clearance_count and result.result is not None:
        null_rate = cleared_null_rate(
            scenario.clearance_rate, scenario.clearance_count, result.result.reps,
        )
        lines.append(f"cleared guard null rate: {null_rate:.6f}")
    if result.stress_case is not None:
        lines.append(f"stress case (shown, never bounded): {result.stress_case:.6f}")
    lines.append(f"result: {result.state}")
    if result.result is not None:
        lines.append("chosen " + _size_line(result.result))
    return "\n".join(lines)


def validate_noise_floor_recall(defect_packages, counted_runs, package_runs):
    """Refuse layouts whose main recall cannot have a package interval.

    Inputs are the shared verdict's validated main-figure counts, with arm
    first and defect/package last. Recall retains only defects counted in
    both arms; clean packages cannot provide recall degrees of freedom.
    """
    if not np.any(package_runs[1] > 0):
        raise ValueError("main recall is not computable: every on-arm run is uncounted")
    retained = np.all(counted_runs > 0, axis=0)
    if not np.any(retained):
        raise ValueError("main recall is not computable: no retained defect in both arms")
    if np.unique(defect_packages[retained]).size < 2:
        raise ValueError("main recall is not computable: fewer than two retained packages")


def noise_floor(layout, rates, sd, *, alpha, seed, reps, sims):
    """Find the first grid drop with 80% power on the observed study's layout.

    Rates follow the layout's package order, with each package's defects
    contiguous. Repetitions are either one positive integer or the main
    counted-run counts for each arm and package, shaped (2, packages).
    Fixed rates keep their package identities; the reference simulator's
    random permutation of population rates does not apply to this study.
    """
    rates = _sim_rates(rates)
    if rates.ndim != 1 or rates.size != layout.defects:
        raise ValueError("rates must contain one probability per layout defect")
    sd = _sim_number(sd, "sd")
    seed = _sim_integer(seed, "seed")
    sims = _sim_integer(sims, "sims", minimum=1)
    rules = verdict.VerdictRules(alpha, cleared_guard_decides=False)
    try:
        repetitions = np.asarray(reps, dtype=object)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("reps must be an integer or have shape (2, packages)") from exc
    if repetitions.ndim == 0:
        count = _sim_integer(repetitions.item(), "reps", minimum=1)
        repetitions = np.full((2, layout.package_count), count, dtype=np.int64)
    elif repetitions.shape == (2, layout.package_count):
        repetitions = np.array([
            [_sim_integer(value, "reps") for value in arm]
            for arm in repetitions.tolist()
        ], dtype=np.int64)
    else:
        raise ValueError("reps must be an integer or have shape (2, packages)")

    defect_packages = np.repeat(np.arange(layout.package_count), layout.packages)
    validate_noise_floor_recall(
        defect_packages, repetitions[:, defect_packages], repetitions,
    )
    package_runs = np.broadcast_to(
        repetitions[None, :, None, :], (sims, 2, 2, layout.package_count),
    )
    false_alarms = np.zeros_like(package_runs)
    table = stats.intercept_table(sd)
    off_intercepts = stats.intercept(table, rates)
    maximum_reps = int(np.max(repetitions))
    largest_attainable = None
    for points in NOISE_FLOOR_GRID:
        powers = []
        for shape in SHAPES:
            on_rates = drop_rates(rates, points / 100, shape)
            if on_rates is None:
                continue
            largest_attainable = points
            intercepts = np.stack((off_intercepts, stats.intercept(table, on_rates)))
            detected = np.zeros((sims, 2, layout.defects), dtype=np.int64)
            # Resetting the seed shares the same shocks and uniforms across
            # grid points and shapes, without moving rates between packages.
            rng = np.random.Generator(np.random.PCG64(seed))
            for repetition in range(maximum_reps):
                draws = _draw_detections(
                    rng, intercepts, sd, (sims, 2, layout.package_count), defect_packages,
                )
                counted = (repetitions > repetition)[:, defect_packages]
                detected += draws & counted
            simulated = _main_figure_stats(
                detected, package_runs, defect_packages, false_alarms,
            )
            outcomes = verdict.judge(simulated, rules, named=False)
            powers.append(np.count_nonzero(outcomes.main_recall_loss) / sims)
        if powers and min(powers) >= 0.8:
            return points
    return (
        verdict.above_noise_floor(largest_attainable) if largest_attainable is not None
        else "not attainable"
    )


class NoiseFloorRecord(ReviewModel):
    """A strict stored result; reading it never performs a simulation."""

    noise_floor_schema: int
    study: str
    provider: str
    model: str
    runs_digest: str
    seed: int = Field(ge=0)
    sims: int = Field(ge=1)
    numpy_version: str
    grid: list[float]
    result: float | str

    @field_validator("result")
    @classmethod
    def _grid_result(cls, value: float | str) -> float | str:
        verdict.validate_noise_floor_points(value)
        return value

    @field_validator("noise_floor_schema")
    @classmethod
    def _supported_schema(cls, value: int) -> int:
        if value != 1:
            raise ValueError(f"noise_floor_schema {value} is not supported; expected 1")
        return value


def read_noise_floor(path: Path | str) -> NoiseFloorRecord:
    return NoiseFloorRecord.model_validate_json(Path(path).read_bytes())


def runs_digest(run_dirs: Iterable[Path | str], *, relative_to: Path | str) -> str:
    """Hash relative folder/parsed-scorecard-digest pairs, independent of JSON spelling."""
    root = Path(relative_to).resolve()
    pairs = []
    for folder in run_dirs:
        run = Path(folder).resolve()
        relative = Path(os.path.relpath(run, root)).as_posix()
        card = json.loads((run / "scorecard.json").read_bytes())
        pairs.append((relative, digest.canonical_sha256(card)))
    return digest.canonical_sha256(sorted(pairs))
