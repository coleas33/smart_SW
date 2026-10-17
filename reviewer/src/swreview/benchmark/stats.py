"""Pure package statistics shared by the verdict, simulator and pilot (T223).

The Student t CDF uses the finite series for integer degrees of freedom from
Abramowitz and Stegun 26.7.3 and 26.7.4; its inverse needs only bisection.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

import numpy as np
from numpy.typing import ArrayLike, NDArray

GH_NODES = 40
_GH_POINTS, _GH_WEIGHTS = np.polynomial.hermite_e.hermegauss(GH_NODES)
_GH_WEIGHTS = _GH_WEIGHTS / math.sqrt(2 * math.pi)

InterceptTable = tuple[NDArray[np.float64], NDArray[np.float64]]


def _integer(value: int, name: str, minimum: int = 1) -> int:
    try:
        if isinstance(value, (bool, np.bool_)):
            raise TypeError
        result = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer at least {minimum}") from exc
    if result < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}")
    return result


def _finite(value: float, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def t_cdf(t: float, df: int) -> float:
    """Student t probability through ``t`` for positive integer ``df``."""
    df = _integer(df, "df")
    try:
        t = float(t)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("t must be a real number") from exc
    if math.isnan(t):
        raise ValueError("t must not be NaN")
    if math.isinf(t):
        return 0.0 if t < 0 else 1.0

    theta = math.atan(abs(t) / math.sqrt(df))
    sine, cosine = math.sin(theta), math.cos(theta)
    cosine_squared = cosine * cosine
    term = total = 1.0
    if df % 2 == 0:
        for j in range(1, df // 2):
            term *= (2 * j - 1) / (2 * j) * cosine_squared
            total += term
        area = sine * total
    elif df == 1:
        area = 2 * theta / math.pi
    else:
        for j in range(1, (df - 1) // 2):
            term *= (2 * j) / (2 * j + 1) * cosine_squared
            total += term
        area = 2 / math.pi * (theta + sine * cosine * total)
    positive_cdf = (1 + min(area, 1.0)) / 2
    return 1 - positive_cdf if t < 0 else positive_cdf


def t_quantile(df: int, p: float) -> float:
    """Invert :func:`t_cdf`, doubling the bracket from 1 then bisecting to 1e-10."""
    df = _integer(df, "df")
    p = _finite(p, "p")
    if not 0 < p < 1:
        raise ValueError("p must be inside (0, 1)")
    return _t_quantile(df, p)


@cache
def _t_quantile(df: int, p: float) -> float:
    """Cache only validated arguments: bools must never hit an integer cache key."""
    if p == 0.5:
        return 0.0

    target = 1 - p if p < 0.5 else p
    lower, upper = 0.0, 1.0
    while t_cdf(upper, df) < target:
        lower, upper = upper, 2 * upper
    while upper - lower > 1e-10:
        midpoint = (lower + upper) / 2
        if midpoint == lower or midpoint == upper:
            break  # The bracket can be narrower than a float's spacing in the far tails.
        if t_cdf(midpoint, df) < target:
            lower = midpoint
        else:
            upper = midpoint
    result = (lower + upper) / 2
    return -result if p < 0.5 else result


@dataclass(frozen=True)
class Interval:
    """An interval over retained packages; absent bounds mean not computable."""

    estimate: float | None
    lower: float | None
    upper: float | None
    df: int
    packages: int
    computable: bool


@dataclass(frozen=True)
class PackageMoments:
    """Alpha-independent interval inputs, with packages on the reduced axis."""

    estimate: NDArray[np.float64]
    se: NDArray[np.float64]
    df: NDArray[np.int64]
    packages: NDArray[np.int64]
    computable: NDArray[np.bool_]


@dataclass(frozen=True)
class BatchInterval:
    """Package intervals over arbitrary leading axes; absent values are NaN."""

    estimate: NDArray[np.float64]
    lower: NDArray[np.float64]
    upper: NDArray[np.float64]
    df: NDArray[np.int64]
    packages: NDArray[np.int64]
    computable: NDArray[np.bool_]


@np.errstate(over="ignore", invalid="ignore")
def _fsum_last(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Apply math.fsum's expansion arithmetic to every row together.

    NumPy's reduction may round away small residuals and alter a strict verdict
    boundary. The loops traverse packages and the short float expansion, never
    studies. The final half-even correction matches math.fsum on IEEE doubles.
    """
    shape = values.shape[:-1]
    columns = values.shape[-1]
    rows = math.prod(shape)
    inputs = values.reshape(rows, columns)
    partials = np.zeros((columns, rows), dtype=float)
    count = np.zeros(rows, dtype=np.int64)
    inf_sum = np.zeros(rows, dtype=float)
    special_sum = np.zeros(rows, dtype=float)
    row = np.arange(rows)
    for column in range(columns):
        x = inputs[:, column].copy()
        special = ~np.isfinite(x)
        if np.any(special):
            infinite = np.isinf(x)
            inf_sum[infinite] += x[infinite]
            special_sum[special] += x[special]
            count[special] = 0
            x[special] = 0
        if not np.any(x):
            continue
        stored = np.zeros(rows, dtype=np.int64)
        for index in range(int(np.max(count, initial=0))):
            active = index < count
            y = np.where(active, partials[index], 0)
            swap = np.abs(x) < np.abs(y)
            larger, smaller = np.where(swap, y, x), np.where(swap, x, y)
            hi = larger + smaller
            if np.any(~np.isfinite(hi)):
                raise OverflowError("intermediate overflow in fsum")
            lo = smaller - (hi - larger)
            keep = active & (lo != 0)
            partials[stored[keep], row[keep]] = lo[keep]
            stored += keep
            x = np.where(active, hi, x)
        keep = x != 0
        partials[stored[keep], row[keep]] = x[keep]
        count = stored + keep
    remaining = np.maximum(count - 1, 0)
    hi = np.zeros(rows, dtype=float)
    present = count > 0
    hi[present] = partials[remaining[present], row[present]]
    lo = np.zeros(rows, dtype=float)
    active = remaining > 0
    while np.any(active):
        remaining[active] -= 1
        y = partials[remaining, row]
        next_hi = hi + y
        next_lo = y - (next_hi - hi)
        hi = np.where(active, next_hi, hi)
        lo = np.where(active, next_lo, lo)
        active &= lo == 0
        active &= remaining > 0
    previous = partials[np.maximum(remaining - 1, 0), row] if columns else hi
    correct = (remaining > 0) & (((lo < 0) & (previous < 0)) | ((lo > 0) & (previous > 0)))
    doubled = lo * 2
    rounded = hi + doubled
    hi = np.where(correct & (rounded - hi == doubled), rounded, hi)
    if np.any(np.isnan(inf_sum)):
        raise ValueError("-inf + inf in fsum")
    hi = np.where(special_sum != 0, special_sum, hi)
    return hi.reshape(shape)


def prepare_package_intervals(sums: ArrayLike, weights: ArrayLike) -> PackageMoments:
    """Compute ratio-linearised moments for all studies without row iteration."""
    arrays = []
    for values, name in ((sums, "sums"), (weights, "weights")):
        try:
            array = np.asarray(values, dtype=float)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be finite arrays with a final package axis") from exc
        if array.ndim < 1 or not np.all(np.isfinite(array)):
            raise ValueError(f"{name} must be finite arrays with a final package axis")
        arrays.append(array)
    sums_array, weights_array = arrays
    if sums_array.shape != weights_array.shape:
        raise ValueError("weights must have the same shape as sums")
    if np.any(weights_array < 0):
        raise ValueError("weights must be nonnegative")
    if np.any((weights_array == 0) & (sums_array != 0)):
        raise ValueError("sums must be zero for packages with zero weights")
    retained = weights_array > 0
    packages = np.sum(retained, axis=-1, dtype=np.int64)
    df = packages - 1
    total_weight = _fsum_last(weights_array)
    estimate = np.divide(
        _fsum_last(sums_array), total_weight,
        out=np.full(packages.shape, np.nan), where=packages > 0,
    )
    means = np.divide(
        sums_array, weights_array, out=np.zeros_like(sums_array), where=retained,
    )
    if sums_array.shape[-1]:
        first = np.take_along_axis(means, np.argmax(retained, axis=-1)[..., None], axis=-1)
        equal = np.all(~retained | (means == first), axis=-1)
    else:
        equal = np.ones(packages.shape, dtype=bool)
    residuals = np.where(retained, sums_array - estimate[..., None] * weights_array, 0)
    variance = np.divide(
        packages, df, out=np.zeros(packages.shape, dtype=float), where=packages > 1,
    ) * _fsum_last(residuals * residuals)
    se = np.divide(
        np.sqrt(variance), total_weight,
        out=np.zeros(packages.shape, dtype=float), where=packages > 0,
    )
    computable = (packages > 1) & ~equal & (se != 0)
    return PackageMoments(estimate, se, df, packages, computable)


def _interval_parameters(alpha: float, sides: int) -> tuple[float, int]:
    alpha = _finite(alpha, "alpha")
    if not 0 < alpha <= 0.5:
        raise ValueError("alpha must be inside (0, 0.5]")
    sides = _integer(sides, "sides")
    if sides not in (1, 2):
        raise ValueError("sides must be 1 or 2")
    return alpha, sides


def package_intervals_from_moments(
    moments: PackageMoments, alpha: float, sides: int = 1,
) -> BatchInterval:
    """Apply one tail level to prepared moments; invert t only once per df."""
    alpha, sides = _interval_parameters(alpha, sides)
    quantiles = np.zeros(moments.df.shape, dtype=float)
    for df in np.unique(moments.df[moments.computable]):
        quantiles[moments.df == df] = t_quantile(int(df), 1 - alpha / sides)
    margin = quantiles * moments.se
    lower = np.where(moments.computable, moments.estimate - margin, np.nan)
    upper = np.where(moments.computable, moments.estimate + margin, np.nan)
    return BatchInterval(
        moments.estimate, lower, upper, moments.df, moments.packages, moments.computable,
    )


def package_intervals(
    sums: ArrayLike, weights: ArrayLike, alpha: float, sides: int = 1,
) -> BatchInterval:
    """Ratio-linearised intervals across the final package axis of an array."""
    return package_intervals_from_moments(prepare_package_intervals(sums, weights), alpha, sides)


def _vector(values: ArrayLike, name: str) -> NDArray[np.float64]:
    try:
        result = np.asarray(values, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite one-dimensional sequence") from exc
    if result.ndim != 1 or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite one-dimensional sequence")
    return result


def package_interval(
    sums: Sequence[float] | NDArray[np.float64],
    weights: Sequence[float] | NDArray[np.float64],
    alpha: float,
    sides: int = 1,
) -> Interval:
    """Ratio-linearised t interval, with one entry per package and ``on - off`` sums.

    Zero-weight packages hold no retained units and are omitted. With no retained
    package even the estimate is absent; with fewer than two, or SE zero, both
    bounds are absent. A two-sided interval allocates ``alpha / 2`` to each tail.
    """
    sums_array = _vector(sums, "sums")
    weights_array = _vector(weights, "weights")
    if sums_array.shape != weights_array.shape:
        raise ValueError("weights must have the same length as sums")
    batch = package_intervals_from_moments(
        prepare_package_intervals(sums_array[None], weights_array[None]), alpha, sides,
    )
    estimate, lower, upper = (
        None if np.isnan(values[0]) else float(values[0])
        for values in (batch.estimate, batch.lower, batch.upper)
    )
    return Interval(
        estimate, lower, upper, int(batch.df[0]), int(batch.packages[0]), bool(batch.computable[0]),
    )


def mc_upper_bound(hits: int, n: int) -> float:
    """One-sided 95% Wilson upper bound, with the contract's z = 1.6448536."""
    n = _integer(n, "n")
    hits = _integer(hits, "hits", minimum=0)
    if hits > n:
        raise ValueError("hits must be between 0 and n")
    p, z = hits / n, 1.6448536
    return (p + z**2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / (
        1 + z**2 / n
    )


@cache
def intercept_table(sigma: float) -> InterceptTable:
    """Solve once per shock SD at rates j/4000, j=1,...,3999.

    The returned pair is (rates, intercepts), both read-only arrays. Marginals
    use 40-node Gauss-Hermite quadrature for a standard normal variable.
    """
    sigma = _finite(sigma, "sigma")
    if sigma < 0:
        raise ValueError("sigma must be nonnegative")
    rates = np.arange(1, 4000, dtype=float) / 4000
    logits = np.log(rates / (1 - rates))
    if sigma == 0:
        solutions = logits
    else:
        with np.errstate(over="ignore"):
            shocks = sigma * _GH_POINTS
        # At these endpoints every quadrature node is below/above the target logit.
        lower, upper = logits - np.max(shocks), logits - np.min(shocks)
        if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
            raise ValueError("sigma is too large to form a finite intercept bracket")

        def marginal(intercepts: NDArray[np.float64]) -> NDArray[np.float64]:
            probabilities = np.exp(-np.logaddexp(0, -(intercepts[:, None] + shocks)))
            return probabilities @ _GH_WEIGHTS

        # Verify the bracket against the implemented quadrature, expanding only
        # if rounding puts an endpoint on the wrong side of a target.
        for _ in range(200):
            too_high, too_low = marginal(lower) > rates, marginal(upper) < rates
            if not np.any(too_high | too_low):
                break
            # A sub-ulp shock can round both endpoints to the same logit.
            width = np.maximum(upper - lower, 1.0)
            lower = np.where(too_high, lower - width, lower)
            upper = np.where(too_low, upper + width, upper)
            if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
                raise ValueError("sigma is too large to bracket the intercept targets")
        else:
            raise ValueError("sigma intercept targets could not be bracketed")

        for _ in range(200):
            if np.max(upper - lower) <= 1e-10:
                break
            midpoint = (lower + upper) / 2
            movable = (midpoint != lower) & (midpoint != upper)
            if not np.any(movable):
                break  # Far-tail float spacing can exceed the absolute tolerance.
            below = marginal(midpoint) < rates
            lower = np.where(movable & below, midpoint, lower)
            upper = np.where(movable & ~below, midpoint, upper)
        solutions = (lower + upper) / 2
    rates.setflags(write=False)
    solutions.setflags(write=False)
    return rates, solutions


def intercept(table: InterceptTable, rates: ArrayLike) -> float | NDArray[np.float64]:
    """Interpolate intercepts, mapping exact endpoint rates to never/always."""
    try:
        rates_array = np.asarray(rates, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("rates must be finite probabilities inside [0, 1]") from exc
    if not np.all(np.isfinite(rates_array)) or np.any((rates_array < 0) | (rates_array > 1)):
        raise ValueError("rates must be finite probabilities inside [0, 1]")
    values = np.interp(rates_array, *table)
    values = np.where(rates_array == 0, -np.inf, np.where(rates_array == 1, np.inf, values))
    return float(values) if rates_array.ndim == 0 else values
