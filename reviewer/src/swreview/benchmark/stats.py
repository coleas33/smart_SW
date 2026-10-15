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
    alpha = _finite(alpha, "alpha")
    if not 0 < alpha <= 0.5:
        raise ValueError("alpha must be inside (0, 0.5]")
    sides = _integer(sides, "sides")
    if sides not in (1, 2):
        raise ValueError("sides must be 1 or 2")
    sums_array = _vector(sums, "sums")
    weights_array = _vector(weights, "weights")
    if sums_array.shape != weights_array.shape:
        raise ValueError("weights must have the same length as sums")
    if np.any(weights_array < 0):
        raise ValueError("weights must be nonnegative")
    if np.any((weights_array == 0) & (sums_array != 0)):
        raise ValueError("sums must be zero for packages with zero weights")
    retained = weights_array > 0
    sums_array, weights_array = sums_array[retained], weights_array[retained]
    packages = len(sums_array)
    df = packages - 1
    if packages == 0:
        return Interval(None, None, None, df, packages, False)
    total_weight = math.fsum(weights_array)
    estimate = math.fsum(sums_array) / total_weight
    if packages < 2:
        return Interval(estimate, None, None, df, packages, False)
    package_means = sums_array / weights_array
    if np.all(package_means == package_means[0]):
        # Summing identical decimal means can round D away from that common mean.
        # Their variance is still zero; a tolerance would erase real small differences.
        return Interval(estimate, None, None, df, packages, False)
    residuals = sums_array - estimate * weights_array
    se = math.sqrt(packages / df * math.fsum(residuals * residuals)) / total_weight
    if se == 0:
        return Interval(estimate, None, None, df, packages, False)
    margin = t_quantile(df, 1 - alpha / sides) * se
    return Interval(estimate, estimate - margin, estimate + margin, df, packages, True)


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
        shocks = sigma * _GH_POINTS
        # At these endpoints every quadrature node is below/above the target logit.
        lower, upper = logits - np.max(shocks), logits - np.min(shocks)
        while np.max(upper - lower) > 1e-10:
            midpoint = (lower + upper) / 2
            probabilities = np.exp(-np.logaddexp(0, -(midpoint[:, None] + shocks)))
            marginals = probabilities @ _GH_WEIGHTS
            lower = np.where(marginals < rates, midpoint, lower)
            upper = np.where(marginals < rates, upper, midpoint)
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
