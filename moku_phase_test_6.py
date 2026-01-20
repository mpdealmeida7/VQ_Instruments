
#!/usr/bin/env python3
"""
Moku:Lab Phasemeter — Compare Wrapped vs Unwrapped (Cumulative) Phase Difference

- Configures Phasemeter (50 Ω, DC, user-selectable range).
- Seeds PLLs at 100 kHz with adjustable bandwidth.
- Reads phases via get_data(), computes:
    Δφ_wrapped(t)   = wrap_{(-180,180]}(φ2 - φ1)
    Δφ_cum(t)       = sum_k Δφ_wrapped[k]   (cumulative over time)
- Live plotting: top panel = wrapped Δφ, bottom panel = cumulative Δφ.
- Console prints periodic status.
- Stop with Ctrl+C.

References:
  set_frontend: https://apis.liquidinstruments.com/api/reference/phasemeter/set_frontend.html
  set_pm_loop:  https://apis.liquidinstruments.com/api/reference/phasemeter/set_pm_loop.html
  get_data:     https://apis.liquidinstruments.com/api/reference/phasemeter/get_data.html
  Phase units (cycles in legacy streaming docs): https://pymoku.readthedocs.io/en/2.8.2/phasemeter.html
"""

import time
from math import fmod
from collections import deque
import matplotlib.pyplot as plt
from moku.instruments import Phasemeter

# ---------- USER SETTINGS ----------
MOKU_TARGET   = 'localhost:8090'  # e.g., "192.168.1.100"
F_TONE_HZ     = 1e6           # known tone ~100 kHz
PLL_BW        = "1kHz"              # '1Hz','10Hz','100Hz','1kHz','10kHz','100kHz' (Moku:Lab supports to 100kHz)
INPUT_RANGE   = "10Vpp"             # choose "1Vpp" if AWG amplitude is small
POLL_SEC      = 0.10                # read & plot interval
PRINT_EVERY_S = 1.0                 # console print period
WINDOW_S      = 60.0                # time window shown in plots
PHASE_UNITS   = "cycles"            # "cycles" (typical) or "deg"
# -----------------------------------

def wrap_deg_pm180(x_deg: float) -> float:
    """Wrap angle to (-180, 180] degrees."""
    y = fmod(x_deg + 180.0, 360.0)
    if y < 0:
        y += 360.0
    return y - 180.0

def to_deg(phase_value):
    """Convert phase to degrees depending on reported units."""
    if PHASE_UNITS.lower() == "deg":
        return float(phase_value)
    return float(phase_value) * 360.0  # cycles -> degrees

def main():
    i = Phasemeter(MOKU_TARGET, force_connect=True)

    try:
        # --- Front-ends: 50 Ω, DC, selected range ---
        i.set_frontend(channel=1, impedance="50Ohm", coupling="DC", range=INPUT_RANGE)
        i.set_frontend(channel=2, impedance="50Ohm", coupling="DC", range=INPUT_RANGE)

        # --- PLLs: 100 kHz seed, specified BW ---
        i.set_pm_loop(channel=1, auto_acquire=False, frequency=F_TONE_HZ, bandwidth=PLL_BW)
        i.set_pm_loop(channel=2, auto_acquire=False, frequency=F_TONE_HZ, bandwidth=PLL_BW)

        # Ensure fresh lock
        i.reacquire()
       
        # --- Live plots (two subplots) ---
        plt.ion()
        fig, (ax_wrapped, ax_cum) = plt.subplots(
            2, 1, figsize=(9, 6.5), sharex=True, constrained_layout=True
        )

        # Wrapped Δφ plot
        line_wrapped, = ax_wrapped.plot([], [], lw=1.6, color="#1f77b4")
        ax_wrapped.set_title("Instantaneous Wrapped Phase Difference  Δφ_wrapped(t)")
        ax_wrapped.set_ylabel("Δφ_wrapped [deg]")
        ax_wrapped.grid(True, alpha=0.3)

        # Cumulative Δφ plot
        line_cum, = ax_cum.plot([], [], lw=1.8, color="#d62728")
        ax_cum.set_title("Unwrapped (Cumulative) Phase Difference  Δφ_cum(t)")
        ax_cum.set_xlabel("Elapsed time [s]")
        ax_cum.set_ylabel("Δφ_cum [deg]")
        ax_cum.grid(True, alpha=0.3)

        # Data buffers
        maxlen = int(WINDOW_S / POLL_SEC) + 50
        times      = deque(maxlen=maxlen)
        dphi_wrap  = deque(maxlen=maxlen)
        dphi_cum   = deque(maxlen=maxlen)

        t0 = time.time()
        t_last_print = t0

        # Running cumulative sum
        delta_phi_cumulative = 0.0
        first_sample = True

        print("\nMoku:Lab Phasemeter — Wrapped vs Unwrapped Δφ (Ctrl+C to stop)")
        print("Target: {} | PLL f0: {:.1f} Hz | BW: {}".format(MOKU_TARGET, F_TONE_HZ, PLL_BW))
        print("{:>9} {:>10} {:>10} {:>14} {:>14}".format("t[s]", "f1[Hz]", "f2[Hz]",
                                                         "Δφ_wrapped[deg]", "Δφ_cum[deg]"))
        print("-" * 70)

        while True:
            frame = i.get_data()  # {'ch1': {...}, 'ch2': {...}, ...}
            ch1 = frame["ch1"]
            ch2 = frame["ch2"]

            # Convert phases to degrees
            phi1_deg = to_deg(ch1["phase"])
            phi2_deg = to_deg(ch2["phase"])

            # Instantaneous difference (raw) and wrapped value
            dphi_raw_deg = phi2_deg - phi1_deg
            dphi_wrapped_deg = wrap_deg_pm180(dphi_raw_deg)

            # Cumulative update
            if first_sample:
                delta_phi_cumulative = dphi_wrapped_deg
                first_sample = False
            else:
                delta_phi_cumulative += dphi_wrapped_deg

            t_now = time.time() - t0
            times.append(t_now)
            dphi_wrap.append(dphi_wrapped_deg)
            dphi_cum.append(delta_phi_cumulative)

            # Update wrapped plot
            if len(times) > 1:
                t_min = max(0.0, times[-1] - WINDOW_S)
                ax_wrapped.set_xlim(t_min, times[-1])
                # keep ±200° or autoscale around data with padding; here we autoscale
                y_min_w, y_max_w = min(dphi_wrap), max(dphi_wrap)
                span_w = max(10.0, (y_max_w - y_min_w))
                pad_w = 0.15 * span_w
                ax_wrapped.set_ylim(y_min_w - pad_w, y_max_w + pad_w)

            line_wrapped.set_data(times, dphi_wrap)

            # Update cumulative plot
            if len(times) > 1:
                t_min = max(0.0, times[-1] - WINDOW_S)
                ax_cum.set_xlim(t_min, times[-1])
                y_min_c, y_max_c = min(dphi_cum), max(dphi_cum)
                span_c = max(10.0, (y_max_c - y_min_c))
                pad_c = 0.15 * span_c
                ax_cum.set_ylim(y_min_c - pad_c, y_max_c + pad_c)

            line_cum.set_data(times, dphi_cum)

            fig.canvas.draw_idle()
            plt.pause(0.001)

            # Console status at low rate
            if (time.time() - t_last_print) >= PRINT_EVERY_S:
                print("{:9.1f} {:10.1f} {:10.1f} {:14.3f} {:14.3f}".format(
                    t_now, ch1["frequency"], ch2["frequency"],
                    dphi_wrapped_deg, delta_phi_cumulative
                ))
                t_last_print = time.time()

            time.sleep(POLL_SEC)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        i.relinquish_ownership()
        try:
            plt.ioff()
            plt.show()
        except Exception:
            pass

if __name__ == "__main__":
    main()
