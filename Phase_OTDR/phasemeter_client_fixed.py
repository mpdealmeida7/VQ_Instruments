
from __future__ import annotations
"""
Phasemeter Client — class wrapper around Liquid Instruments Moku:Lab Phasemeter

Features
- Load/connect and close/release the device
- Change device settings on the fly (front-end, PLL bandwidth/frequency)
- Measure instantaneous phase difference (Δφ = φ2 − φ1)
- Live plot Δφ vs. time (optional convenience)
- Sweep frequency and print/plot Δφ vs. frequency (both channels share the same f)

Notes
- Requires the `moku` Python package and a reachable Moku device.
- Phase units can be 'cycles' (typical from API) or 'deg'.
"""
import time
from math import fmod
from statistics import mean, median
from typing import Iterable, List, Tuple, Optional
from collections import deque

import matplotlib.pyplot as plt

 
from IPython.display import display, clear_output

import csv
import os
from datetime import datetime


try:
    from moku.instruments import Phasemeter  # type: ignore
except Exception:
    Phasemeter = None  # type: ignore


class PhasemeterClient:
    def __init__(
        self,
        target: str,
        *,
        phase_units: str = 'cycles',
        wrap_output: bool = True,
        input_range: str = '1Vpp',
        impedance: str = '50Ohm',
        coupling: str = 'DC',
        pll_bandwidth: str = '1kHz',
        poll_sec: float = 0.1,
    ) -> None:
        self.target = target
        self.phase_units = phase_units
        self.wrap_output = wrap_output
        self.input_range = input_range
        self.impedance = impedance
        self.coupling = coupling
        self.pll_bandwidth = pll_bandwidth
        self.poll_sec = poll_sec

        self._inst = None  # type: Optional[Phasemeter]
        self._is_loaded = False

    @staticmethod
    def _wrap_deg_pm180(x_deg: float) -> float:
        """Wrap angle to (-180, 180] degrees for readability."""
        y = fmod(x_deg + 180.0, 360.0)
        if y < 0:
            y += 360.0
        return y - 180.0

    def _to_deg(self, phase_value: float) -> float:
        """Convert phase to degrees based on configured units."""
        if str(self.phase_units).lower() == 'deg':
            return float(phase_value)
        return float(phase_value) * 360.0

    def load(self, *, f0_hz: Optional[float] = None, configure_frontend: bool = True) -> None:
        """Connect; configure front-end; set initial PLL(s) and reacquire if f0 provided."""
        if Phasemeter is None:
            raise RuntimeError('moku package is not available in this environment. Install and retry.')
        self._inst = Phasemeter(self.target, force_connect=True)
        if configure_frontend:
            self.set_frontend(1, impedance=self.impedance, coupling=self.coupling, input_range=self.input_range)
            self.set_frontend(2, impedance=self.impedance, coupling=self.coupling, input_range=self.input_range)
        if f0_hz is not None:
            self.set_pm_loop(1, frequency=f0_hz, bandwidth=self.pll_bandwidth)
            self.set_pm_loop(2, frequency=f0_hz, bandwidth=self.pll_bandwidth)
            self.reacquire()
        self._is_loaded = True

    def close(self) -> None:
        """Release ownership and close the device."""
        if self._inst is not None:
            try:
                self._inst.relinquish_ownership()
            finally:
                self._inst = None
                self._is_loaded = False
                
                
    
    def set_frontend(
        self,
        channel: int,
        impedance: Optional[str] = None,
        coupling: Optional[str] = None,
        input_range: Optional[str] = None
    ) -> None:
        
        """
        Set the front-end for a channel. The LI API expects all three parameters,
        so we always provide them: any omitted ones fall back to the current
        class defaults.
        """
        
        if self._inst is None:
                raise RuntimeError('Device not loaded. Call load() first.')
            
        imp = impedance if impedance is not None else self.impedance
        coup = coupling if coupling is not None else self.coupling
        rng = input_range if input_range is not None else self.input_range
        
        
        # Persist the new defaults so subsequent partial calls remain consistent
        self.impedance = imp
        self.coupling = coup
        self.input_range = rng

        
        # LI API requires all three args
        self._inst.set_frontend(channel=channel, impedance=imp, coupling=coup, range=rng)


    def set_pm_loop(self, channel: int, *, frequency: Optional[float] = None, bandwidth: Optional[str] = None, auto_acquire: bool = False) -> None:
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        kwargs = {'auto_acquire': auto_acquire}
        if frequency is not None:
            kwargs['frequency'] = frequency
        if bandwidth is not None:
            kwargs['bandwidth'] = bandwidth
        self._inst.set_pm_loop(channel=channel, **kwargs)

    def set_frequency_all(self, f_hz: float, *, reacquire_each_step: bool = True) -> None:
        self.set_pm_loop(1, frequency=f_hz, bandwidth=None)
        self.set_pm_loop(2, frequency=f_hz, bandwidth=None)
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

    def _get_frame(self) -> dict:
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        return self._inst.get_data()

    def read_phase_difference_deg(self) -> Tuple[float, dict]:
        frame = self._get_frame()
        ch1, ch2 = frame['ch1'], frame['ch2']
        phi1_deg = self._to_deg(ch1['phase'])
        phi2_deg = self._to_deg(ch2['phase'])
        dphi_deg = phi2_deg - phi1_deg
        if self.wrap_output:
            dphi_deg = self._wrap_deg_pm180(dphi_deg)
        return dphi_deg, frame
    
    def live_plot_delta_phi_vs_time_jupyter(self, *, window_s: float = 60.0, print_every_s: float = 1.0):
        """
        Jupyter-safe live plot using IPython.display (works with %matplotlib inline).
        Stop with Kernel → Interrupt or Ctrl+C in terminal.
        """
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')


        fig, ax = plt.subplots(figsize=(8, 4.5))
        line, = ax.plot([], [], lw=1.6, color="#1f77b4")
        ax.set_title("Live Phase Difference Δφ = φ₂ − φ₁")
        ax.set_xlabel("Elapsed time [s]")
        ax.set_ylabel("Δφ [deg]")
        ax.grid(True, alpha=0.3)
        nmax = max(10, int(window_s / max(self.poll_sec, 1e-3)) + 5)
        times, dphis = deque(maxlen=nmax), deque(maxlen=nmax)

        t0 = time.time()
        t_last_print = t0
        print("\nLive Δφ (Kernel→Interrupt to stop)")
        print(f"\n{'t[s]':>9} {'f1[Hz]':>10} {'f2[Hz]':>10} {'Δφ[deg]':>11}")
        print("-" * 46)

        try:
            while True:
                dphi_deg, frame = self.read_phase_difference_deg()
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

                # Re-render output cell
                clear_output(wait=True)
                display(fig)

                if (time.time() - t_last_print) >= print_every_s:
                    print(f"\n{t_now:9.1f} {ch1['frequency']:10.1f} {ch2['frequency']:10.1f} {dphi_deg:11.3f}")
                    t_last_print = time.time()

                time.sleep(self.poll_sec)
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
         plt.close(fig)
    
    def sweep_phase_vs_frequency(
        self,
        freqs_hz: Iterable[float],
        *,
        settle_s: float = 0.2,
        samples_per_point: int = 5,
        average: str = 'median',
        reacquire_each_step: bool = True
    ) -> List[Tuple[float, float]]:
        if self._inst is None:
            raise RuntimeError('Device not loaded. Call load() first.')
        results: List[Tuple[float, float]] = []
        avg_fn = median if average.lower().startswith('med') else mean

        for f in freqs_hz:
            self.set_frequency_all(float(f), reacquire_each_step=reacquire_each_step)
            time.sleep(max(0.0, settle_s))
            samples = []
            for _ in range(max(1, samples_per_point)):
                dphi_deg, _ = self.read_phase_difference_deg()
                samples.append(dphi_deg)
                time.sleep(max(0.0, self.poll_sec))
            results.append((float(f), float(avg_fn(samples))))
        return results

    def print_sweep(self, sweep_data: List[Tuple[float, float]]) -> None:
        print(f"{'f [Hz]':>14} {'Δφ [deg]':>12}")
        print('-' * 27)
        for f, dphi in sweep_data:
            print(f"{f:14.3f} {dphi:12.3f}")

    def plot_sweep(self, sweep_data: List[Tuple[float, float]], *, title: str = 'Phase Difference vs Frequency', marker: str = 'o-') -> None:
        if not sweep_data:
            print('No data to plot.')
            return
        freqs = [p[0] for p in sweep_data]
        dphi = [p[1] for p in sweep_data]
        plt.figure(figsize=(7.5, 4.5))
        plt.plot(freqs, dphi, marker, lw=1.5)
        plt.grid(True, alpha=0.3)
        plt.title(title)
        plt.xlabel('Frequency [Hz]')
        plt.ylabel('Δφ [deg]')
        plt.tight_layout()
        plt.show()
    
    def save_sweep_to_csv(
        self,
        sweep_data: List[Tuple[float, float]],
        filename: str,
        *,
        include_header: bool = True,
        extra_metadata: Optional[dict] = None
        ) -> str:
        
        """
            Save sweep data [(f_hz, dphi_deg), ...] to a CSV file.

            Parameters
            ----------
            sweep_data : list of (float, float)
                Output from sweep_phase_vs_frequency(): (frequency_hz, delta_phi_deg)
            filename : str
                Path to CSV file.
            include_header : bool
                Write header row if file is new/empty.
            extra_metadata : dict | None
                Optional metadata written as commented lines at top (prefixed with '# ').

            Returns
            -------
            str
                Absolute path to the saved file.
        """
        
        if not sweep_data:
            raise ValueError("sweep_data is empty; nothing to save.")
        
        
        file_exists = os.path.exists(filename)
        file_empty = (not file_exists) or (os.path.getsize(filename) == 0)
        
        with open(filename, mode="a", newline="", encoding="utf-8") as f:
            # Optional metadata block (only when creating a new file)
            if (extra_metadata is not None) and file_empty:
                f.write(f"# saved_utc={datetime.utcnow().isoformat()}Z\n")
                for k, v in extra_metadata.items():
                    f.write(f"# {k}={v}\n")
                    
            writer = csv.writer(f)
            
            if include_header and file_empty:
                writer.writerow(["frequency_hz", "delta_phi_deg"])
                
            
            for freq_hz, dphi_deg in sweep_data:
                writer.writerow([float(freq_hz), float(dphi_deg)])

        return os.path.abspath(filename)


__all__ = ['PhasemeterClient']
