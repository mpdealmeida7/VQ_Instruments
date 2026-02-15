
from __future__ import annotations
"""PhasemeterClient — convenience wrapper for Liquid Instruments Moku Phasemeter.
What it does
- Connect/load and close/release ownership
- Change settings on the fly (front-end + PLL)
- Measure phase difference Δφ = φ2 − φ1
- Live plot Δφ vs time (Matplotlib)
- Sweep/measure Δφ vs frequency
  * internal sweep (client sets PLL frequency)
  * external sweep: YOU control an external AWG and pass frequencies in a loop
- Optional wrapped OR unwrapped Δφ recording for later processing
- Save sweep/time-series data to CSV

Notes
- Requires: `pip install moku matplotlib`
- Phase from API is typically in *cycles*; set phase_units='deg' if your API returns degrees.
- Now supports device-backed acquisition speed (Moku:Lab) and on-the-fly changes via
  set_acquisition_speed()/change_acquisition_speed().
"""
import csv
import os
import time
from datetime import datetime
from math import fmod
from statistics import mean, median
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from collections import deque
import matplotlib.pyplot as plt

try:
    from moku.instruments import Phasemeter  # type: ignore
except Exception:
    Phasemeter = None  # type: ignore

# ---------------------- Acquisition speed helpers (Moku:Lab) ----------------------
# Accepted Moku:Lab strings for Phasemeter acquisition speed.
# See Liquid Instruments Moku API 'set_acquisition_speed' (Moku:Lab) docs.
_MOKULAB_SPEEDS_HZ = {
    "30Hz": 30.0,
    "119Hz": 119.0,
    "477Hz": 477.0,
    "1.9kHz": 1900.0,
    "15.2kHz": 15200.0,
}

def _normalize_speed(s: str) -> str:
    s = str(s).strip()
    # Keep canonical spellings as per API; accept common case variants
    s = s.replace("KHZ", "kHz").replace("Khz", "kHz").replace("kHZ", "kHz")
    return s


class PhasemeterClient:
    def __init__(
        self,
        target: str,
        *,
        phase_units: str = 'cycles',
        default_wrap: bool = True,
        input_range: str = '1Vpp',
        impedance: str = '50Ohm',
        coupling: str = 'DC',
        pll_bandwidth: str = '1kHz',
        # New: device-driven acquisition speed. Replaces client-side 'poll_sec'.
        # Allowed (Moku:Lab): "30Hz", "119Hz", "477Hz", "1.9kHz", "15.2kHz"
        acquisition_speed: str = '119Hz',
    ) -> None:
        self.target = target
        self.phase_units = phase_units
        self.default_wrap = default_wrap
        # Front-end defaults
        self.input_range = input_range
        self.impedance = impedance
        self.coupling = coupling
        # PLL defaults
        self.pll_bandwidth = pll_bandwidth
        # Acquisition speed default + derived poll interval (client throttle)
        self.acquisition_speed = _normalize_speed(acquisition_speed)
        if self.acquisition_speed not in _MOKULAB_SPEEDS_HZ:
            raise ValueError(
                f"Invalid acquisition_speed '{acquisition_speed}'. "
                f"Expected one of {list(_MOKULAB_SPEEDS_HZ.keys())}."
            )
        # NOTE: We keep 'poll_sec' as an internal throttle derived from device speed
        # to minimize code churn. Do not set it directly; use set_acquisition_speed().
        self.poll_sec = 1.0 / _MOKULAB_SPEEDS_HZ[self.acquisition_speed]

        self._inst = None  # type: Optional[Phasemeter]
        self._is_loaded = False

        # Unwrap state (used by unwrapped sweep/recording)
        self._unwrap_last_wrapped = None  # type: Optional[float]
        self._unwrap_last_unwrapped = None  # type: Optional[float]

    # ---------------------- Angle helpers ----------------------
    @staticmethod
    def wrap_deg_pm180(x_deg: float) -> float:
        """Wrap angle to (-180, 180] degrees."""
        y = fmod(x_deg + 180.0, 360.0)
        if y < 0:
            y += 360.0
        return y - 180.0

    def _to_deg(self, phase_value: float) -> float:
        """Convert phase to degrees based on configured units."""
        if str(self.phase_units).lower() == 'deg':
            return float(phase_value)
        return float(phase_value) * 360.0  # cycles -> degrees

    def reset_unwrap(self) -> None:
        """Reset internal unwrapping state (call before a new sweep/recording if desired)."""
        self._unwrap_last_wrapped = None
        self._unwrap_last_unwrapped = None

    def unwrap_step(self, wrapped_deg: float) -> float:
        """Online phase unwrapping (degrees) from a wrapped (-180,180] sequence."""
        if self._unwrap_last_wrapped is None or self._unwrap_last_unwrapped is None:
            self._unwrap_last_wrapped = float(wrapped_deg)
            self._unwrap_last_unwrapped = float(wrapped_deg)
            return float(wrapped_deg)
        w_prev = self._unwrap_last_wrapped
        u_prev = self._unwrap_last_unwrapped
        delta = float(wrapped_deg) - float(w_prev)
        if delta > 180.0:
            delta -= 360.0
        elif delta < -180.0:
            delta += 360.0
        u = float(u_prev) + delta
        self._unwrap_last_wrapped = float(wrapped_deg)
        self._unwrap_last_unwrapped = float(u)
        return float(u)

    # ---------------------- Acquisition speed (device + client) ----------------------
    def set_acquisition_speed(self, speed: str, *, apply_now: bool = True) -> None:
        """
        Set the Phasemeter acquisition speed (Moku:Lab), updating both device and client.
        Allowed values: "30Hz", "119Hz", "477Hz", "1.9kHz", "15.2kHz".
        When successful, also updates the client's polling interval to match.
        """
        s = _normalize_speed(speed)
        if s not in _MOKULAB_SPEEDS_HZ:
            raise ValueError(
                f"Invalid acquisition speed '{speed}'. "
                f"Expected one of {list(_MOKULAB_SPEEDS_HZ.keys())}."
            )
        # Update local state
        self.acquisition_speed = s
        self.poll_sec = 1.0 / _MOKULAB_SPEEDS_HZ[s]
        # Apply to device if connected
        if apply_now and self._inst is not None:
            self._inst.set_acquisition_speed(self.acquisition_speed)

    def change_acquisition_speed(self, speed: str) -> None:
        """
        Explicit convenience alias for on-the-fly changes during live runs.
        Equivalent to set_acquisition_speed(speed, apply_now=True).
        """
        self.set_acquisition_speed(speed, apply_now=True)

    def get_acquisition_speed_cached(self) -> str:
        """Return the client's current acquisition speed string (cached)."""
        return self.acquisition_speed

    # ---------------------- Connection ----------------------
    def load(self, *, f0_hz: Optional[float] = None, configure_frontend: bool = True) -> None:
        """Connect and optionally configure front-end & initial PLL frequency/bandwidth."""
        if Phasemeter is None:
            raise RuntimeError('moku package is not available in this environment. Install and retry.')
        self._inst = Phasemeter(self.target, force_connect=True)
        if configure_frontend:
            self.set_frontend(1)  # uses stored defaults
            self.set_frontend(2)
        if f0_hz is not None:
            self.set_pm_loop(1, frequency=f0_hz, bandwidth=self.pll_bandwidth)
            self.set_pm_loop(2, frequency=f0_hz, bandwidth=self.pll_bandwidth)
        self.reacquire()
        # Apply desired acquisition speed at connect time
        try:
            self._inst.set_acquisition_speed(self.acquisition_speed)
        except Exception:
            # Do not prevent load() from succeeding if speed can't be set; user can retry.
            pass
        self._is_loaded = True

    def close(self) -> None:
        """Release ownership and close the device."""
        if self._inst is not None:
            try:
                self._inst.relinquish_ownership()
            finally:
                self._inst = None
                self._is_loaded = False

    # ---------------------- On-the-fly settings ----------------------
    def set_frontend(
        self,
        channel: int,
        *,
        impedance: Optional[str] = None,
        coupling: Optional[str] = None,
        input_range: Optional[str] = None,
    ) -> None:
        """Set front-end. LI API requires impedance & coupling & range each call."""
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        imp = impedance if impedance is not None else self.impedance
        coup = coupling if coupling is not None else self.coupling
        rng = input_range if input_range is not None else self.input_range
        # Persist as new defaults
        self.impedance, self.coupling, self.input_range = imp, coup, rng
        self._inst.set_frontend(channel=channel, impedance=imp, coupling=coup, range=rng)

    def set_pm_loop(
        self,
        channel: int,
        *,
        frequency: Optional[float] = None,
        bandwidth: Optional[str] = None,
        auto_acquire: bool = False,
    ) -> None:
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        kwargs = {'auto_acquire': auto_acquire}
        if frequency is not None:
            kwargs['frequency'] = float(frequency)
        if bandwidth is not None:
            kwargs['bandwidth'] = bandwidth
        self._inst.set_pm_loop(channel=channel, **kwargs)

    def set_frequency_all(self, f_hz: float, *, reacquire_each_step: bool = True) -> None:
        """Set the same PLL center frequency for both channels."""
        self.set_pm_loop(1, frequency=f_hz)
        self.set_pm_loop(2, frequency=f_hz)
        if reacquire_each_step:
            self.reacquire()

    def set_bandwidth_all(self, bandwidth: str) -> None:
        self.set_pm_loop(1, bandwidth=bandwidth)
        self.set_pm_loop(2, bandwidth=bandwidth)
        self.pll_bandwidth = bandwidth

    def reacquire(self) -> None:
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        self._inst.reacquire()

    # ---------------------- Measurements ----------------------
    def _get_frame(self) -> dict:
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        return self._inst.get_data()

    def read_delta_phi_deg(self, *, mode: str = 'wrapped') -> Tuple[float, dict]:
        """Read Δφ in degrees.
        mode:
        - 'raw'      : φ2−φ1 without wrapping
        - 'wrapped'  : wrapped to (-180,180]
        - 'unwrapped': online unwrapped based on wrapped principal value
        """
        frame = self._get_frame()
        ch1, ch2 = frame['ch1'], frame['ch2']
        phi1_deg = self._to_deg(ch1['phase'])
        phi2_deg = self._to_deg(ch2['phase'])
        raw = phi2_deg - phi1_deg
        wrapped = self.wrap_deg_pm180(raw)
        m = mode.lower().strip()
        if m == 'raw':
            return float(raw), frame
        if m == 'wrapped':
            return float(wrapped), frame
        if m == 'unwrapped':
            return float(self.unwrap_step(wrapped)), frame
        raise ValueError("mode must be one of: 'raw', 'wrapped', 'unwrapped'")

    # ---------------------- Live plot (time) ----------------------
    def live_plot_delta_phi_vs_time(self, *, window_s: float = 60.0, print_every_s: float = 1.0, mode: str = 'wrapped') -> None:
        """Live plot Δφ vs time. In Jupyter, use %matplotlib notebook/widget or the *_jupyter method below."""
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        # Reset unwrap at start if requested mode is unwrapped
        if mode.lower().strip() == 'unwrapped':
            self.reset_unwrap()
        plt.ion()
        fig, ax = plt.subplots(figsize=(8, 4.5))
        line, = ax.plot([], [], lw=1.6, color="#1f77b4")
        ax.set_title(f"Live Phase Difference Δφ ({mode})")
        ax.set_xlabel("Elapsed time [s]")
        ax.set_ylabel("Δφ [deg]")
        ax.grid(True, alpha=0.3)
        # Non-blocking show (helps some backends)
        try:
            plt.show(block=False)
        except TypeError:
            pass
        nmax = max(10, int(window_s / max(self.poll_sec, 1e-3)) + 5)
        times, dphis = deque(maxlen=nmax), deque(maxlen=nmax)
        t0 = time.time()
        t_last_print = t0
        print("Live Δφ (Ctrl+C or Kernel Interrupt to stop)")
        print(f"Target: {self.target}  BW: {self.pll_bandwidth}  mode={mode}")
        print(f"{'t[s]':>9} {'f1[Hz]':>10} {'f2[Hz]':>10} {'Δφ[deg]':>11}")
        print("-" * 46)
        try:
            while True:
                dphi_deg, frame = self.read_delta_phi_deg(mode=mode)
                ch1, ch2 = frame['ch1'], frame['ch2']
                t_now = time.time() - t0
                times.append(t_now)
                dphis.append(dphi_deg)
                if len(times) > 1:
                    t_min = max(0.0, times[-1] - window_s)
                    ax.set_xlim(t_min, times[-1])
                    y_min, y_max = min(dphis), max(dphis)
                    pad = max(5.0, 0.1 * (y_max - y_min if y_max > y_min else 1.0))
                    ax.set_ylim(y_min - pad, y_max + pad)
                    line.set_data(times, dphis)
                    fig.canvas.draw_idle()
                    try:
                        fig.canvas.flush_events()
                    except Exception:
                        pass
                plt.pause(0.001)
                if (time.time() - t_last_print) >= print_every_s:
                    print(f"{t_now:9.1f} {ch1.get('frequency', 0.0):10.1f} {ch2.get('frequency', 0.0):10.1f} {dphi_deg:11.3f}")
                    t_last_print = time.time()
                time.sleep(self.poll_sec)  # derived from acquisition_speed
        except KeyboardInterrupt:
            print("Stopped by user.")
        finally:
            try:
                plt.ioff(); plt.show()
            except Exception:
                pass

    def live_plot_delta_phi_vs_time_jupyter(self, *, window_s: float = 60.0, print_every_s: float = 1.0, mode: str = 'wrapped') -> None:
        """Jupyter-safe live plot (works with %matplotlib inline)."""
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        if mode.lower().strip() == 'unwrapped':
            self.reset_unwrap()
        from IPython.display import display, clear_output
        fig, ax = plt.subplots(figsize=(8, 4.5))
        line, = ax.plot([], [], lw=1.6, color="#1f77b4")
        ax.set_title(f"Live Phase Difference Δφ ({mode})")
        ax.set_xlabel("Elapsed time [s]")
        ax.set_ylabel("Δφ [deg]")
        ax.grid(True, alpha=0.3)
        nmax = max(10, int(window_s / max(self.poll_sec, 1e-3)) + 5)
        times, dphis = deque(maxlen=nmax), deque(maxlen=nmax)
        t0 = time.time()
        t_last_print = t0
        print("Live Δφ (Kernel→Interrupt to stop)")
        print(f"Target: {self.target}  BW: {self.pll_bandwidth}  mode={mode}")
        print(f"{'t[s]':>9} {'f1[Hz]':>10} {'f2[Hz]':>10} {'Δφ[deg]':>11}")
        print("-" * 46)
        try:
            while True:
                dphi_deg, frame = self.read_delta_phi_deg(mode=mode)
                ch1, ch2 = frame['ch1'], frame['ch2']
                t_now = time.time() - t0
                times.append(t_now)
                dphis.append(dphi_deg)
                if len(times) > 1:
                    t_min = max(0.0, times[-1] - window_s)
                    ax.set_xlim(t_min, times[-1])
                    y_min, y_max = min(dphis), max(dphis)
                    pad = max(5.0, 0.1 * (y_max - y_min if y_max > y_min else 1.0))
                    ax.set_ylim(y_min - pad, y_max + pad)
                    line.set_data(times, dphis)
                    clear_output(wait=True)
                    display(fig)
                if (time.time() - t_last_print) >= print_every_s:
                    print(f"{t_now:9.1f} {ch1.get('frequency', 0.0):10.1f} {ch2.get('frequency', 0.0):10.1f} {dphi_deg:11.3f}")
                    t_last_print = time.time()
                time.sleep(self.poll_sec)  # derived from acquisition_speed
        except KeyboardInterrupt:
            print("Stopped by user.")
        finally:
            plt.close(fig)

    # ---------------------- Sweeps ----------------------
    def sweep_phase_vs_frequency(
        self,
        freqs_hz: Iterable[float],
        *,
        settle_s: float = 0.2,
        samples_per_point: int = 5,
        average: str = 'median',
        reacquire_each_step: bool = True,
        mode: str = 'wrapped',
        reset_unwrap: bool = True,
    ) -> List[Dict[str, float]]:
        """Internal sweep: client sets PLL frequency for both channels and measures Δφ.
        Returns a list of dict rows: {frequency_hz, delta_phi_deg}
        (plus extra columns if mode='both').
        """
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        if reset_unwrap:
            self.reset_unwrap()
        avg_fn = median if average.lower().startswith('med') else mean
        rows: List[Dict[str, float]] = []
        for f in freqs_hz:
            self.set_frequency_all(float(f), reacquire_each_step=reacquire_each_step)
            time.sleep(max(0.0, settle_s))
            samples_wrapped: List[float] = []
            samples_unwrapped: List[float] = []
            samples_raw: List[float] = []
            for _ in range(max(1, samples_per_point)):
                raw, _frame = self.read_delta_phi_deg(mode='raw')
                wrapped = self.wrap_deg_pm180(raw)
                unwrapped = self.unwrap_step(wrapped)
                samples_raw.append(raw)
                samples_wrapped.append(wrapped)
                samples_unwrapped.append(unwrapped)
                time.sleep(max(0.0, self.poll_sec))  # derived from acquisition_speed
            row: Dict[str, float] = {'frequency_hz': float(f)}
            m = mode.lower().strip()
            if m == 'raw':
                row['delta_phi_deg'] = float(avg_fn(samples_raw))
            elif m == 'wrapped':
                row['delta_phi_deg'] = float(avg_fn(samples_wrapped))
            elif m == 'unwrapped':
                row['delta_phi_deg'] = float(avg_fn(samples_unwrapped))
            elif m == 'both':
                row['delta_phi_wrapped_deg'] = float(avg_fn(samples_wrapped))
                row['delta_phi_unwrapped_deg'] = float(avg_fn(samples_unwrapped))
                row['delta_phi_raw_deg'] = float(avg_fn(samples_raw))
            else:
                raise ValueError("mode must be one of: 'raw','wrapped','unwrapped','both'")
            rows.append(row)
        return rows

    def sweep_phase_vs_frequency_external(
        self,
        freq_iter: Iterable[float],
        *,
        settle_s: float = 0.0,
        samples_per_point: int = 5,
        average: str = 'median',
        mode: str = 'wrapped',
        reset_unwrap: bool = True,
        set_pll_to_frequency: bool = True,
        reacquire_each_step: bool = True,
        max_points: Optional[int] = None,
        on_step: Optional[Callable[[float], None]] = None,
    ) -> List[Dict[str, float]]:
        """External sweep: YOU control the AWG; pass the frequency values in a loop.
        Typical usage:
            for f in freqs:
                awg.set_frequency(f)
                yield f
        This method then optionally sets the Phasemeter PLL center to f (recommended),
        waits settle_s, samples Δφ, and records wrapped/unwrapped per `mode`.

        Parameters
        - freq_iter: iterable/generator of frequencies (Hz) that you set on the AWG.
        - on_step: optional callback called with f just before measuring (e.g., trigger AWG update).
        - mode: 'wrapped' or 'unwrapped' or 'raw' or 'both'
        - reset_unwrap: reset unwrapping state at the start
        - set_pll_to_frequency: if True, set both channel PLLs to f each step
        Returns: list of dict rows.
        """
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        if reset_unwrap:
            self.reset_unwrap()
        avg_fn = median if average.lower().startswith('med') else mean
        rows: List[Dict[str, float]] = []
        for idx, f in enumerate(freq_iter):
            if max_points is not None and idx >= int(max_points):
                break
            f = float(f)
            # Let user run any external actions (e.g., AWG set) inside this loop if desired
            if on_step is not None:
                on_step(f)
            if set_pll_to_frequency:
                self.set_frequency_all(f, reacquire_each_step=reacquire_each_step)
            if settle_s and settle_s > 0:
                time.sleep(float(settle_s))
            samples_wrapped: List[float] = []
            samples_unwrapped: List[float] = []
            samples_raw: List[float] = []
            for _ in range(max(1, samples_per_point)):
                raw, _frame = self.read_delta_phi_deg(mode='raw')
                wrapped = self.wrap_deg_pm180(raw)
                unwrapped = self.unwrap_step(wrapped)
                samples_raw.append(raw)
                samples_wrapped.append(wrapped)
                samples_unwrapped.append(unwrapped)
                time.sleep(max(0.0, self.poll_sec))  # derived from acquisition_speed
            row: Dict[str, float] = {'frequency_hz': f}
            m = mode.lower().strip()
            if m == 'raw':
                row['delta_phi_deg'] = float(avg_fn(samples_raw))
            elif m == 'wrapped':
                row['delta_phi_deg'] = float(avg_fn(samples_wrapped))
            elif m == 'unwrapped':
                row['delta_phi_deg'] = float(avg_fn(samples_unwrapped))
            elif m == 'both':
                row['delta_phi_wrapped_deg'] = float(avg_fn(samples_wrapped))
                row['delta_phi_unwrapped_deg'] = float(avg_fn(samples_unwrapped))
                row['delta_phi_raw_deg'] = float(avg_fn(samples_raw))
            else:
                raise ValueError("mode must be one of: 'raw','wrapped','unwrapped','both'")
            rows.append(row)
        return rows

    # ---------------------- Printing / plotting sweep ----------------------
    @staticmethod
    def print_sweep(rows: Sequence[Dict[str, float]]) -> None:
        if not rows:
            print('No sweep data.')
            return
        keys = list(rows[0].keys())
        # stable ordering: frequency first
        if 'frequency_hz' in keys:
            keys.remove('frequency_hz')
            keys = ['frequency_hz'] + keys
        header = ' '.join([f"{k:>22}" for k in keys])
        print(header)
        print('-' * len(header))
        for r in rows:
            print(' '.join([f"{r.get(k, float('nan')):22.6f}" for k in keys]))

    @staticmethod
    def plot_sweep(rows: Sequence[Dict[str, float]], *, y_key: str = 'delta_phi_deg', title: str = 'Phase Difference vs Frequency', marker: str = 'o-') -> None:
        if not rows:
            print('No data to plot.')
            return
        if 'frequency_hz' not in rows[0]:
            raise ValueError("rows must contain 'frequency_hz'")
        if y_key not in rows[0]:
            raise ValueError(f"rows must contain '{y_key}'")
        freqs = [float(r['frequency_hz']) for r in rows]
        y = [float(r[y_key]) for r in rows]
        plt.figure(figsize=(7.5, 4.5))
        plt.plot(freqs, y, marker, lw=1.5)
        plt.grid(True, alpha=0.3)
        plt.title(title)
        plt.xlabel('Frequency [Hz]')
        plt.ylabel(f'{y_key} [deg]')
        plt.tight_layout()
        plt.show()

    # ---------------------- CSV helpers ----------------------
    @staticmethod
    def save_rows_to_csv(
        rows: Sequence[Dict[str, Union[float, int, str]]],
        filename: str,
        *,
        include_header: bool = True,
        append: bool = False,
        metadata: Optional[Dict[str, Union[str, float, int]]] = None,
    ) -> str:
        """Save a list of dict rows to CSV. Keys become columns."""
        if not rows:
            raise ValueError('rows is empty; nothing to save.')
        mode = 'a' if append else 'w'
        file_exists = os.path.exists(filename)
        file_empty = (not file_exists) or (os.path.getsize(filename) == 0) or (not append)
        # Column order: frequency_hz first if present, then the rest sorted
        keys = list(rows[0].keys())
        if 'frequency_hz' in keys:
            keys.remove('frequency_hz')
            keys = ['frequency_hz'] + keys
        else:
            keys = sorted(keys)
        with open(filename, mode=mode, newline='', encoding='utf-8') as f:
            if metadata is not None and file_empty:
                f.write(f"# saved_utc={datetime.utcnow().isoformat()}Z")
                for k, v in metadata.items():
                    f.write(f"# {k}={v}\n")
                            
            writer = csv.DictWriter(f, fieldnames=keys)
            if include_header and file_empty:
                writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return os.path.abspath(filename)


__all__ = ['PhasemeterClient']