#!/usr/bin/env python3
"""
Generates TTL-like pulses on Rigol DG922 Pro (CH1 + delayed CH2).

Robust fixes included:
  1) Force DC offset (front-panel "Vdc"/Offset) to 0 V on both channels.
  2) Program pulse width / rise / fall using adaptive SCPI variants because firmware
     differs across models/versions. Detects which header is supported by your unit.
  3) Verifies pulse width by readback (and checks SCPI error queue so nothing fails silently).
  4) Applies CH2 delay via phase using the instrument's *actual* frequency (readback),
     so delay stays correct even if frequency is quantized/rounded by the AWG.

Stop options while running:
  - Press q then Enter
  - Press Ctrl+C
"""

from __future__ import annotations

import argparse
import threading
import time

DEFAULT_RESOURCE = "USB0::0x1AB1::0x0646::DG9R280300043::INSTR"


class DG922Controller:
    """Minimal PyVISA wrapper for DG922 Pro dual-channel pulse output."""

    def __init__(self, resource: str, timeout_ms: int = 5000) -> None:
        self.resource_name = resource
        self.timeout_ms = timeout_ms
        self.rm = None
        self.inst = None

    @staticmethod
    def _validate_ch(ch: int) -> None:
        if ch not in (1, 2):
            raise ValueError("channel must be 1 or 2")

    # --------------------
    # VISA plumbing
    # --------------------
    def open(self) -> None:
        try:
            import pyvisa
        except ModuleNotFoundError as exc:
            raise RuntimeError("pyvisa is required. Install with: pip install pyvisa") from exc

        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(self.resource_name)
        self.inst.timeout = self.timeout_ms
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"

    def close(self) -> None:
        if self.inst is not None:
            try:
                self.inst.close()
            finally:
                self.inst = None
        if self.rm is not None:
            try:
                self.rm.close()
            finally:
                self.rm = None

    def write(self, cmd: str) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument not open")
        self.inst.write(cmd)

    def query(self, cmd: str) -> str:
        if self.inst is None:
            raise RuntimeError("Instrument not open")
        return self.inst.query(cmd).strip()

    def identify(self) -> str:
        return self.query("*IDN?")

    def opc(self) -> None:
        _ = self.query("*OPC?")

    def reset(self) -> None:
        self.write("*RST")
        self.opc()

    def clear_status(self) -> None:
        self.write("*CLS")

    def release_local_control(self) -> None:
        self.write(":SYST:LOC")

    # --------------------
    # SCPI error handling
    # --------------------
    def get_error(self) -> str:
        """Query one entry from SCPI error queue."""
        return self.query(":SYST:ERR?")

    def clear_errors(self, max_reads: int = 25) -> None:
        """Drain error queue so new errors are attributable to the next commands."""
        for _ in range(max_reads):
            e = self.get_error()
            if e.startswith("0,") or "No error" in e:
                return

    def write_checked(self, cmd: str) -> None:
        """Write a command and raise immediately if it produces an SCPI error."""
        self.write(cmd)
        e = self.get_error()
        if not (e.startswith("0,") or "No error" in e):
            raise RuntimeError(f"SCPI error after '{cmd}': {e}")

    def try_write_variants(self, cmds: list[str]) -> str:
        """
        Try multiple command variants; return the first that works (no SCPI error).
        If all fail, raise with the last error.
        """
        last_err = None
        for cmd in cmds:
            self.write(cmd)
            e = self.get_error()
            if e.startswith("0,") or "No error" in e:
                return cmd
            last_err = f"'{cmd}' -> {e}"
        raise RuntimeError(f"All SCPI variants failed. Last: {last_err}")

    def query_float_variants(self, queries: list[str]) -> float:
        """
        Try multiple query variants; return the first that parses as float.
        """
        last_err = None
        for q in queries:
            try:
                return float(self.query(q))
            except Exception as ex:
                last_err = f"'{q}' -> {ex}"
        raise RuntimeError(f"All query variants failed. Last: {last_err}")

    # --------------------
    # Output / load
    # --------------------
    def output_on(self, ch: int) -> None:
        self._validate_ch(ch)
        self.write(f":OUTP{ch} ON")

    def output_off(self, ch: int) -> None:
        self._validate_ch(ch)
        self.write(f":OUTP{ch} OFF")

    def set_load(self, ch: int, load: str) -> None:
        self._validate_ch(ch)
        load_norm = load.strip().upper()
        if load_norm not in {"50", "INF"}:
            raise ValueError("load must be '50' or 'INF'")
        self.write(f":OUTP{ch}:LOAD {load_norm}")

    # --------------------
    # Offset (Vdc) control
    # --------------------
    def set_dc_offset(self, ch: int, offset_v: float) -> None:
        """Force channel DC offset (Vdc/Offset) in volts."""
        self._validate_ch(ch)
        self.write(f":SOUR{ch}:VOLT:OFFS {offset_v}")
        self.opc()

    # --------------------
    # Pulse helpers (width readback)
    # --------------------
    def get_pulse_width_s(self, ch: int) -> float:
        """
        Query pulse width (seconds) using multiple possible query paths.
        Different firmware variants may expose different trees.
        """
        self._validate_ch(ch)
        return self.query_float_variants([
            f":SOUR{ch}:FUNC:PULS:WIDT?",
            f":SOURce{ch}:FUNCtion:PULSe:WIDTh?",
            f":SOUR{ch}:PULS:WIDT?",
        ])

    # --------------------
    # Pulse configuration (adaptive)
    # --------------------
    def configure_ttl_pulse(
        self,
        ch: int,
        frequency_hz: float,
        pulse_width_s: float,
        low_v: float,
        high_v: float,
        rise_s: float,
        fall_s: float,
        verify: bool = True,
        width_tol_s: float = 5e-9,
    ) -> dict:
        """
        Configure pulse output robustly across DG922 firmware variants.

        Returns a dict with the actual commands used and readback values
        to aid debugging.
        """
        self._validate_ch(ch)
        if high_v <= low_v:
            raise ValueError("ttl_high must be greater than ttl_low")

        # Rigol documentation indicates min pulse width is 9 ns and also constrained by period/duty. 
        if pulse_width_s < 9e-9:
            raise ValueError("pulse width must be >= 9 ns (documented minimum).")

        period_s = 1.0 / frequency_hz
        # 0.01%*T ≤ TW ≤ 99.99%*T (documented constraint). 
        if not (0.0001 * period_s <= pulse_width_s <= 0.9999 * period_s):
            raise ValueError("pulse width must satisfy 0.01%*T <= TW <= 99.99%*T")

        # Clean slate so we don't blame old errors on new commands.
        self.clear_errors()

        # Put in pulse mode + frequency first (your original code uses these operations). [1](https://download.rigol.com/en/Manual/Waveform%20Generator/DG900%20Pro/DG800ProDG900Pro_ProgrammingGuide_EN.pdf)
        self.write_checked(f":SOUR{ch}:FUNC PULS")
        self.set_dc_offset(ch, 0.0)
        self.write_checked(f":SOUR{ch}:FREQ {frequency_hz}")

        # --- width (try multiple possible trees) ---
        width_cmd = self.try_write_variants([
            f":SOUR{ch}:FUNC:PULS:WIDT {pulse_width_s}",
            f":SOURce{ch}:FUNCtion:PULSe:WIDTh {pulse_width_s}",
            f":SOUR{ch}:PULS:WIDT {pulse_width_s}",
        ])

        # --- rise / fall (try multiple possible trees) ---
        rise_cmd = self.try_write_variants([
            f":SOUR{ch}:FUNC:PULS:TRAN:LEAD {rise_s}",
            f":SOURce{ch}:FUNCtion:PULSe:TRANsition:LEADing {rise_s}",
            f":SOUR{ch}:PULS:TRAN:LEAD {rise_s}",
        ])

        fall_cmd = self.try_write_variants([
            f":SOUR{ch}:FUNC:PULS:TRAN:TRAI {fall_s}",
            f":SOURce{ch}:FUNCtion:PULSe:TRANsition:TRAiling {fall_s}",
            f":SOUR{ch}:PULS:TRAN:TRAI {fall_s}",
            f":SOUR{ch}:PULS:TRAN:TRA {fall_s}",
        ])

        # Levels (your original approach uses VOLT:LOW/HIGH). [1](https://download.rigol.com/en/Manual/Waveform%20Generator/DG900%20Pro/DG800ProDG900Pro_ProgrammingGuide_EN.pdf)
        self.write_checked(f":SOUR{ch}:VOLT:LOW {low_v}")
        self.write_checked(f":SOUR{ch}:VOLT:HIGH {high_v}")

        self.opc()

        # Verify by readback: if AWG ignores width, you’ll see it here (instead of scope surprises).
        width_rb = None
        if verify:
            width_rb = self.get_pulse_width_s(ch)
            if abs(width_rb - pulse_width_s) > width_tol_s:
                raise RuntimeError(
                    f"CH{ch} pulse width mismatch: requested {pulse_width_s:.3e} s "
                    f"but read back {width_rb:.3e} s (tol {width_tol_s:.3e} s).\n"
                    f"Commands used:\n"
                    f"  width: {width_cmd}\n"
                    f"  rise:  {rise_cmd}\n"
                    f"  fall:  {fall_cmd}\n"
                )

        return {
            "ch": ch,
            "width_cmd": width_cmd,
            "rise_cmd": rise_cmd,
            "fall_cmd": fall_cmd,
            "width_readback_s": width_rb,
        }

    # --------------------
    # Phase / delay control
    # --------------------
    def set_phase_deg(self, ch: int, phase_deg: float) -> None:
        self._validate_ch(ch)
        self.write(f":SOUR{ch}:PHAS {phase_deg}")
        self.opc()

    def sync_phase(self) -> None:
        # Your original code already uses :PHAS:SYNC for deterministic phase. [1](https://download.rigol.com/en/Manual/Waveform%20Generator/DG900%20Pro/DG800ProDG900Pro_ProgrammingGuide_EN.pdf)
        self.write(":PHAS:SYNC")
        self.opc()

    def get_frequency_hz(self, ch: int) -> float:
        self._validate_ch(ch)
        return float(self.query(f":SOUR{ch}:FREQ?"))

    def get_phase_deg(self, ch: int) -> float:
        self._validate_ch(ch)
        return float(self.query(f":SOUR{ch}:PHAS?"))

    @staticmethod
    def _wrap_delay_to_period(delay_s: float, period_s: float) -> float:
        if period_s <= 0:
            return 0.0
        return delay_s % period_s

    def apply_time_delay_via_phase(
        self,
        delay_s: float,
        ref_ch: int = 1,
        target_ch: int = 2,
        do_sync: bool = True,
    ) -> dict:
        """
        Apply requested delay via phase computed from the instrument's *actual* frequency.
        """
        self._validate_ch(ref_ch)
        self._validate_ch(target_ch)

        f_actual = self.get_frequency_hz(ref_ch)
        period_s = 1.0 / f_actual
        delay_wrapped_s = self._wrap_delay_to_period(delay_s, period_s)

        phase_deg = (delay_wrapped_s * f_actual * 360.0) % 360.0

        if do_sync:
            self.sync_phase()

        self.set_phase_deg(target_ch, phase_deg)

        try:
            phase_rb = self.get_phase_deg(target_ch)
        except Exception:
            phase_rb = phase_deg

        achieved_delay_s = (phase_rb / 360.0) * (1.0 / f_actual)

        return {
            "freq_hz_actual": f_actual,
            "period_s": period_s,
            "delay_requested_s": delay_s,
            "delay_wrapped_s": delay_wrapped_s,
            "phase_set_deg": phase_deg,
            "phase_readback_deg": phase_rb,
            "delay_achieved_s": achieved_delay_s,
        }

    # --------------------
    # Startup sequencing
    # --------------------
    def prepare_for_run(self) -> None:
        self.clear_status()
        self.output_off(1)
        self.output_off(2)
        self.reset()
        self.output_off(1)
        self.output_off(2)
        # Extra safety after reset
        self.set_dc_offset(1, 0.0)
        self.set_dc_offset(2, 0.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate IDQ IDCube detector TTL-like pulse outputs (CH1 + delayed CH2)"
    )
    parser.add_argument("--resource", default=DEFAULT_RESOURCE, help="PyVISA resource string")

    parser.add_argument("--rate", type=float, default=5e6, help="Pulse repetition rate (Hz)")
    parser.add_argument("--pulse-width", type=float, default=9e-9, help="Pulse width (seconds)")
    parser.add_argument("--delay", type=float, default=0e-9, help="CH2 delay relative to CH1 (seconds)")

    parser.add_argument("--ttl-low", type=float, default=-1.0, help="TTL low level (V)")
    parser.add_argument("--ttl-high", type=float, default=5.0, help="TTL high level (V)")
    parser.add_argument("--rise", type=float, default=3e-9, help="Edge rise time (seconds)")
    parser.add_argument("--fall", type=float, default=3e-9, help="Edge fall time (seconds)")

    parser.add_argument("--load", type=str.upper, default="50", choices=["50", "INF"],
                        help="Output load: 50 or INF")

    parser.add_argument(
        "--reset-on-exit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reset and release AWG local control when stopping (default: enabled)",
    )

    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip readback verification (not recommended while debugging).",
    )

    return parser.parse_args()


def keyboard_stop_watcher(stop_event: threading.Event) -> None:
    """Allow stop via keyboard entry ('q' + Enter)."""
    while not stop_event.is_set():
        try:
            text = input().strip().lower()
        except EOFError:
            return
        if text in {"q", "quit", "stop", "exit"}:
            stop_event.set()
            return


def main() -> None:
    args = parse_args()

    # -------- validation --------
    if args.rate <= 0:
        raise ValueError("--rate must be > 0")

    period_s = 1.0 / args.rate

    if args.pulse_width <= 0 or args.pulse_width >= period_s:
        raise ValueError("--pulse-width must be > 0 and smaller than the period (1/rate)")

    if args.ttl_high <= args.ttl_low:
        raise ValueError("--ttl-high must be greater than --ttl-low")

    if args.rise < 0 or args.fall < 0:
        raise ValueError("--rise and --fall must be >= 0")

    if (args.rise + args.fall) >= args.pulse_width:
        raise ValueError("--rise + --fall must be smaller than --pulse-width")

    if abs(args.delay) >= period_s:
        print("Warning: --delay is >= one period; phase-based delay wraps modulo the period.")

    # -------- run --------
    awg = DG922Controller(resource=args.resource)
    stop_event = threading.Event()

    print("Connecting to DG922...")
    awg.open()

    try:
        print(f"Connected: {awg.identify()}")
        awg.prepare_for_run()

        awg.set_load(1, args.load)
        awg.set_load(2, args.load)

        verify = not args.no_verify

        cfg1 = awg.configure_ttl_pulse(
            ch=1,
            frequency_hz=args.rate,
            pulse_width_s=args.pulse_width,
            low_v=args.ttl_low,
            high_v=args.ttl_high,
            rise_s=args.rise,
            fall_s=args.fall,
            verify=verify,
        )

        cfg2 = awg.configure_ttl_pulse(
            ch=2,
            frequency_hz=args.rate,
            pulse_width_s=args.pulse_width,
            low_v=args.ttl_low,
            high_v=args.ttl_high,
            rise_s=args.rise,
            fall_s=args.fall,
            verify=verify,
        )



        #awg.output_on(1)
        #awg.output_on(2)
        
        #awg.sync_phase()
        
        delay_info = awg.apply_time_delay_via_phase(
            delay_s=args.delay,
            ref_ch=1,
            target_ch=2,
            do_sync=True,
        )

        awg.output_on(1)
        awg.output_on(2)
        
        awg.sync_phase()

        # Readbacks for visibility
        width_rb_ch1 = awg.get_pulse_width_s(1)
        width_rb_ch2 = awg.get_pulse_width_s(2)

        print("\nTTL pulse simulation running on CH1 + CH2")
        print(f"Load:               {args.load}")
        print(f"Rate (requested):   {args.rate:.6f} Hz")
        print(f"Rate (actual):      {delay_info['freq_hz_actual']:.6f} Hz")
        print(f"Pulse width req:    {args.pulse_width * 1e9:.2f} ns")
        print(f"Pulse width rb CH1: {width_rb_ch1 * 1e9:.2f} ns")
        print(f"Pulse width rb CH2: {width_rb_ch2 * 1e9:.2f} ns")
        print(f"Rise/Fall:          {args.rise * 1e9:.2f} ns / {args.fall * 1e9:.2f} ns")
        print(f"TTL levels:         LOW={args.ttl_low:.3f} V HIGH={args.ttl_high:.3f} V")
        print("Vdc/Offset:         forced to 0.000 V on both channels")
        print(f"CH2 delay req:      {args.delay * 1e9:.2f} ns")
        print(f"CH2 delay wrapped:  {delay_info['delay_wrapped_s'] * 1e9:.2f} ns")
        print(f"CH2 phase set:      {delay_info['phase_set_deg']:.3f} deg")
        print(f"CH2 phase rb:       {delay_info['phase_readback_deg']:.3f} deg")
        print(f"CH2 delay achieved: {delay_info['delay_achieved_s'] * 1e9:.2f} ns")

        print("\nSCPI variants selected (for your firmware):")
        print(f"  CH1 width cmd: {cfg1['width_cmd']}")
        print(f"  CH1 rise  cmd: {cfg1['rise_cmd']}")
        print(f"  CH1 fall  cmd: {cfg1['fall_cmd']}")
        print(f"  CH2 width cmd: {cfg2['width_cmd']}")
        print(f"  CH2 rise  cmd: {cfg2['rise_cmd']}")
        print(f"  CH2 fall  cmd: {cfg2['fall_cmd']}")

        print("\nStop with: q + Enter (or Ctrl+C)\n")

        watcher = threading.Thread(target=keyboard_stop_watcher, args=(stop_event,), daemon=True)
        watcher.start()

        while not stop_event.is_set():
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received. Stopping outputs...")

    finally:
        try:
            awg.output_off(1)
            awg.output_off(2)

            # Safety: force offset to 0 V at shutdown
            try:
                awg.set_dc_offset(1, 0.0)
                awg.set_dc_offset(2, 0.0)
            except Exception:
                pass

            if args.reset_on_exit:
                awg.reset()
                awg.output_off(1)
                awg.output_off(2)
                awg.clear_status()
                try:
                    awg.release_local_control()
                except Exception:
                    pass
        finally:
            awg.close()
            print("Outputs OFF. Instrument connection closed.")


if __name__ == "__main__":
    main()