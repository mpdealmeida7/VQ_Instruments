
import time, math, statistics
from moku.instruments import Phasemeter

# ========= USER SETTINGS =========
HOST = 'localhost:8090'     # IPv4 or USB IPv6+%zone (e.g., 'fe80::...%41' on Windows)
TONE_HZ = 1e6        # Your AWG tone
PLL_BW_HZ = '1kHz'          # 0.5–5 kHz is a good starting point for steady tones
N_READS = 20               # Samples per measurement block
READ_DT = 0.1              # s between reads

# Front-end (adapt to your AWG & cabling)
INPUT_IMPEDANCE = '50Ohm'   # 'FiftyOhm' or 'OneMeg'
COUPLING = 'DC'                # 'DC' or 'AC'
RANGE_VPP = '10Vpp'                # Smallest non-clipping range

# Optional: do a baseline calibration with 0° on both AWG channels first
RUN_BASELINE_CAL = True

# ========= HELPERS =========
def wrap_deg(angle_deg):
    """Wrap degrees to (-180, 180]."""
    x = (angle_deg + 180.0) % 360.0 - 180.0
    return 180.0 if x == -180.0 else x

def detect_deg(delta_raw):
    """
    Convert a raw phase difference (unknown unit: radians or cycles)
    to degrees by picking the interpretation that is closest to 0° or 360° multiples
    when Δphase is near an expected value (we don't assume 45°; we minimize wrap).
    """
    d_rad = math.degrees(delta_raw)
    d_cyc = delta_raw * 360.0
    # choose the one with the smaller absolute wrapped magnitude (more 'stable')
    c1 = abs(wrap_deg(d_rad))
    c2 = abs(wrap_deg(d_cyc))
    return d_rad if c1 <= c2 else d_cyc

def read_block(pm, n=N_READS, dt=READ_DT):
    vals = []
    for _ in range(n):
        d = pm.get_data()
        phi1 = d['ch1']['phase']
        phi2 = d['ch2']['phase']
        vals.append(detect_deg(phi2 - phi1))
        time.sleep(dt)
    vals = [wrap_deg(v) for v in vals]
    return vals, statistics.mean(vals), (statistics.pstdev(vals) if len(vals) > 1 else 0.0)

# ========= MAIN =========
pm = Phasemeter(HOST, force_connect=True)
try:
    # Front-end
    pm.set_frontend(1, impedance=INPUT_IMPEDANCE, coupling=COUPLING, range=RANGE_VPP)
    pm.set_frontend(2, impedance=INPUT_IMPEDANCE, coupling=COUPLING, range=RANGE_VPP)

    pm.enable_input(1, True); pm.enable_input(2, True)

    # Seed PLLs and lock
    pm.set_pm_loop(1, frequency=TONE_HZ, bandwidth=PLL_BW_HZ)
    pm.set_pm_loop(2, frequency=TONE_HZ, bandwidth=PLL_BW_HZ)
    pm.reacquire()
    time.sleep(0.4)

    # Optional: baseline calibration at AWG 0°/0° to remove path skew
    baseline_deg = 0.0
    if RUN_BASELINE_CAL:
        pm.zero_phase(1)          # choose CH1 as reference
        time.sleep(0.2)
        _, mean0, std0 = read_block(pm)
        baseline_deg = mean0
        print(f"[Baseline] Δφ(CH2-CH1) @ 0° setting: {mean0:.2f}° ±{std0:.2f}°")
        print("Now set AWG CH2 to +45° and rerun the next block...")
        input("Press Enter after AWG is at +45°...")

    # Zero CH1 again before the actual measurement
    pm.zero_phase(1)
    time.sleep(0.2)

    # Measure with CH2 set to +45°
    vals, mean_deg, std_deg = read_block(pm)
    # Remove baseline (if done)
    corrected = wrap_deg(mean_deg - baseline_deg)
    print("\n--- Measurement ---")
    print(f"Raw Δφ(CH2-CH1): {mean_deg:.2f}° ±{std_deg:.2f}°")
    if RUN_BASELINE_CAL:
        print(f"Baseline-corrected Δφ: {corrected:.2f}° (expected ≈ +45°)")
    else:
        print(f"Δφ(CH2-CH1): {mean_deg:.2f}° (expected ≈ +45°)")

    # Quick sanity alert if far from 45°
    estimate = corrected if RUN_BASELINE_CAL else mean_deg
    if min(abs(estimate-45), abs((estimate+360)-45), abs((estimate-360)-45)) > 5:
        print("\n[Hint] Not ≈45°? See the checklist below to fix phase offset.")

finally:
    try: pm.relinquish_ownership()
    except Exception: pass
