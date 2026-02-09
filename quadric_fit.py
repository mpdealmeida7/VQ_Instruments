import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def unwrap_deg(phi_deg):
    """Unwrap phase in degrees using np.unwrap (works in radians)."""
    return np.rad2deg(np.unwrap(np.deg2rad(phi_deg.astype(float))))

def quad_fit_phase(f_hz, phi_deg, unwrap=False):
    """
    Fit phi(f) = a2*f^2 + a1*f + a0  (phi in deg, f in Hz)
    Returns coefficients and covariance + residuals.
    """
    f = np.asarray(f_hz, dtype=float)
    y = np.asarray(phi_deg, dtype=float)

    # Sort by frequency (important for unwrapping + stable plots)
    idx = np.argsort(f)
    f, y = f[idx], y[idx]

    if unwrap:
        y = unwrap_deg(y)

    # Quadratic fit; returns p=[a2,a1,a0] and covariance matrix (3x3)  [1](https://www.geeksforgeeks.org/data-analysis/numpys-polyfit-function-a-comprehensive-guide/)
    p, cov = np.polyfit(f, y, deg=2, cov=True)  # [1](https://www.geeksforgeeks.org/data-analysis/numpys-polyfit-function-a-comprehensive-guide/)
    a2, a1, a0 = p

    # Standard errors of coefficients (sqrt of diagonal of covariance)  [1](https://www.geeksforgeeks.org/data-analysis/numpys-polyfit-function-a-comprehensive-guide/)
    sa2, sa1, sa0 = np.sqrt(np.diag(cov))       # [1](https://www.geeksforgeeks.org/data-analysis/numpys-polyfit-function-a-comprehensive-guide/)

    yhat = a2*f**2 + a1*f + a0
    resid = y - yhat

    # R^2
    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else np.nan

    return {
        "f": f, "y": y, "yhat": yhat, "resid": resid,
        "a2": float(a2), "a1": float(a1), "a0": float(a0),
        "sa2": float(sa2), "sa1": float(sa1), "sa0": float(sa0),
        "cov": cov, "r2": float(r2), "n": int(len(f)),
        "unwrap_applied": bool(unwrap)
    }

def plot_fit_and_residuals(fit, title="Quadratic fit"):
    f, y, yhat, resid = fit["f"], fit["y"], fit["yhat"], fit["resid"]
    a2, a1, a0 = fit["a2"], fit["a1"], fit["a0"]

    fig, ax = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    ax[0].scatter(f, y, s=18, alpha=0.75, label="data")
    ax[0].plot(f, yhat, lw=2, color="tab:red", label="quadratic fit")
    ax[0].set_ylabel("Δφ [deg]")
    ax[0].set_title(title + f"\nphi = a0 + a1 f + a2 f^2;  R²={fit['r2']:.6f}")
    ax[0].grid(True, alpha=0.3)
    ax[0].legend()

    ax[1].axhline(0, color="k", lw=1)
    ax[1].scatter(f, resid, s=18, alpha=0.75)
    ax[1].set_xlabel("Frequency [Hz]")
    ax[1].set_ylabel("Residual [deg]")
    ax[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()

    print("Coefficients:")
    print(f"  a0 = {a0:.6e} ± {fit['sa0']:.3e}  [deg]")
    print(f"  a1 = {a1:.6e} ± {fit['sa1']:.3e}  [deg/Hz]")
    print(f"  a2 = {a2:.6e} ± {fit['sa2']:.3e}  [deg/Hz^2]")
    
def group_delay_from_quad(a1, a2, f_hz):
    """
    tau(f) in seconds from quadratic phase model coefficients (deg units):
      tau = -(a1 + 2*a2*f) / 360
    """
    f = np.asarray(f_hz, dtype=float)
    return -(a1 + 2*a2*f) / 360.0

def plot_group_delay(f, tau_s, title="Group delay vs frequency"):
    plt.figure(figsize=(9, 4.5))
    plt.plot(f, tau_s*1e9, "o-", lw=1.5)
    plt.xlabel("Frequency [Hz]")
    plt.ylabel("Group delay τ [ns]")
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()
    
def quad_calibration_subtract(fit_meas, fit_cal):
    """
    Subtract calibration coefficients from measurement coefficients.
    Also propagate coefficient covariance (assuming independent fits).
    """
    a0 = fit_meas["a0"] - fit_cal["a0"]
    a1 = fit_meas["a1"] - fit_cal["a1"]
    a2 = fit_meas["a2"] - fit_cal["a2"]

    # Covariance propagation: Cov(diff) = Cov(meas) + Cov(cal) if independent
    cov = fit_meas["cov"] + fit_cal["cov"]
    sa2, sa1, sa0 = np.sqrt(np.diag(cov))  # order matches [a2,a1,a0]

    return {
        "a0": float(a0), "a1": float(a1), "a2": float(a2),
        "cov": cov,
        "sa0": float(sa0), "sa1": float(sa1), "sa2": float(sa2)
    }
    
def fibre_length_from_tau(tau_s, ng=1.468):
    c = 299_792_458.0
    return (c * tau_s) / ng

def fibre_length_from_quad_coeffs(a1, a2, f0_hz, ng=1.468):
    tau0 = group_delay_from_quad(a1, a2, np.array([f0_hz]))[0]
    return fibre_length_from_tau(tau0, ng=ng), tau0

def load_csv(csv_path, freq_col="frequency_hz", phase_col=None):
    df = pd.read_csv(csv_path, comment="#")
    if phase_col is None:
        candidates = ["delta_phi_unwrapped_deg", "delta_phi_deg", "delta_phi_wrapped_deg"]
        found = [c for c in candidates if c in df.columns]
        if not found:
            raise ValueError(f"No phase column found. Columns: {list(df.columns)}")
        phase_col = found[0]
    f = pd.to_numeric(df[freq_col], errors="coerce").to_numpy()
    y = pd.to_numeric(df[phase_col], errors="coerce").to_numpy()
    m = np.isfinite(f) & np.isfinite(y)
    return f[m], y[m], phase_col

# -------- USER SETTINGS --------
MEAS_CSV = "phase_vs_frequency_meas.csv"
CAL_CSV  = "phase_vs_frequency_cal.csv"
FREQ_COL = "frequency_hz"
PHASE_COL = None          # auto-detect
UNWRAP = False            # set True if using wrapped phase column
NG = 1.468                # SMF-28 @ 1550 nm

# -------- LOAD --------
f_meas, phi_meas, phcol_meas = load_csv(MEAS_CSV, FREQ_COL, PHASE_COL)
f_cal,  phi_cal,  phcol_cal  = load_csv(CAL_CSV,  FREQ_COL, PHASE_COL)

# -------- FIT QUADRATIC --------
fit_meas = quad_fit_phase(f_meas, phi_meas, unwrap=UNWRAP)
fit_cal  = quad_fit_phase(f_cal,  phi_cal,  unwrap=UNWRAP)

plot_fit_and_residuals(fit_meas, title=f"MEAS quadratic fit ({phcol_meas}, unwrap={UNWRAP})")
plot_fit_and_residuals(fit_cal,  title=f"CAL quadratic fit ({phcol_cal}, unwrap={UNWRAP})")

# -------- CAL SUBTRACTION ON COEFFS --------
fit_fibre = quad_calibration_subtract(fit_meas, fit_cal)
print("\nFIBRE-ONLY coefficients (MEAS - CAL):")
print(f"  a1 = {fit_fibre['a1']:.6e} ± {fit_fibre['sa1']:.3e}  [deg/Hz]")
print(f"  a2 = {fit_fibre['a2']:.6e} ± {fit_fibre['sa2']:.3e}  [deg/Hz^2]")

# -------- GROUP DELAY vs F --------
# Use the common frequency grid for plotting
f_common = np.linspace(max(f_meas.min(), f_cal.min()), min(f_meas.max(), f_cal.max()), 200)
tau_fibre = group_delay_from_quad(fit_fibre["a1"], fit_fibre["a2"], f_common)
plot_group_delay(f_common, tau_fibre, title="Fibre-only group delay (quadratic, MEAS - CAL)")

# -------- LENGTH at mid-band --------
f0 = 0.5*(f_common.min() + f_common.max())
L_m, tau0 = fibre_length_from_quad_coeffs(fit_fibre["a1"], fit_fibre["a2"], f0_hz=f0, ng=NG)
print(f"\nMid-band frequency f0 = {f0/1e6:.3f} MHz")
print(f"Fibre-only group delay τ(f0) = {tau0*1e9:.3f} ns")
print(f"Estimated fibre length L = {abs(L_m):.3f} m  (sign indicates channel direction)")