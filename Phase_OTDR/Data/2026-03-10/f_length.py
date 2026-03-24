# Fibre Length with Calibration -- Improved error calculation
# =============================================================================
# Author: Your name
# Description:
#   Extract group delay and fibre length from phase-vs-frequency sweeps
#   with calibration, including robust uncertainty handling:
#   - Weighted linear least squares (if per-point σφ available)
#   - Optional frequency window selection
#   - Automatic unwrap trial
#   - 95% CI via Student-t (uses SciPy if available; else normal approx)
#   - Optional bootstrap for slope σ
#   - Timebase ppm contribution
# =============================================================================

from __future__ import annotations
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Optional: SciPy for t-quantiles (falls back to z=1.96 if missing)
try:
    from scipy.stats import t as scipy_t  # type: ignore
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False

# -----------------------------
# Constants for SMF-28 @ 1550 nm
# -----------------------------
C = 299_792_458.0        # speed of light [m/s]
NG_DEFAULT = 1.468       # SMF-28 group index at 1550 nm (typical)
NG_STD_DEFAULT = 0.0001   # typical uncertainty if not otherwise known

# -----------------------------
# Helpers
# -----------------------------
def unwrap_deg(phi_deg: np.ndarray) -> np.ndarray:
    """
    Unwrap phase given in degrees using numpy.unwrap in radians.
    """
    phi_rad = np.deg2rad(np.asarray(phi_deg, dtype=float))
    phi_unwrapped = np.unwrap(phi_rad)
    return np.rad2deg(phi_unwrapped)


def load_xy_from_csv(
    csv_path: str,
    freq_col: str = "frequency_hz",
    phase_col: str | None = None,
    phase_sigma_col: str | None = None,
) -> tuple[np.ndarray, np.ndarray, str, np.ndarray | None, str | None]:
    """
    Load (frequency, phase) from a CSV file and optionally per-point phase σ.
    Automatically selects a phase column if not specified.
    Supports metadata/comment lines starting with '#'.

    Returns:
        f_hz, phi_deg, chosen_phase_col, sigma_phi_deg (or None), chosen_sigma_col
    """
    df = pd.read_csv(csv_path, comment="#")

    # Auto-detect phase column if not provided
    if phase_col is None:
        candidates = [
            "delta_phi_unwrapped_deg",
            "delta_phi_deg",
            "delta_phi_wrapped_deg",
            "delta_phi_raw_deg",
            "phase_deg",
        ]
        found = [c for c in candidates if c in df.columns]
        if not found:
            raise ValueError(
                f"No phase column found. Available columns: {list(df.columns)}. "
                f"Please pass phase_col explicitly."
            )
        phase_col = found[0]

    # Optionally auto-detect per-point phase σ column
    sigma_col_used = None
    sigma_phi = None
    if phase_sigma_col is None:
        sigma_candidates = [
            "delta_phi_std_deg",
            "phase_std_deg",
            "sigma_phase_deg",
            "delta_phi_sem_deg",
        ]
        found_s = [c for c in sigma_candidates if c in df.columns]
        if found_s:
            sigma_col_used = found_s[0]
    else:
        if phase_sigma_col not in df.columns:
            raise ValueError(
                f"Requested phase_sigma_col='{phase_sigma_col}' not found. "
                f"Available: {list(df.columns)}"
            )
        sigma_col_used = phase_sigma_col

    # Extract numeric arrays
    f = pd.to_numeric(df[freq_col], errors="coerce").to_numpy()
    y = pd.to_numeric(df[phase_col], errors="coerce").to_numpy()

    if sigma_col_used is not None:
        sigma_phi = pd.to_numeric(df[sigma_col_used], errors="coerce").to_numpy()
    else:
        sigma_phi = None

    # Keep finite rows only
    mask = np.isfinite(f) & np.isfinite(y)
    if sigma_phi is not None:
        mask &= np.isfinite(sigma_phi) & (sigma_phi > 0)

    f, y = f[mask], y[mask]
    if sigma_phi is not None:
        sigma_phi = sigma_phi[mask]

    # Sort by frequency
    idx = np.argsort(f)
    f, y = f[idx].astype(float), y[idx].astype(float)
    if sigma_phi is not None:
        sigma_phi = sigma_phi[idx].astype(float)

    return f, y, phase_col, sigma_phi, sigma_col_used


def select_band(
    f_hz: np.ndarray,
    phi_deg: np.ndarray,
    fmin: float | None = None,
    fmax: float | None = None,
    sigma_phi_deg: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """
    Select a frequency sub-band (useful to exclude nonlinear edges).
    If sigma_phi_deg is provided, it is filtered identically.
    """
    f = np.asarray(f_hz, dtype=float)
    y = np.asarray(phi_deg, dtype=float)
    mask = np.isfinite(f) & np.isfinite(y)
    if fmin is not None:
        mask &= (f >= float(fmin))
    if fmax is not None:
        mask &= (f <= float(fmax))
    f, y = f[mask], y[mask]

    if sigma_phi_deg is not None:
        s = np.asarray(sigma_phi_deg, dtype=float)
        s = s[mask]
    else:
        s = None

    return f, y, s


def _tcrit_95(dof: int) -> float:
    """
    95% two-sided critical value (≈1.96 for large dof).
    Uses SciPy if available; otherwise normal approx.
    """
    if _HAVE_SCIPY:
        dof_eff = max(int(dof), 1)
        return float(scipy_t.ppf(0.975, dof_eff))
    else:
        return 1.959963984540054  # ~N(0,1) 97.5th percentile


def linear_fit_with_sigma_m(
    f_hz: np.ndarray,
    phi_deg: np.ndarray,
    unwrap: bool = False,
    plot: bool = True,
    title: str | None = None,
    sigma_phi_deg: np.ndarray | None = None,
) -> dict:
    """
    Fit phi_deg = m * f_hz + b and compute sigma_m from covariance.

    - If sigma_phi_deg is provided, uses weighted least squares via numpy.polyfit(w=...).
    - Returns slope/intercept, their standard errors, R^2, residuals RMS, and n.
    """
    f = np.asarray(f_hz, dtype=float)
    y = np.asarray(phi_deg, dtype=float)

    if unwrap:
        y = unwrap_deg(y)

    if sigma_phi_deg is not None:
        w = 1.0 / np.asarray(sigma_phi_deg, dtype=float)
        good = np.isfinite(f) & np.isfinite(y) & np.isfinite(w) & (w > 0)
        f, y, w = f[good], y[good], w[good]
        (m, b), cov = np.polyfit(f, y, deg=1, w=w, cov=True)
    else:
        (m, b), cov = np.polyfit(f, y, deg=1, cov=True)

    sigma_m = float(np.sqrt(cov[0, 0]))  # std error of slope
    sigma_b = float(np.sqrt(cov[1, 1]))  # std error of intercept
    y_hat = m * f + b
    resid = y - y_hat

    # Goodness-of-fit metrics
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - np.mean(y))**2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    resid_rms = float(np.sqrt(np.mean(resid**2))) if len(resid) > 0 else np.nan

    if plot:
        if title is None:
            title = "Linear fit: phase difference vs frequency"
        fig, ax = plt.subplots(2, 1, figsize=(8.5, 7), sharex=True)

        ax[0].scatter(f, y, s=18, alpha=0.75, label="data")
        ax[0].plot(f, y_hat, lw=2, color="tab:red", label="fit")
        ax[0].set_ylabel("Δφ [deg]")
        ax[0].set_title(title)
        ax[0].grid(True, alpha=0.3)
        ax[0].legend()

        ax[1].axhline(0, color="k", lw=1)
        ax[1].scatter(f, resid, s=18, alpha=0.75)
        ax[1].set_xlabel("Frequency [Hz]")
        ax[1].set_ylabel("Residual [deg]")
        ax[1].grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show()

    return {
        "m_deg_per_hz": float(m),
        "b_deg": float(b),
        "sigma_m_deg_per_hz": sigma_m,
        "sigma_b_deg": sigma_b,
        "r2": float(r2),
        "resid_rms_deg": resid_rms,
        "n": int(len(f)),
        "unwrap_applied": bool(unwrap),
    }


def fit_try_unwrap(
    f_hz: np.ndarray,
    phi_deg: np.ndarray,
    plot: bool = False,
    sigma_phi_deg: np.ndarray | None = None,
) -> dict:
    """
    Try fits both without and with unwrapping; return the one with smaller sigma_m.
    """
    r1 = linear_fit_with_sigma_m(f_hz, phi_deg, unwrap=False, plot=False, sigma_phi_deg=sigma_phi_deg)
    r2 = linear_fit_with_sigma_m(f_hz, phi_deg, unwrap=True,  plot=False, sigma_phi_deg=sigma_phi_deg)
    best = r1 if r1["sigma_m_deg_per_hz"] <= r2["sigma_m_deg_per_hz"] else r2

    # Optionally plot the chosen fit
    if plot:
        linear_fit_with_sigma_m(f_hz, phi_deg, unwrap=best["unwrap_applied"], plot=True, sigma_phi_deg=sigma_phi_deg,
                                title=f"Chosen fit (unwrap={best['unwrap_applied']})")

    return best


def slope_to_group_delay(m_deg_per_hz: float) -> float:
    """
    Convert slope (deg/Hz) to group delay tau [s].
    tau = -m / 360
    """
    return -m_deg_per_hz / 360.0


def slope_sigma_to_group_delay_sigma(sigma_m_deg_per_hz: float) -> float:
    """
    Propagate slope uncertainty to group delay uncertainty.
    sigma_tau = sigma_m / 360
    """
    return sigma_m_deg_per_hz / 360.0


def group_delay_to_length(tau_s: float, ng: float = NG_DEFAULT) -> float:
    """
    Convert group delay to fibre length: L = c * tau / ng
    """
    return (C * tau_s) / ng


def group_delay_sigma_to_length_sigma(sigma_tau_s: float, ng: float = NG_DEFAULT) -> float:
    """
    Convert group delay uncertainty to length uncertainty from the fit only:
    sigma_L_fit = c * sigma_tau / ng
    """
    return (C * sigma_tau_s) / ng


def length_uncertainty_from_ng(L_m: float, ng: float = NG_DEFAULT, ng_std: float = NG_STD_DEFAULT) -> float:
    """
    Uncertainty in length due to uncertainty in group index:
    sigma_L_ng = |L| * (ng_std / ng)
    """
    return abs(L_m) * (ng_std / ng)


def length_uncertainty_from_timebase(L_m: float, ppm: float = 0.0) -> float:
    """
    Fractional error from timebase accuracy (ppm): delta L / L ≈ ppm * 1e-6
    """
    return abs(L_m) * (ppm * 1e-6)


def combine_uncertainties(*sigmas: float) -> float:
    """
    Quadrature sum of independent uncertainties.
    """
    arr = np.asarray(sigmas, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.sqrt(np.sum(arr**2))) if arr.size else 0.0


def welch_satterthwaite_dof(var1: float, n1: int, var2: float, n2: int) -> float:
    """
    Effective degrees of freedom for the sum of two independent variances
    using Welch–Satterthwaite equation (with dof ~ N-2 for each linear fit).
    """
    dof1 = max(n1 - 2, 1)
    dof2 = max(n2 - 2, 1)
    num = (var1 + var2) ** 2
    den = (var1**2 / dof1) + (var2**2 / dof2)
    return float(num / den) if den > 0 else 1.0


def expected_slope_deg_per_hz(L_m: float, ng: float = NG_DEFAULT) -> float:
    """
    Expected slope (deg/Hz) for a given length, useful as a sanity check.
    """
    tau = (ng * L_m) / C
    return -360.0 * tau


def bootstrap_sigma_m(
    f_hz: np.ndarray,
    phi_deg: np.ndarray,
    unwrap: bool = False,
    nboot: int = 1000,
    seed: int | None = 0,
    sigma_phi_deg: np.ndarray | None = None,
) -> float:
    """
    Bootstrap estimate of sigma_m (robust to outliers/non-Gaussian residuals).
    """
    rng = np.random.default_rng(seed)
    idx = np.arange(len(f_hz))
    slopes = []
    f = np.asarray(f_hz, dtype=float)
    y = np.asarray(phi_deg, dtype=float)

    if unwrap:
        y = unwrap_deg(y)

    if sigma_phi_deg is not None:
        w = 1.0 / np.asarray(sigma_phi_deg, dtype=float)
        good = np.isfinite(f) & np.isfinite(y) & np.isfinite(w) & (w > 0)
        f, y, w = f[good], y[good], w[good]
        idx = np.arange(len(f))
        for _ in range(nboot):
            bb = rng.choice(idx, size=len(idx), replace=True)
            (m, _), _ = np.polyfit(f[bb], y[bb], deg=1, w=w[bb], cov=True)
            slopes.append(m)
    else:
        good = np.isfinite(f) & np.isfinite(y)
        f, y = f[good], y[good]
        idx = np.arange(len(f))
        for _ in range(nboot):
            bb = rng.choice(idx, size=len(idx), replace=True)
            (m, _), _ = np.polyfit(f[bb], y[bb], deg=1, cov=True)
            slopes.append(m)

    return float(np.std(slopes, ddof=1)) if slopes else np.nan


# -----------------------------
# Calibration workflow
# -----------------------------
def calibrated_length_from_two_fits(
    fit_meas: dict,
    fit_cal: dict,
    ng: float = NG_DEFAULT,
    ng_std: float = NG_STD_DEFAULT,
    timebase_ppm: float = 0.0,
    return_ci95: bool = True,
) -> dict:
    """
    Compute fibre-only slope = m_meas - m_cal,
    then convert to tau and length and propagate uncertainties.

    slope uncertainty adds in quadrature:
      sigma_m_fibre = sqrt(sigma_m_meas^2 + sigma_m_cal^2)

    total length uncertainty includes:
      - fit uncertainty
      - group index uncertainty (ng)
      - (optional) timebase accuracy
    """
    m_meas = fit_meas["m_deg_per_hz"]
    m_cal  = fit_cal["m_deg_per_hz"]
    sm_meas = fit_meas["sigma_m_deg_per_hz"]
    sm_cal  = fit_cal["sigma_m_deg_per_hz"]
    n_meas = fit_meas["n"]
    n_cal  = fit_cal["n"]

    m_fibre = m_meas - m_cal
    sm_fibre = float(np.sqrt(sm_meas**2 + sm_cal**2))

    tau = slope_to_group_delay(m_fibre)
    stau = slope_sigma_to_group_delay_sigma(sm_fibre)
    L = group_delay_to_length(tau, ng=ng)

    sL_fit = group_delay_sigma_to_length_sigma(stau, ng=ng)
    sL_ng  = length_uncertainty_from_ng(L, ng=ng, ng_std=ng_std)
    sL_tb  = length_uncertainty_from_timebase(L, ppm=timebase_ppm)
    sL_total = combine_uncertainties(sL_fit, sL_ng, sL_tb)

    out = {
        "m_fibre_deg_per_hz": m_fibre,
        "sigma_m_fibre_deg_per_hz": sm_fibre,
        "tau_s": tau,
        "sigma_tau_s": stau,
        "L_m": L,
        "sigma_L_fit_m": sL_fit,
        "sigma_L_ng_m": sL_ng,
        "sigma_L_timebase_m": sL_tb,
        "sigma_L_total_m": sL_total,
        "ng": ng,
        "ng_std": ng_std,
        "timebase_ppm": timebase_ppm,
        "n_meas": n_meas,
        "n_cal": n_cal,
    }

    if return_ci95:
        # 95% CI on m_fibre using Welch–Satterthwaite for dof
        var_meas = sm_meas**2
        var_cal  = sm_cal**2
        dof_eff = welch_satterthwaite_dof(var_meas, n_meas, var_cal, n_cal)
        tcrit = _tcrit_95(int(round(dof_eff)))
        m_ci = (m_fibre - tcrit * sm_fibre, m_fibre + tcrit * sm_fibre)
        out["m_fibre_ci95_deg_per_hz"] = m_ci

        # Propagate CI to tau and L (linear mapping; endpoints suffice)
        tau_ci = (slope_to_group_delay(m_ci[0]), slope_to_group_delay(m_ci[1]))
        L_ci = (group_delay_to_length(tau_ci[0], ng=ng),
                group_delay_to_length(tau_ci[1], ng=ng))
        out["tau_ci95_s"] = tau_ci
        out["L_ci95_m"] = L_ci

    return out


# -----------------------------
# Main usage example
# -----------------------------
if __name__ == "__main__":
    # ---- USER INPUTS ----


    from pathlib import Path
    import re

    def discover_files(data_folder: str, base_prefix: str):
        """
        Find calibration and all run CSVs in the given folder.
        Expected:
        - {base_prefix}__start-...__calibration.csv
        - {base_prefix}__start-...__run-XX.csv
        Returns: (calibration_path, [run_paths_sorted])
        """
        p = Path(data_folder)
        cal = None
        runs = []
        for f in sorted(p.glob(f"{base_prefix}__start-*__*.csv")):
            name = f.name
            if name.endswith("__calibration.csv"):
                cal = f
            else:
                m = re.search(r"__run-(\d+)\.csv$", name)
                if m:
                    runs.append((int(m.group(1)), f))
        runs_sorted = [fp for _, fp in sorted(runs, key=lambda t: t[0])]
        return cal, runs_sorted
  
    data_folder = "./Data/2026-03-10"  # change as needed

    # Your measurement sweep CSV (with fibre under test)
    MEAS_CSV = os.path.join(data_folder, "fut_FBS_2m_10_av_10kHz_BW__start-20260310_142750__run-02.csv")

    # Your calibration sweep CSV (same setup, short reference or no fibre)
    CAL_CSV  = os.path.join(data_folder, "fut_FBS_2m_10_av_10kHz_BW__start-20260310_140323__calibration.csv")

    # Columns in your CSV
    FREQ_COL = "frequency_hz"

    # If None, auto-detect from common names (see load_xy_from_csv)
    PHASE_COL_MEAS = None
    PHASE_COL_CAL  = None

    # Optional: per-point phase σ column (None -> auto-detect; or set a column name)
    PHASE_SIGMA_COL_MEAS = None
    PHASE_SIGMA_COL_CAL  = None

    # Optional: fit window (exclude nonlinear edges if needed)
    F_MIN = 8e6
    F_MAX = 120e6

    # If your CSV uses wrapped phase, you can let the code auto-try both
    AUTO_TRY_UNWRAP = True

    # SMF-28 parameters at 1550 nm
    NG = 1.468
    NG_STD = 0.001

    # Optional: Moku timebase accuracy (ppm). Set 0 if GPSDO / disciplined.
    TIMEBASE_PPM = 0.5

    # Plot toggles
    PLOT_FITS = False  # Set True to visually inspect fits

    # Optional: bootstrap for robust slope σ (set 0 to skip)
    BOOTSTRAP_ITER = 10000  # e.g., 2000 for strong robustness

    # ---------- Load Data -------------------------------------

    # 1) Discover calibration and runs
    BASE_PREFIX = "calib_FBS_2m_10_av_10kHz_BW"   # <-- set to your actual prefix
    cal_csv, run_csvs = discover_files(data_folder, BASE_PREFIX)

    if cal_csv is None:
        raise FileNotFoundError(
            f"Calibration file not found in {data_folder}. "
            f"Expected pattern: {BASE_PREFIX}__start-...__calibration.csv"
        )
    if not run_csvs:
        raise FileNotFoundError(
            f"No run files found in {data_folder}. "
            f"Expected pattern: {BASE_PREFIX}__start-...__run-XX.csv"
        )

    # 2) Calibration fit (once)
    f_cal, phi_cal, _, sigma_cal, _ = load_xy_from_csv(
        str(cal_csv), freq_col=FREQ_COL, phase_col=PHASE_COL_CAL, phase_sigma_col=PHASE_SIGMA_COL_CAL
    )
    f_cal, phi_cal, sigma_cal = select_band(f_cal, phi_cal, F_MIN, F_MAX, sigma_cal)
    if AUTO_TRY_UNWRAP:
        fit_cal = fit_try_unwrap(f_cal, phi_cal, plot=PLOT_FITS, sigma_phi_deg=sigma_cal)
    else:
        fit_cal = linear_fit_with_sigma_m(f_cal, phi_cal, unwrap=False, plot=PLOT_FITS, sigma_phi_deg=sigma_cal)

    # 3) Iterate runs, compute per-run length + uncertainty
    rows = []
    for rp in run_csvs:
        # Extract run index from filename
        m = re.search(r"__run-(\d+)\.csv$", rp.name)
        run_label = m.group(1) if m else rp.name

        f_meas, phi_meas, _, sigma_meas, _ = load_xy_from_csv(
            str(rp), freq_col=FREQ_COL, phase_col=PHASE_COL_MEAS, phase_sigma_col=PHASE_SIGMA_COL_MEAS
        )
        f_meas, phi_meas, sigma_meas = select_band(f_meas, phi_meas, F_MIN, F_MAX, sigma_meas)

        if AUTO_TRY_UNWRAP:
            fit_meas = fit_try_unwrap(f_meas, phi_meas, plot=PLOT_FITS, sigma_phi_deg=sigma_meas)
        else:
            fit_meas = linear_fit_with_sigma_m(f_meas, phi_meas, unwrap=False, plot=PLOT_FITS, sigma_phi_deg=sigma_meas)

        # Calibrated length and uncertainties (reuses your function)
        out = calibrated_length_from_two_fits(
            fit_meas, fit_cal, ng=NG, ng_std=NG_STD, timebase_ppm=TIMEBASE_PPM, return_ci95=True
        )

        rows.append({
            "run": run_label,
            "filename": rp.name,
            "length_m": out["L_m"],
            "sigma_L_fit_m": out["sigma_L_fit_m"],
            "sigma_L_ng_m": out["sigma_L_ng_m"],
            "sigma_L_timebase_m": out["sigma_L_timebase_m"],
            "sigma_L_total_m": out["sigma_L_total_m"],
        })

        print(f"Run {run_label:>3}: L = {out['L_m']:.3f} m  (σ_total ≈ {out['sigma_L_total_m']:.3f} m)  <- {rp.name}")

    # 4) Save summary CSV
    df_sum = pd.DataFrame(rows)
    summary_csv = os.path.join(data_folder, f"{BASE_PREFIX}__fiber_length_runs_summary.csv")
    df_sum.to_csv(summary_csv, index=False)
    print(f"Saved summary: {summary_csv}")

    # 5) Plot: length vs run with shaded 95% CI (from σ_total)
    x = np.array([int(r) if str(r).isdigit() else np.nan for r in df_sum["run"]], dtype=float)
    y = df_sum["length_m"].to_numpy(float)
    se = df_sum["sigma_L_total_m"].to_numpy(float)
    ci95 = 1.96 * se

    order = np.argsort(x)
    x, y, ci95 = x[order], y[order], ci95[order]

    plt.figure(figsize=(9, 5.5))
    plt.plot(x, y, marker='o', color='#1f77b4', lw=1.5, label='Estimated length')
    plt.fill_between(x, y - ci95, y + ci95, color='#1f77b4', alpha=0.2, label='95% CI (total)')
    plt.title('Fibre length per run (with 95% CI)')
    plt.xlabel('Run index')
    plt.ylabel('Length [m]')
    plt.grid(True, ls=':', alpha=0.6)
    plt.legend()
    plt.tight_layout()

    out_png = os.path.join(data_folder, f"{BASE_PREFIX}__fiber_length_runs.png")
    out_pdf = os.path.join(data_folder, f"{BASE_PREFIX}__fiber_length_runs.pdf")
    plt.savefig(out_png, dpi=150)
    plt.savefig(out_pdf)
    print(f"Saved plots: {os.path.basename(out_png)}, {os.path.basename(out_pdf)}")

    # 6) Plot: error distribution (errors = L - mean(L))
    mean_L = float(np.mean(y))
    errors = y - mean_L
    std_L = float(np.std(errors, ddof=1)) if len(errors) > 1 else 0.0

    plt.figure(figsize=(8.5, 5.5))
    plt.hist(errors, bins=min(12, max(5, len(errors)//2)),
            density=True, alpha=0.6, color='#1f77b4', edgecolor='white',
            label='Errors = L - mean(L)')
    if std_L > 0:
        xs_err = np.linspace(-4*std_L, 4*std_L, 400)
        norm_pdf_err = (1.0/(std_L*np.sqrt(2*np.pi))) * np.exp(-0.5*(xs_err/std_L)**2)
        plt.plot(xs_err, norm_pdf_err, 'r--', lw=2, label=f'Normal(μ=0, σ={std_L:.3f})')
    plt.title('Error distribution across runs')
    plt.xlabel('Error relative to mean length [m]')
    plt.ylabel('Density')
    plt.grid(True, ls=':', alpha=0.6)
    plt.legend()
    plt.tight_layout()

    out_hist_png = os.path.join(data_folder, f"{BASE_PREFIX}__fiber_length_error_distribution.png")
    out_hist_pdf = os.path.join(data_folder, f"{BASE_PREFIX}__fiber_length_error_distribution.pdf")
    plt.savefig(out_hist_png, dpi=150)
    plt.savefig(out_hist_pdf)
    print(f"Saved error distribution plots: {os.path.basename(out_hist_png)}, {os.path.basename(out_hist_pdf)}")
