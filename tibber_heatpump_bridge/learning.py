"""Learn the house and power models from logged data.

The controller logs one row per slot: time, indoor temperature, outdoor
temperature, the shift it applied and (optionally) the heat pump's electrical
power. From consecutive rows the indoor temperature *rate* is regressed on
``[1, -T_in, shift_eff, T_out]`` which yields ``c, a, b, d`` directly.

Two solvers are provided: a batch least-squares fit for ``curve-fit`` and a
recursive least-squares estimator with a forgetting factor for a controller
that keeps learning while it runs. Both are plain Python; the problem has
four unknowns.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .curve import HouseModel, PowerModel


class LearningError(ValueError):
    """Raised when the data cannot support a fit."""


# --- linear algebra ---------------------------------------------------------


def solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve ``matrix @ x = rhs`` by Gaussian elimination with partial pivoting."""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise LearningError("regression matrix is singular; the data lacks variation")
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, n):
            factor = a[r][col] / a[col][col]
            if factor:
                for c in range(col, n + 1):
                    a[r][c] -= factor * a[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = a[r][n] - sum(a[r][c] * x[c] for c in range(r + 1, n))
        x[r] = s / a[r][r]
    return x


def least_squares(rows: Sequence[tuple[Sequence[float], float]], *, ridge: float = 1e-9) -> list[float]:
    if not rows:
        raise LearningError("no samples to fit")
    n = len(rows[0][0])
    ata = [[ridge if i == j else 0.0 for j in range(n)] for i in range(n)]
    atb = [0.0] * n
    for x, y in rows:
        for i in range(n):
            atb[i] += x[i] * y
            for j in range(n):
                ata[i][j] += x[i] * x[j]
    return solve_linear(ata, atb)


class RecursiveLeastSquares:
    """Online estimator: ``update(x, y)`` refines ``theta`` so that ``x . theta ~ y``."""

    def __init__(self, n: int, *, forgetting: float = 0.998, initial_variance: float = 100.0) -> None:
        if not 0.0 < forgetting <= 1.0:
            raise ValueError("forgetting factor must be in (0, 1]")
        self.n = n
        self.forgetting = forgetting
        self.theta = [0.0] * n
        self.p = [[initial_variance if i == j else 0.0 for j in range(n)] for i in range(n)]
        self.samples = 0

    def predict(self, x: Sequence[float]) -> float:
        return sum(xi * ti for xi, ti in zip(x, self.theta, strict=True))

    def update(self, x: Sequence[float], y: float) -> float:
        """Incorporate one sample; returns the prediction error before the update."""
        px = [sum(self.p[i][j] * x[j] for j in range(self.n)) for i in range(self.n)]
        denominator = self.forgetting + sum(x[i] * px[i] for i in range(self.n))
        gain = [v / denominator for v in px]
        error = y - self.predict(x)
        self.theta = [t + g * error for t, g in zip(self.theta, gain, strict=True)]
        xp = [sum(x[i] * self.p[i][j] for i in range(self.n)) for j in range(self.n)]
        self.p = [
            [(self.p[i][j] - gain[i] * xp[j]) / self.forgetting for j in range(self.n)] for i in range(self.n)
        ]
        self.samples += 1
        return error


# --- observations -----------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    when: datetime
    indoor_c: float
    outdoor_c: float
    shift: float
    power_kw: float | None = None


@dataclass
class FitReport:
    samples: int
    rmse: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class HouseFit:
    model: HouseModel
    report: FitReport


@dataclass
class PowerFit:
    model: PowerModel
    report: FitReport


def _effective_shifts(observations: Sequence[Observation], filter_minutes: float) -> list[float]:
    """Effective shift during each logged interval, after the pump's smoothing.

    Row ``k`` records the shift applied from ``when_k`` until the next row. The
    value returned for ``k`` is the smoothed shift at the end of that interval,
    which is what the model uses for the temperature step and what an energy
    meter's average power over the interval corresponds to.
    """
    model = HouseModel(filter_minutes=filter_minutes)
    eff = observations[0].shift if observations else 0.0
    result: list[float] = []
    for index, obs in enumerate(observations):
        if index + 1 < len(observations):
            dt = (observations[index + 1].when - obs.when).total_seconds() / 60.0
        else:
            dt = (obs.when - observations[index - 1].when).total_seconds() / 60.0 if index else 0.0
        eff = model.filter_step(eff, obs.shift, max(dt, 0.0))
        result.append(eff)
    return result


def house_regression_rows(
    observations: Sequence[Observation],
    *,
    filter_minutes: float = 0.0,
    max_gap_minutes: float = 120.0,
) -> list[tuple[list[float], float]]:
    """Rows ``([1, -T_in, shift_eff, T_out], dT_in/dt)`` for consecutive observations.

    ``shift_eff`` is the smoothed shift during the interval (see
    :func:`_effective_shifts`); ``T_in``/``T_out`` are taken at its start.
    """
    ordered = sorted(observations, key=lambda o: o.when)
    effective = _effective_shifts(ordered, filter_minutes)
    rows: list[tuple[list[float], float]] = []
    for (before, after), eff in zip(zip(ordered, ordered[1:], strict=False), effective, strict=False):
        dt = (after.when - before.when).total_seconds() / 60.0
        if dt < 1.0 or dt > max_gap_minutes:
            continue
        rate = (after.indoor_c - before.indoor_c) / (dt / 60.0)
        rows.append(([1.0, -before.indoor_c, eff, before.outdoor_c], rate))
    return rows


def fit_house_model(
    observations: Sequence[Observation],
    *,
    filter_minutes: float = 0.0,
    include_outdoor: bool = True,
    max_gap_minutes: float = 120.0,
) -> HouseFit:
    rows = house_regression_rows(observations, filter_minutes=filter_minutes, max_gap_minutes=max_gap_minutes)
    if len(rows) < 8:
        raise LearningError(f"need at least 8 usable consecutive samples, got {len(rows)}")
    if not include_outdoor:
        rows = [(x[:3], y) for x, y in rows]
    theta = least_squares(rows)
    c, a, b = theta[0], theta[1], theta[2]
    d = theta[3] if include_outdoor else 0.0
    residuals = [y - sum(xi * ti for xi, ti in zip(x, theta, strict=True)) for x, y in rows]
    rmse = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    report = FitReport(samples=len(rows), rmse=rmse)
    if a <= 0:
        report.warnings.append("a <= 0: the room does not settle in this data; log longer or check sensors")
    if b <= 0:
        report.warnings.append(
            "b <= 0: no measurable response to the shift; vary the shift more or log longer"
        )
    shifts = {round(o.shift, 3) for o in observations}
    if len(shifts) < 2:
        report.warnings.append("the shift never changed; b cannot be identified")
    return HouseFit(HouseModel(a=a, b=b, c=c, d=d, filter_minutes=filter_minutes), report)


def fit_power_model(
    observations: Sequence[Observation], *, heat_limit_c: float = 16.0, filter_minutes: float = 0.0
) -> PowerFit:
    """Fit ``P = g * max(0, limit - T_out) + p * shift_eff + standby``.

    ``power_kw`` is read as the average power over the interval the row covers,
    which is how a slot energy reading converts.
    """
    ordered = sorted(observations, key=lambda o: o.when)
    effective = _effective_shifts(ordered, filter_minutes)
    rows = [
        ([max(0.0, heat_limit_c - obs.outdoor_c), eff, 1.0], obs.power_kw)
        for obs, eff in zip(ordered, effective, strict=True)
        if obs.power_kw is not None
    ]
    if len(rows) < 8:
        raise LearningError(f"need at least 8 samples with power_kw, got {len(rows)}")
    g, p_shift, standby = least_squares(rows)
    residuals = [y - (g * x[0] + p_shift * x[1] + standby) for x, y in rows]
    rmse = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    report = FitReport(samples=len(rows), rmse=rmse)
    if p_shift <= 0:
        report.warnings.append(
            "kw_per_k_shift <= 0: power did not rise with the shift; check the sign convention"
        )
    return PowerFit(
        PowerModel(
            kw_per_k_outdoor=max(0.0, g),
            kw_per_k_shift=p_shift,
            heat_limit_c=heat_limit_c,
            standby_kw=max(0.0, standby),
        ),
        report,
    )


# --- CSV log ----------------------------------------------------------------

CSV_COLUMNS = ("time", "indoor_c", "outdoor_c", "shift", "power_kw")


def read_observations_csv(path: str | Path) -> list[Observation]:
    """Read ``time,indoor_c,outdoor_c,shift[,power_kw]`` rows; blank power is allowed."""
    observations: list[Observation] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in CSV_COLUMNS[:4] if c not in (reader.fieldnames or [])]
        if missing:
            raise LearningError(f"CSV is missing columns: {', '.join(missing)}")
        for line, row in enumerate(reader, start=2):
            try:
                when = datetime.fromisoformat(row["time"].strip())
                power = row.get("power_kw")
                observations.append(
                    Observation(
                        when=when,
                        indoor_c=float(row["indoor_c"]),
                        outdoor_c=float(row["outdoor_c"]),
                        shift=float(row["shift"]),
                        power_kw=float(power) if power not in (None, "") else None,
                    )
                )
            except (KeyError, ValueError) as exc:
                raise LearningError(f"{path} line {line}: {exc}") from exc
    if not observations:
        raise LearningError(f"{path} has no data rows")
    return observations


def write_observations_csv(path: str | Path, observations: Sequence[Observation]) -> None:
    with Path(path).open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for obs in observations:
            writer.writerow(
                [
                    obs.when.isoformat(),
                    f"{obs.indoor_c:.3f}",
                    f"{obs.outdoor_c:.3f}",
                    f"{obs.shift:.3f}",
                    "" if obs.power_kw is None else f"{obs.power_kw:.4f}",
                ]
            )
