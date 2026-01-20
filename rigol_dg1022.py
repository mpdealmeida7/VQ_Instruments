
# rigol_dg1022.py
"""
Lightweight SCPI wrapper for the Rigol DG1022 / DG1022A function generator
using PyVISA. Includes helpers for duty cycle (square), ramp symmetry,
burst/sweep configuration, and arbitrary waveform upload.

Tested against the DG1000-series programming model.

Requirements:
    - pyvisa (NI-VISA or pyvisa-py backend)

Author: Marcelo Pereira de Almeida
"""
from __future__ import annotations
import pyvisa
from typing import Iterable, Optional, Sequence


class RigolDG1022:
    VALID_WAVES = {"SIN", "SQU", "RAMP", "PULSE", "NOIS", "ARB", "DC", "USER"}

    def __init__(
        self,
        resource: str,
        backend: Optional[str] = None,
        timeout_ms: int = 5000,
        write_termination: str = "\n",
        read_termination: str = "\n",
        auto_open: bool = True,
    ) -> None:
        self.resource_name = resource
        self.backend = backend
        self.timeout_ms = timeout_ms
        self.write_termination = write_termination
        self.read_termination = read_termination
        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst: Optional[pyvisa.resources.MessageBasedResource] = None
        if auto_open:
            self.open()

    # ----------------------- lifecycle / context mgr -----------------------
    def open(self) -> None:
        if self._inst is not None:
            return
        self._rm = pyvisa.ResourceManager(self.backend) if self.backend else pyvisa.ResourceManager()
        self._inst = self._rm.open_resource(self.resource_name)
        self._inst.timeout = self.timeout_ms
        self._inst.write_termination = self.write_termination
        self._inst.read_termination = self.read_termination

    def close(self) -> None:
        try:
            if self._inst is not None:
                self._inst.close()
        finally:
            self._inst = None
            if self._rm is not None:
                self._rm.close()
                self._rm = None

    def __enter__(self) -> "RigolDG1022":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ----------------------------- I/O helpers -----------------------------
    def write(self, cmd: str) -> None:
        if self._inst is None:
            raise RuntimeError("Instrument not open. Call open() first.")
        self._inst.write(cmd)

    def query(self, cmd: str) -> str:
        if self._inst is None:
            raise RuntimeError("Instrument not open. Call open() first.")
        return self._inst.query(cmd)

    def opc(self) -> None:
        _ = self.query("*OPC?")

    # ------------------------------- basics --------------------------------
    @property
    def idn(self) -> str:
        return self.query("*IDN?").strip()

    @staticmethod
    def _validate_ch(ch: int) -> None:
        if ch not in (1, 2):
            raise ValueError("Channel must be 1 or 2.")

    @staticmethod
    def _chsuffix(ch: int) -> str:
        return "" if ch == 1 else ":CH2"

    # --------------------------- output controls ---------------------------
    def output_on(self, ch: int) -> None:
        self._validate_ch(ch)
        self.write(f":OUTP{ch} ON")

    def output_off(self, ch: int) -> None:
        self._validate_ch(ch)
        self.write(f":OUTP{ch} OFF")

    def set_load(self, ch: int, load: str) -> None:
        self._validate_ch(ch)
        load_norm = str(load).strip().upper()
        if load_norm not in {"50", "INF"}:
            raise ValueError("load must be '50' or 'INF'")
        self.write(f":OUTP{ch}:LOAD {load_norm}")

    def set_phase_deg(self, ch: int, phase_deg: float) -> None:
        self._validate_ch(ch)
        self.write(f":SOURce{ch}:PHAS {phase_deg}")
        self.opc()

    def sync_phase(self, ch: int) -> None:
        self._validate_ch(ch)
        self.write(f":SOURce{ch}:PHAS:SYNC")
        self.opc()

    # --------------------------- waveform apply ----------------------------
    def set_waveform(
        self, ch: int, wave: str, freq_hz: float, ampl_vpp: float, offset_v: float = 0.0
    ) -> None:
        self._validate_ch(ch)
        wave = wave.strip().upper()
        if wave == "USER":
            wave = "ARB"  # allow alias
        if wave not in self.VALID_WAVES:
            raise ValueError(f"wave must be one of {sorted(self.VALID_WAVES)}")
        # Use SOURce<n>:APPLy:<WAVE> to match many SCPI examples
        cmd = f":SOURce{ch}:APPLy:{wave} {freq_hz},{ampl_vpp},{offset_v}"
        self.write(cmd)
        self.opc()

    # ------------------------- square/ramp helpers -------------------------
    def set_square_duty(self, ch: int, duty_percent: float) -> None:
        """Set square duty cycle (percent, 0-100)."""
        self._validate_ch(ch)
        if not (0.0 <= duty_percent <= 100.0):
            raise ValueError("duty_percent must be between 0 and 100")
        suffix = self._chsuffix(ch)
        self.write(f"FUNCtion:SQUare:DCYCle{suffix} {duty_percent}")
        self.opc()

    def set_ramp_symmetry(self, ch: int, symmetry_percent: float) -> None:
        """Set ramp symmetry (percent of period rising vs falling, 0-100)."""
        self._validate_ch(ch)
        if not (0.0 <= symmetry_percent <= 100.0):
            raise ValueError("symmetry_percent must be between 0 and 100")
        suffix = self._chsuffix(ch)
        self.write(f"FUNCtion:RAMP:SYMMetry{suffix} {symmetry_percent}")
        self.opc()

    # ------------------------------ burst ----------------------------------
    def configure_burst(
        self,
        ch: int,
        enable: bool = True,
        mode: str = "TRIG",  # TRIG or GATe
        ncycles: Optional[int] = None,  # valid in TRIG mode
        trig_source: str = "INT",  # INT|EXT|MAN
        phase_deg: Optional[float] = None,
    ) -> None:
        """Configure burst for a channel.

        Notes:
            - In TRIG mode, ncycles specifies number of cycles per burst.
            - Trigger source can be INT (timed), EXT (rear BNC), or MAN (software).
        """
        self._validate_ch(ch)
        suffix = self._chsuffix(ch)
        mode = mode.strip().upper()
        if mode not in {"TRIG", "GAT", "GATE", "GATe"}:
            raise ValueError("mode must be 'TRIG' or 'GATE'")
        trig_source = trig_source.strip().upper()
        if trig_source not in {"INT", "EXT", "MAN"}:
            raise ValueError("trig_source must be 'INT', 'EXT', or 'MAN'")
        # normalize gate spelling
        mode_kw = "GATe" if mode.startswith("GAT") else "TRIG"

        # Order: program parameters first, then enable
        self.write(f"BURSt:MODE{suffix} {mode_kw}")
        if mode_kw == "TRIG" and ncycles is not None:
            if ncycles < 1:
                raise ValueError("ncycles must be >= 1")
            self.write(f"BURSt:NCYCles{suffix} {ncycles}")
        if phase_deg is not None:
            self.write(f"BURSt:PHASe{suffix} {phase_deg}")
        self.write(f"TRIGger:SOURce{suffix} {trig_source}")
        self.write(f"BURSt:STATe{suffix} {'ON' if enable else 'OFF'}")
        self.opc()

    def burst_trigger(self, ch: int) -> None:
        """Issue a manual trigger (use when TRIGger:SOURce is MAN)."""
        self._validate_ch(ch)
        suffix = self._chsuffix(ch)
        self.write(f"TRIGger:SINGle{suffix}")

    # ------------------------------ sweep ----------------------------------
    def configure_sweep(
        self,
        ch: int,
        start_hz: float,
        stop_hz: float,
        time_s: float,
        spacing: str = "LIN",  # LIN or LOG
        trig_source: str = "INT",  # INT|EXT|MAN
        direction: Optional[str] = None,  # optionally 'UP', 'DOWN' or 'UPDOWN'
        enable: bool = True,
    ) -> None:
        """Configure frequency sweep for a channel."""
        self._validate_ch(ch)
        suffix = self._chsuffix(ch)
        spacing = spacing.strip().upper()
        if spacing not in {"LIN", "LOG"}:
            raise ValueError("spacing must be LIN or LOG")
        trig_source = trig_source.strip().upper()
        if trig_source not in {"INT", "EXT", "MAN"}:
            raise ValueError("trig_source must be INT, EXT, or MAN")

        self.write(f"SWEep:SPACing{suffix} {spacing}")
        self.write(f"SWEep:STARt{suffix} {start_hz}")
        self.write(f"SWEep:STOP{suffix} {stop_hz}")
        self.write(f"SWEep:TIME{suffix} {time_s}")
        if direction:
            direction = direction.strip().upper()
            if direction not in {"UP", "DOWN", "UPDOWN"}:
                raise ValueError("direction must be UP, DOWN, or UPDOWN")
            self.write(f"SWEep:DIRection{suffix} {direction}")
        self.write(f"TRIGger:SOURce{suffix} {trig_source}")
        self.write(f"SWEep:STATe{suffix} {'ON' if enable else 'OFF'}")
        self.opc()

    # ------------------------ arbitrary waveform ---------------------------
    @staticmethod
    def _validate_arb_points(points: Sequence[int]) -> None:
        if not points:
            raise ValueError("points must be a non-empty sequence")
        if len(points) > 4096:
            raise ValueError("DG1022 supports up to 4096 points in volatile ARB")
        for v in points:
            if not (0 <= int(v) <= 16383):
                raise ValueError("ARB point values must be 0..16383 (14-bit)")

    def upload_arb_points(
        self,
        ch: int,
        points: Sequence[int],
        name: Optional[str] = None,
        select_after: bool = True,
    ) -> None:
        """Upload an arbitrary waveform to volatile memory and optionally store it.

        Args:
            ch: channel number (1 or 2)
            points: iterable of integers in [0, 16383], up to 4096 samples
            name: if provided, the waveform will be copied from VOLATILE to
                  non-volatile memory under this name
            select_after: if True, select the uploaded ARB for output on the
                  target channel (FUNCtion:USER) and keep it active
        """
        self._validate_ch(ch)
        self._validate_arb_points(points)
        # Send as comma-separated ASCII integers
        payload = ",".join(str(int(v)) for v in points)
        self.write(f"DATA VOLATILE,{payload}")
        self.opc()
        if name:
            # Store to a named non-volatile slot
            safe = name.strip().replace(' ', '_')[:12]
            self.write(f"DATA:COPY {safe},VOLATILE")
            self.opc()
        if select_after:
            # Select USER/ARB waveform on the specified channel and keep current freq/amp/offset
            suffix = self._chsuffix(ch)
            self.write(f"FUNCtion:USER{suffix}")
            self.opc()

    # ------------------------- convenience routine -------------------------
    def enable_sine_both(
        self,
        freq_hz_ch1: float,
        freq_hz_ch2: float,
        vpp: float = 2.0,
        offset_v: float = 0.0,
        load: str = "50",
        phase_deg_ch2: float = 0.0,
    ) -> None:
        self.set_load(1, load)
        self.set_load(2, load)
        self.set_waveform(1, "SIN", freq_hz_ch1, vpp, offset_v)
        self.set_waveform(2, "SIN", freq_hz_ch2, vpp, offset_v)
        if phase_deg_ch2:
            self.set_phase_deg(2, phase_deg_ch2)
        self.output_on(1)
        self.output_on(2)

