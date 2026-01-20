

import time
import math
from moku.instruments import Phasemeter

# ========= USER SETTINGS =========
HOST = 'localhost:8090'       # Replace with your device IP or USB IPv6+%zone (Windows) e.g., 'fe80::7269:79ff:feb7:d15a%41'
TONE_HZ = 100e3          # Set to your AWG tone (Hz). Manual seed recommended; auto-acquire can be unreliable <~10 kHz.
PLL_BW_HZ = '1Hz'            # PLL bandwidth (Hz). Increase if your phase/frequency drifts quickly; reduce for quieter readout.
N_SAMPLES = 20              # Number of measurement frames to average for a stable result
SAMPLE_DELAY_S = 0.01         # Time between reads (s)
# Front-end: pick ranges/impedance appropriate to your AWG output and cabling
INPUT_IMPEDANCE = '50Ohm' # 'FiftyOhm' or 'OneMeg'
COUPLING = 'AC'              # 'DC' or 'AC'
RANGE_VPP = '10Vpp'              # Input range (Vpp). Choose smallest non-clipping range (e.g., 2 Vpp, 4 Vpp, etc.)

# ========= CONNECT & CONFIGURE =========
pm = Phasemeter(HOST, force_connect=True)  # Take ownership if already held elsewhere

try:
    # Configure analog front-end for both inputs (impedance, coupling, range)
    pm.set_frontend(channel=1,impedance=INPUT_IMPEDANCE, coupling=COUPLING, range=RANGE_VPP)
    pm.set_frontend(channel=2,impedance=INPUT_IMPEDANCE, coupling=COUPLING, range=RANGE_VPP)

    # Enable both inputs
    pm.enable_input(channel=1, enable=True)
    pm.enable_input(channel=2, enable=True)
    

    # Seed PLLs and lock
    pm.set_pm_loop(channel=1, frequency=TONE_HZ, bandwidth=PLL_BW_HZ)
    pm.set_pm_loop(channel=2, frequency=TONE_HZ, bandwidth=PLL_BW_HZ)
    pm.reacquire()           # Start/Restart PLL lock on all channels
    time.sleep(0.3)          # Small settle time

    # Zero channel 1 phase so CH2 phase directly reads the relative offset (CH2 - CH1)
    pm.zero_phase(channel=1)
    time.sleep(0.2)

    print(f"Locked to ~{TONE_HZ/1e6:.3f} MHz, reporting Δphase = CH2 − CH1 (~45° expected):")
    deltas_deg = []

    for _ in range(N_SAMPLES):
        data = pm.get_data()  # {'ch1': {'phase','frequency','amplitude'}, 'ch2': {...}, ...}
        phi1 = data['ch1']['phase']
        phi2 = data['ch2']['phase']

        # The API’s 'phase' field in programmatic clients may be returned in radians or cycles.
        # Compute both; the correct one should be near 45° for your setup.
        delta_raw = phi2 - phi1
        delta_deg_if_radians = math.degrees(delta_raw)
        delta_deg_if_cycles = delta_raw * 360.0

        print(f"  Δφ ≈ {delta_deg_if_radians:7.2f}° (assuming radians) | "
              f"{delta_deg_if_cycles:7.2f}° (assuming cycles)")

        # If you know your firmware/driver returns radians (common), keep that; otherwise detect:
        # Heuristic: pick the one closer to 45° modulo 360
        cand = min(
            delta_deg_if_radians % 360.0,
            delta_deg_if_cycles % 360.0,
            key=lambda x: min(abs(x-45.0), abs((x-360.0)-45.0))
        )
        deltas_deg.append(cand if cand <= 180 else cand - 360)  # normalize to [-180, 180]

        time.sleep(SAMPLE_DELAY_S)

    avg = sum(deltas_deg)/len(deltas_deg)
    print(f"\nAverage Δphase over {N_SAMPLES} samples: {avg:.2f}°")
    if abs((avg+360) % 360 - 45) < 5 or abs(avg - 45) < 5:
        print("Result looks correct (≈45°).")
    else:
        print("Note: If this isn’t ≈45°, check input ranges/impedance, PLL bandwidth, and AWG phase settings.")

finally:
    # Relinquish ownership so future scripts connect cleanly
    try:
        pm.relinquish_ownership()
    except Exception:
        pass
