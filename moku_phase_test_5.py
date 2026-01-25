
#!/usr/bin/env python3
"""
Moku:Lab Phasemeter — Live Phase-Difference Plot (Δφ = φ2 - φ1)

- Deploys/configures Phasemeter for two external tones (50 Ω, DC).
- Locks PLLs around f=f1=f2 frequencies (1 kHz bandwidth).
- Continuously computes Δφ and plots it live (wrapped to ±180°).
- Prints a short console update once per second.
- Stop with Ctrl+C.

Requirements:
  pip install moku matplotlib
  mokucli instrument download <your-MokuOS-version>  # once per environment

References:
  - Phasemeter set_frontend (impedance, coupling, range)
    https://apis.liquidinstruments.com/api/reference/phasemeter/set_frontend.html
  - Phasemeter set_pm_loop (PLL frequency, bandwidth)
    https://apis.liquidinstruments.com/api/reference/phasemeter/set_pm_loop.html
  - Phasemeter get_data (phase / frequency / amplitude per channel)
    https://apis.liquidinstruments.com/api/reference/phasemeter/get_data.html
"""

import time
from math import fmod
from collections import deque
import matplotlib.pyplot as plt
from moku.instruments import Phasemeter

# ---------- USER SETTINGS ----------
MOKU_TARGET   = 'localhost:8090'   # e.g., "192.168.1.100"
F_TONE_HZ     = 5e6           # known tone ~100 kHz
PLL_BW        = "1kHz"              # '1Hz','10Hz','100Hz','1kHz','10kHz','100kHz' (Moku:Lab supports up to 100kHz)
INPUT_RANGE   = "10Vpp"             # choose "1Vpp" if your AWG amplitude is small
POLL_SEC      = 0.1                 # plot update interval
PRINT_EVERY_S = 1.0                 # print a console line every N seconds
WINDOW_S      = 60.0                # plot window length (seconds)
WRAP_OUTPUT   = True                # wrap Δφ to ±180° (set False if you prefer raw subtraction)
# If your API returns phase in degrees directly (rare), set PHASE_UNITS = "deg"
PHASE_UNITS   = "cycles"            # "cycles" (typical) or "deg"
# -----------------------------------

def wrap_deg_pm180(x_deg: float) -> float:
    """Wrap angle to (-180, 180] degrees for readability."""
    y = fmod(x_deg + 180.0, 360.0)
    if y < 0:
        y += 360.0
    return y - 180.0

def to_deg(phase_value):
    """Convert phase to degrees based on units."""
    if PHASE_UNITS.lower() == "deg":
        return float(phase_value)
    # default: cycles -> degrees
    return float(phase_value) * 360.0

def main():
    # Connect and take ownership
    i = Phasemeter(MOKU_TARGET, force_connect=True)

    try:
        # --- Configure front-ends: 50 Ω, DC coupling, set input range ---
        i.set_frontend(channel=1, impedance="50Ohm", coupling="AC", range=INPUT_RANGE)
        i.set_frontend(channel=2, impedance="50Ohm", coupling="AC", range=INPUT_RANGE)

        # --- Configure PLLs: known tone at 100 kHz, selected bandwidth ---
        i.set_pm_loop(channel=1, auto_acquire=False, frequency=F_TONE_HZ, bandwidth=PLL_BW)
        i.set_pm_loop(channel=2, auto_acquire=False, frequency=F_TONE_HZ, bandwidth=PLL_BW)

        # Reacquire to ensure fresh lock
        i.reacquire()
        

        # --- Matplotlib live plot setup ---
        plt.ion()
        fig, ax = plt.subplots(figsize=(8, 4.5))
        line, = ax.plot([], [], lw=1.6, color="#1f77b4")
        ax.set_title("Live Phase Difference Δφ = φ₂ − φ₁")
        ax.set_xlabel("Elapsed time [s]")
        ax.set_ylabel("Δφ [deg]")
        ax.grid(True, alpha=0.3)

        times = deque(maxlen=int(WINDOW_S / POLL_SEC) + 5)
        dphis = deque(maxlen=int(WINDOW_S / POLL_SEC) + 5)

        t0 = time.time()
        t_last_print = t0

        print("\nMoku:Lab Phasemeter — live Δφ (Ctrl+C to stop)")
        print("Target: {} | PLL f0: {:.1f} Hz | BW: {}".format(MOKU_TARGET, F_TONE_HZ, PLL_BW))
        print("{:>9} {:>10} {:>10} {:>11}".format("t[s]", "f1[Hz]", "f2[Hz]", "Δφ[deg]"))
        print("-" * 46)

        while True:
            frame = i.get_data()   # {'ch1': {...}, 'ch2': {...}}
            ch1 = frame["ch1"]
            ch2 = frame["ch2"]

            # Convert per-channel phases to degrees
            phi1_deg = to_deg(ch1["phase"])
            phi2_deg = to_deg(ch2["phase"])

            # Phase difference
            dphi_deg = (phi2_deg - phi1_deg)
            if WRAP_OUTPUT:
                dphi_deg = wrap_deg_pm180(dphi_deg)

            # Append to buffers
            t_now = time.time() - t0
            times.append(t_now)
            dphis.append(dphi_deg)

            # Update plot window to last WINDOW_S seconds
            # (We always keep a fixed-length deque; x-limits reflect the last time span)
            if len(times) > 1:
                t_min = max(0.0, times[-1] - WINDOW_S)
                ax.set_xlim(t_min, times[-1])
                # Keep a reasonable y-lim around the data with padding
                y_min = min(dphis)
                y_max = max(dphis)
                pad = max(5.0, 0.1 * (y_max - y_min if y_max > y_min else 1.0))
                ax.set_ylim(y_min - pad, y_max + pad)

            # Redraw
            line.set_data(times, dphis)
            fig.canvas.draw_idle()
            plt.pause(0.001)

            # Console print at low rate
            if (time.time() - t_last_print) >= PRINT_EVERY_S:
                print("{:9.1f} {:10.1f} {:10.1f} {:11.3f}".format(
                    t_now, ch1["frequency"], ch2["frequency"], dphi_deg
                ))
                t_last_print = time.time()

            time.sleep(POLL_SEC)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        i.relinquish_ownership()
        # Keep the final plot on screen (optional):
        try:
            plt.ioff()
            plt.show()
        except Exception:
            pass

if __name__ == "__main__":
    main()

