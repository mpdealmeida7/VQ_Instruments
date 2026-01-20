
# ===== Moku:Lab — Phasemeter-only phase difference measurement =====
# Hardware hookup: Out1 -> splitter -> In1 and In2 (50 Ω coax, matched length)
# Software: pip install moku ; install mokucli; mokucli instrument download <ver>
# References: generate_output / set_frontend / set_pm_loop / get_data

import time
import numpy as np
from moku.instruments import Phasemeter

MOKU_IP     =  'localhost:8090'   # <-- set your Moku:Lab IP
FREQ_HZ     = 1e6         # test tone (1 MHz)
AMP_VPP     = 0.5               # 0.5 Vpp on Out1
READS       = 64                # number of averaged readings
SLEEP_S     = 0.05              # time between polls

def wrap_deg(x):
    """Wrap angle(s) in degrees to (-180, 180]."""
    return (x + 180.0) % 360.0 - 180.0

def cycles_or_radians_to_deg(diff_values):
    """
    Heuristic unit-detection: the Phasemeter 'phase' field is numeric; depending
    on API generation/stream, it may be radians or cycles (older pymoku stream).
    We examine the raw differences and convert to degrees accordingly.
    """
    a = np.asarray(diff_values)
    m = np.nanmedian(np.abs(a))
    # If typical magnitude << 0.8 -> assume cycles; if <~3.5 -> radians; else already degrees.
    if m < 0.8:        # cycles (~<0.8 cyc)
        return wrap_deg(a * 360.0)
    elif m < 3.5:      # radians (~<pi+ margin)
        return wrap_deg(np.degrees(a))
    else:              # likely already degrees
        return wrap_deg(a)

# Connect Phasemeter
pm = Phasemeter(MOKU_IP, force_connect=True)

try:
    # Generate a sine on Out1 (0.5 Vpp @ 1 MHz)
    pm.generate_output(channel=1, amplitude=AMP_VPP, frequency=FREQ_HZ, signal='Sine')  # Phasemeter DAC
    # Frontends: 50 Ω, DC, 10 Vpp range (adjust range to your signal level)
    pm.set_frontend(channel=1, impedance="50Ohm", coupling="DC", range="10Vpp")
    pm.set_frontend(channel=2, impedance="50Ohm", coupling="DC", range="10Vpp")

    # PLL: lock both channels near FREQ_HZ with 1 kHz bandwidth
    pm.set_pm_loop(channel=1, auto_acquire=False, frequency=FREQ_HZ, bandwidth='1kHz')
    pm.set_pm_loop(channel=2, auto_acquire=False, frequency=FREQ_HZ, bandwidth='1kHz')

    # Give the loops a moment to settle
    time.sleep(0.5)

    # Poll phases and compute difference ch2 - ch1
    diffs_raw = []
    for _ in range(READS):
        time.sleep(SLEEP_S)
        frame = pm.get_data()    # contains per-channel amplitude, frequency, phase
        ph1 = frame['ch1']['phase']
        ph2 = frame['ch2']['phase']
        diffs_raw.append(ph2 - ph1)

    # Convert to degrees regardless of underlying units (cycles/radians/degrees)
    diffs_deg = cycles_or_radians_to_deg(diffs_raw)

    print(f"Mean Δphase: {np.mean(diffs_deg):.4f}°")
    print(f"Std  Δphase: {np.std(diffs_deg):.4f}°")
    # Save a one-time calibration (expected near 0° for a perfect splitter/cables)
    # calib_offset_deg = float(np.mean(diffs_deg))
    # Report calibrated value as wrap_deg(measured - calib_offset_deg)

finally:
    # Optional: turn off the output when done
    pm.disable_output(1)
    pm.relinquish_ownership()