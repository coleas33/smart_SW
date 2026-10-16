"""The package statistics contract: V-1 to V-5 and V-26 (T222)."""

from __future__ import annotations

import ast
import inspect
import math
import sys
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from swreview.benchmark import stats


@pytest.mark.parametrize(
    ("df", "p", "expected"),
    [
        (16, 0.975, 2.119905),
        (16, 0.99, 2.583487),
        (16, 0.995, 2.920782),
        (33, 0.975, 2.034515),
        (50, 0.975, 2.008559),
        (4, 0.975, 2.776445),
    ],
)
def test_v1_t_quantile_matches_six_pinned_values(df: int, p: float, expected: float) -> None:
    assert round(stats.t_quantile(df, p), 6) == expected


def test_v1_one_degree_of_freedom_is_the_cauchy_quantile() -> None:
    assert stats.t_quantile(1, 0.975) == pytest.approx(math.tan(0.475 * math.pi), abs=1e-10)


@pytest.mark.parametrize("df", [1, 2, 3, 4, 16, 33, 50])
@pytest.mark.parametrize("t", [0.0, 0.125, 1.0, 3.0, 20.0])
def test_v1_t_cdf_is_symmetric(t: float, df: int) -> None:
    assert stats.t_cdf(-t, df) == pytest.approx(1 - stats.t_cdf(t, df), abs=1e-15)
    assert stats.t_cdf(0.0, df) == 0.5


@pytest.mark.parametrize("df", [1, 2, 3, 16, 33, 50])
@pytest.mark.parametrize("p", [0.001, 0.025, 0.25, 0.5, 0.75, 0.975, 0.999])
def test_v1_quantile_inverts_both_tails(df: int, p: float) -> None:
    quantile = stats.t_quantile(df, p)
    assert stats.t_cdf(quantile, df) == pytest.approx(p, abs=1e-10)
    assert quantile == pytest.approx(-stats.t_quantile(df, 1 - p), abs=1e-10)


def test_v1_stats_imports_only_numpy_and_the_standard_library() -> None:
    tree = ast.parse(inspect.getsource(stats))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert "scipy" not in roots
    assert roots <= sys.stdlib_module_names | {"numpy"}


def test_v2_equal_weights_are_the_paired_t_interval_on_four_package_means() -> None:
    # Package means -1, 0, 1, 2: mean 1/2, sample variance 5/3, SE sqrt(5/12).
    interval = stats.package_interval([-2, 0, 2, 4], [2, 2, 2, 2], alpha=0.05, sides=1)
    margin = 2.353363434801827 * math.sqrt(5 / 12)  # t(3, .95), independently tabulated.

    assert interval.estimate == pytest.approx(0.5)
    assert interval.lower == pytest.approx(0.5 - margin, abs=1e-10)
    assert interval.upper == pytest.approx(0.5 + margin, abs=1e-10)
    assert interval.df == 3
    assert interval.packages == 4
    assert interval.computable is True
    with pytest.raises(FrozenInstanceError):
        interval.estimate = 0.0


def test_v2_weights_one_and_two_use_the_ratio_standard_error() -> None:
    # D = 2/6. Residuals -4/3, -2/3, 2/3, 4/3 have sum of squares 40/9.
    # SE = sqrt((4/3)*(40/9))/6 = sqrt(40/243), not the SE of package means.
    interval = stats.package_interval([-1, 0, 1, 2], [1, 2, 1, 2], alpha=0.05, sides=1)
    margin = 2.353363434801827 * math.sqrt(40 / 243)

    assert interval.estimate == pytest.approx(1 / 3)
    assert interval.lower == pytest.approx(1 / 3 - margin, abs=1e-10)
    assert interval.upper == pytest.approx(1 / 3 + margin, abs=1e-10)
    assert (interval.upper - interval.estimate) / 2.353363434801827 == pytest.approx(
        math.sqrt(40 / 243), abs=1e-10
    )


def test_v2_two_sided_interval_splits_alpha_between_the_tails() -> None:
    sums, weights = [-1, 0, 1, 2], [1, 2, 1, 2]
    two_sided = stats.package_interval(sums, weights, alpha=0.05, sides=2)
    one_sided = stats.package_interval(sums, weights, alpha=0.025, sides=1)

    assert two_sided == one_sided
    margin = 3.182446305283708 * math.sqrt(40 / 243)  # t(3, .975).
    assert two_sided.lower == pytest.approx(1 / 3 - margin, abs=1e-10)
    assert two_sided.upper == pytest.approx(1 / 3 + margin, abs=1e-10)


def test_v2_alpha_half_is_valid_and_does_not_make_nonzero_se_uncomputable() -> None:
    interval = stats.package_interval([0, 1], [1, 1], alpha=0.5, sides=1)

    assert interval.computable is True
    assert interval.lower == interval.estimate == interval.upper == 0.5


def test_v2_only_packages_with_retained_units_count() -> None:
    expected = stats.package_interval([-1, 2], [1, 2], alpha=0.05, sides=1)

    assert stats.package_interval([0, -1, 2], [0, 1, 2], alpha=0.05, sides=1) == expected
    assert expected.packages == 2
    assert expected.df == 1


def test_v3_no_retained_packages_has_no_estimate_or_bounds() -> None:
    for sums, weights in [([], []), ([0, 0], [0, 0])]:
        interval = stats.package_interval(sums, weights, alpha=0.05, sides=1)

        assert interval.packages == 0
        assert interval.computable is False
        assert interval.estimate is None
        assert interval.lower is None
        assert interval.upper is None


@pytest.mark.parametrize(
    ("sums", "weights", "estimate", "df"),
    [
        ([2], [2], 1.0, 0),
        ([0], [1], 0.0, 0),
        ([1, 2, 1, 2], [1, 2, 1, 2], 1.0, 3),
        ([0, 0, 0, 0], [1, 2, 1, 2], 0.0, 3),
        ([-0.1] * 3, [1] * 3, -0.1, 2),
        ([0.1, 0.2], [1, 2], 0.1, 1),
        ([-1 / 3] * 50, [1] * 50, -1 / 3, 49),
    ],
)
def test_v3_one_package_or_zero_se_has_no_bounds(
    sums: list[float], weights: list[int], estimate: float, df: int
) -> None:
    interval = stats.package_interval(sums, weights, alpha=0.05, sides=1)

    assert interval.estimate == pytest.approx(estimate)
    assert interval.df == df
    assert interval.packages == len(sums)
    assert interval.computable is False
    assert interval.lower is None
    assert interval.upper is None


def test_v3_small_real_variance_is_computable() -> None:
    interval = stats.package_interval(
        [0.1, 0.1 + 1e-14, 0.1 + 2e-14], [1, 1, 1], alpha=0.05, sides=1
    )

    assert interval.computable is True
    assert interval.lower < interval.estimate < interval.upper


@pytest.fixture(scope="module", params=[0.0, 1.0, 2.5], ids=["sd0", "sd1", "sd2.5"])
def intercept_case(request: pytest.FixtureRequest) -> tuple[float, object]:
    sigma = request.param
    return sigma, stats.intercept_table(sigma)


def test_v4_interpolated_intercepts_reproduce_gauss_hermite_marginals(
    intercept_case: tuple[float, object],
) -> None:
    sigma, table = intercept_case
    # Includes rates between table knots, so this exercises interpolation as well as solving.
    rates = np.linspace(0.001, 0.999, 2001).reshape(3, 667)
    intercepts = stats.intercept(table, rates)
    nodes, weights = np.polynomial.hermite_e.hermegauss(40)
    probabilities = np.exp(-np.logaddexp(0, -(intercepts[..., None] + sigma * nodes)))
    marginals = probabilities @ weights / math.sqrt(2 * math.pi)

    assert stats.GH_NODES == 40
    assert np.shape(intercepts) == rates.shape
    np.testing.assert_allclose(marginals, rates, atol=1e-4, rtol=0)


def test_v4_zero_sigma_intercepts_are_logits() -> None:
    rates = np.arange(1, 4000) / 4000
    intercepts = stats.intercept(stats.intercept_table(0.0), rates)

    np.testing.assert_allclose(intercepts, np.log(rates / (1 - rates)), atol=1e-10, rtol=0)


def test_v4_endpoint_rates_are_never_and_always_for_any_shock(
    intercept_case: tuple[float, object],
) -> None:
    _, table = intercept_case
    intercepts = stats.intercept(table, [0.0, 1.0])

    assert np.isneginf(intercepts[0])
    assert np.isposinf(intercepts[1])
    for shock in [-1000.0, 0.0, 1000.0]:
        probabilities = np.exp(-np.logaddexp(0, -(intercepts + shock)))
        np.testing.assert_array_equal(probabilities, [0.0, 1.0])
    assert np.isneginf(stats.intercept(table, 0.0))
    assert np.isposinf(stats.intercept(table, 1.0))


def test_v5_wilson_upper_bound_straddles_the_five_percent_gate() -> None:
    passing = stats.mc_upper_bound(176, 4000)
    failing = stats.mc_upper_bound(180, 4000)

    assert passing <= 0.05 < failing
    assert passing == pytest.approx(0.0496, abs=0.00005)
    assert failing == pytest.approx(0.0507, abs=0.00005)
    for hits, actual in [(176, passing), (180, failing)]:
        p, n, z = hits / 4000, 4000, 1.6448536
        expected = p + z**2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
        assert actual == pytest.approx(expected / (1 + z**2 / n), abs=1e-14)


@pytest.mark.parametrize("df", [0, -1, -10, 1.5, math.nan, math.inf])
def test_v26_invalid_degrees_of_freedom_name_df(df: float) -> None:
    with pytest.raises(ValueError, match=r"\bdf\b"):
        stats.t_quantile(df, 0.975)


@pytest.mark.parametrize("p", [0.0, -0.1, 1.0, 1.1, math.nan, math.inf])
def test_v26_invalid_probabilities_name_p(p: float) -> None:
    with pytest.raises(ValueError, match=r"\bp\b"):
        stats.t_quantile(4, p)


@pytest.mark.parametrize("alpha", [0.0, -0.01, 0.5001, 1.0, math.nan, math.inf])
def test_v26_invalid_interval_alpha_names_alpha(alpha: float) -> None:
    with pytest.raises(ValueError, match=r"\balpha\b"):
        stats.package_interval([0, 1], [1, 1], alpha=alpha, sides=1)


def test_v26_mismatched_weights_name_weights() -> None:
    with pytest.raises(ValueError, match=r"\bweights\b"):
        stats.package_interval([0, 1], [1], alpha=0.05, sides=1)


@pytest.mark.parametrize("n", [0, -1, 1.5, math.nan, math.inf])
def test_v26_invalid_simulation_count_names_n(n: float) -> None:
    with pytest.raises(ValueError, match=r"\bn\b"):
        stats.mc_upper_bound(0, n)


@pytest.mark.parametrize("hits", [-1, 4001, 1.5, math.nan, math.inf])
def test_v26_invalid_hits_name_hits(hits: float) -> None:
    with pytest.raises(ValueError, match=r"\bhits\b"):
        stats.mc_upper_bound(hits, 4000)


def test_batch_sum_matches_fsum_including_cancellation_and_half_even() -> None:
    rng = np.random.default_rng(13)
    values = rng.normal(size=(200, 81)) * np.exp2(rng.integers(-100, 100, size=(200, 81)))
    values[:4] = 0
    values[0, :3] = [1e16, 1, -1e16]
    values[1, :3] = [1, 2**-53, 2**-100]
    values[2, :3] = [1, 2**-53, -2**-100]
    values[3, :4] = [1, 2**-52, 2**-53, 2**-100]
    expected = np.array([math.fsum(row) for row in values])
    np.testing.assert_array_equal(stats._fsum_last(values), expected)


def test_batch_sum_matches_fsum_across_normal_and_subnormal_exponents() -> None:
    rng = np.random.default_rng(20261016)
    values = np.ldexp(rng.uniform(-1, 1, (200, 40)), rng.integers(-1074, 1023, (200, 40)))
    expected = np.array([math.fsum(row) for row in values])
    np.testing.assert_array_equal(stats._fsum_last(values), expected)


@pytest.mark.parametrize("values", [[1e308, 1e308], [-1e308, -1e308]])
def test_batch_sum_preserves_fsum_overflow(values: list[float]) -> None:
    with pytest.raises(OverflowError, match="overflow"):
        math.fsum(values)
    with pytest.raises(OverflowError, match="overflow"):
        stats._fsum_last(np.asarray([values]))


def test_batch_sum_preserves_nonfinite_fsum_results() -> None:
    values = np.array([[math.inf, 1], [-math.inf, 1], [math.nan, 1]])
    expected = np.array([math.fsum(row) for row in values])
    np.testing.assert_array_equal(stats._fsum_last(values), expected)
    with pytest.raises(ValueError, match="-inf"):
        stats._fsum_last(np.array([[math.inf, -math.inf]]))


def test_batch_interval_preserves_infinite_variance_scalar_bounds() -> None:
    with np.errstate(over="ignore"):
        expected = stats.package_interval([1e308, -1e308], [1, 1], 0.025)
        actual = stats.package_intervals([[1e308, -1e308]], [[1, 1]], 0.025)
    assert expected.computable and actual.computable[0]
    assert expected.estimate == actual.estimate[0] == 0
    assert expected.lower == actual.lower[0] == -math.inf
    assert expected.upper == actual.upper[0] == math.inf


@pytest.mark.parametrize("sides", [1, 2])
@pytest.mark.parametrize("alpha", [0.5, 0.025, 0.0025])
def test_batch_intervals_match_every_scalar_field_exactly(alpha: float, sides: int) -> None:
    rng = np.random.default_rng(981)
    weights = rng.integers(0, 3, size=(40, 2, 17)).astype(float)
    sums = rng.normal(size=weights.shape) * weights
    weights[0] = 0
    weights[1, :, 1:] = 0
    sums = np.where(weights > 0, sums, 0)
    sums[2] = 0.1 * weights[2]
    weights[3] = 1
    sums[3] = np.tile([0.1, 0.1 + 1e-14, 0.1 + 2e-14] * 6, (2, 1))[:, :17]
    moments = stats.prepare_package_intervals(sums, weights)
    actual = stats.package_intervals_from_moments(moments, alpha, sides)
    for index in np.ndindex(sums.shape[:-1]):
        expected = stats.package_interval(sums[index], weights[index], alpha, sides)
        for name in ("estimate", "lower", "upper"):
            field = getattr(expected, name)
            value = getattr(actual, name)[index]
            assert math.isnan(value) if field is None else value == field
        for name in ("df", "packages", "computable"):
            assert getattr(actual, name)[index] == getattr(expected, name)


def test_empty_package_axis_and_empty_study_axis() -> None:
    empty_packages = stats.package_intervals(np.empty((3, 0)), np.empty((3, 0)), 0.025)
    assert np.all(empty_packages.packages == 0)
    assert np.all(np.isnan(empty_packages.estimate))
    assert not np.any(empty_packages.computable)
    empty_studies = stats.package_intervals(np.empty((0, 2, 17)), np.empty((0, 2, 17)), 0.025)
    assert empty_studies.estimate.shape == (0, 2)


def test_cached_quantile_revalidates_boolean_df() -> None:
    stats.t_quantile(1, 0.975)
    with pytest.raises(ValueError, match="df"):
        stats.t_quantile(True, 0.975)
    with pytest.raises(ValueError, match="df"):
        stats.t_quantile(np.bool_(True), 0.975)


def test_repeated_quantile_does_not_repeat_cdf_inversion(monkeypatch: pytest.MonkeyPatch) -> None:
    stats._t_quantile.cache_clear()
    original = stats.t_cdf
    calls = 0

    def counted(t: float, df: int) -> float:
        nonlocal calls
        calls += 1
        return original(t, df)

    monkeypatch.setattr(stats, "t_cdf", counted)
    first = stats.t_quantile(16, 0.975)
    first_calls = calls
    assert first_calls > 0
    assert stats.t_quantile(np.int64(16), 0.975) == first
    assert calls == first_calls


def test_intercept_table_solves_once_per_sigma_and_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats.intercept_table.cache_clear()
    original = np.logaddexp
    calls = 0

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(np, "logaddexp", counted)
    first = stats.intercept_table(0.812345)
    first_calls = calls
    assert first_calls > 0
    second = stats.intercept_table(0.812345)
    assert first is second
    assert calls == first_calls
    assert not first[0].flags.writeable
    assert not first[1].flags.writeable
