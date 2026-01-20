
#!/usr/bin/env python3
"""
Live phase-difference readout with Moku:Lab Phasemeter

Hardware:
  - External AWG: CH1 -> Moku Input 1 (100 kHz, 0°), CH2 -> Moku Input 2 (100 kHz, 45°)
  - Moku:Lab Phasemeter instrument

Stop:
  - Press Ctrl+C to end the loop cleanly.

Notes:
  - The Phasemeter API returns 'phase' per channel. In the Phasemeter data model,
    phase is reported in cycles in legacy streaming; the high-level get_data()
    accessor returns a 'phase' field which we convert to degrees as phase*360.
    We wrap Δφ to (-180°, 180°] for readability.
"""

import time
from math import fmod
from moku.instruments import Phasemeter

# --- USER: set your Moku's IP or serial here ---
MOKU_TARGET = 'localhost:8090 ' # e.g., "192.168.1.100"

# Acquisition / PLL config
F_TONE_HZ = 100e3         # 100 kHz
PLL_BW    = "1kHz"             # loop bandwidth: '1Hz','10Hz','100Hz','1kHz','10kHz','100kHz' (Moku:Lab supports up to 100kHz)
POLL_SEC  = 0.1                # polling interval for get_data()

def wrap_deg_pm180(x_deg: float) -> float:
    """Wrap angle to (-180, 180] degrees."""
    # Python fmod keeps sign; adjust to desired interval
    y = fmod(x_deg + 180.0, 360.0)
    if y < 0:
        y += 360.0
    return y - 180.0

def main():
    i = Phasemeter(MOKU_TARGET, force_connect=True)

    try:
        # --- Front-end: 50 Ω, DC-coupled, 10 Vpp (safe default) ---
        # Choose 1Vpp if your AWG amplitude is small; avoid clipping.
        i.set_frontend(channel=1, impedance="50Ohm", coupling="DC", range="10Vpp")
        i.set_frontend(channel=2, impedance="50Ohm", coupling="DC", range="10Vpp")

        # --- PLLs: lock both channels around 100 kHz with 1 kHz BW ---
        # For a known tone, disable auto-acquire and set frequency explicitly for fast, stable lock.
        i.set_pm_loop(channel=1, auto_acquire=False, frequency=F_TONE_HZ, bandwidth=PLL_BW)
        i.set_pm_loop(channel=2, auto_acquire=False, frequency=F_TONE_HZ, bandwidth=PLL_BW)

        # Optional: ensure fresh lock
        i.reacquire()
   
        print("\nMoku:Lab Phasemeter live phase difference (Ctrl+C to stop)")
        print("Target: {}\n".format(MOKU_TARGET))
        print("{:>10} {:>10} {:>12} {:>12} {:>12}".format("f1 [Hz]", "f2 [Hz]", "φ1 [deg]", "φ2 [deg]", "Δφ [deg]"))
        print("-" * 62)

        while True:
            # get_data returns latest amplitude, frequency, phase per channel
            frame = i.get_data()  # {'ch1': {'frequency':..., 'amplitude':..., 'phase':...}, ...}
            ch1 = frame['ch1']
            ch2 = frame['ch2']

            # Convert phases to degrees (see note above)
            phi1_deg = ch1['phase'] * 360.0
            phi2_deg = ch2['phase'] * 360.0
            dphi_deg = wrap_deg_pm180(phi2_deg - phi1_deg)

            print("{:10.1f} {:10.1f} {:12.3f} {:12.3f} {:12.3f}".format(
                ch1['frequency'], ch2['frequency'], phi1_deg, phi2_deg, dphi_deg
            ))

            time.sleep(POLL_SEC)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        # Always release the instrument when done
        i.relinquish_ownership()

if __name__ == "__main__":
    main()

