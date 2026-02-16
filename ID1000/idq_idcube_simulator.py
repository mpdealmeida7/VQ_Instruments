#!/usr/bin/env python3
"""Simulate IDQ IDCube-like TTL pulses on Rigol DG922 Pro (CH1 + delayed CH2).

This version uses native PULSE mode (not ARB), which is the most reliable way to
obtain TTL-like pulses on the oscilloscope.

Typical use:
    python idq_idcube_simulator.py

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

    def configure_ttl_pulse(
        self,
        ch: int,
        frequency_hz: float,
        pulse_width_s: float,
        low_v: float,
        high_v: float,
        rise_s: float,
        fall_s: float,
    ) -> None:
        """Configure a channel as a native TTL-like pulse output."""
        self._validate_ch(ch)
        if high_v <= low_v:
            raise ValueError("ttl_high must be greater than ttl_low")

        self.write(f":SOUR{ch}:FUNC PULS")
        self.write(f":SOUR{ch}:FREQ {frequency_hz}")
        self.write(f":SOUR{ch}:PULS:WIDT {pulse_width_s}")
        self.write(f":SOUR{ch}:VOLT:LOW {low_v}")
        self.write(f":SOUR{ch}:VOLT:HIGH {high_v}")
        self.write(f":SOUR{ch}:PULS:TRAN:LEAD {rise_s}")
        self.write(f":SOUR{ch}:PULS:TRAN:TRA {fall_s}")
        self.opc()

    def set_phase_deg(self, ch: int, phase_deg: float) -> None:
        self._validate_ch(ch)
        self.write(f":SOUR{ch}:PHAS {phase_deg}")
        self.opc()

    def sync_phase(self) -> None:
        # Make channel phase relationship deterministic after (re)configuration.
        self.write(":PHAS:SYNC")
        self.opc()

    def prepare_for_run(self) -> None:
        self.clear_status()
        self.output_off(1)
        self.output_off(2)
        self.reset()
        self.output_off(1)
        self.output_off(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate IDQ IDCube detector TTL-like pulse outputs (CH1 + delayed CH2)"
    )
    parser.add_argument("--resource", default=DEFAULT_RESOURCE, help="PyVISA resource string")

    parser.add_argument("--rate", type=float, default=100_000.0, help="Pulse repetition rate (Hz)")
    parser.add_argument("--pulse-width", type=float, default=20e-9, help="Pulse width (seconds)")
    parser.add_argument("--delay", type=float, default=50e-9, help="CH2 delay relative to CH1 (seconds)")

    parser.add_argument("--ttl-low", type=float, default=0.0, help="TTL low level (V)")
    parser.add_argument("--ttl-high", type=float, default=3.3, help="TTL high level (V)")
    parser.add_argument("--rise", type=float, default=4e-9, help="Edge rise time (seconds)")
    parser.add_argument("--fall", type=float, default=4e-9, help="Edge fall time (seconds)")

    parser.add_argument("--load", default="50", choices=["50", "INF", "inf"], help="Output load: 50 or INF")
    parser.add_argument(
        "--reset-on-exit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reset and release AWG local control when stopping (default: enabled)",
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

    if args.rate <= 0:
        raise ValueError("--rate must be > 0")
    period_s = 1.0 / args.rate
    if args.pulse_width <= 0 or args.pulse_width >= period_s:
        raise ValueError("--pulse-width must be > 0 and smaller than period")
    if args.ttl_high <= args.ttl_low:
        raise ValueError("--ttl-high must be greater than --ttl-low")

    # Convert requested delay to CH2 phase shift for periodic pulse trains.
    ch2_phase_deg = (args.delay * args.rate * 360.0) % 360.0

    awg = DG922Controller(resource=args.resource)
    stop_event = threading.Event()

    print("Connecting to DG922...")
    awg.open()

    try:
        print(f"Connected: {awg.identify()}")

        awg.prepare_for_run()
        awg.set_load(1, str(args.load).upper())
        awg.set_load(2, str(args.load).upper())

        awg.configure_ttl_pulse(
            ch=1,
            frequency_hz=args.rate,
            pulse_width_s=args.pulse_width,
            low_v=args.ttl_low,
            high_v=args.ttl_high,
            rise_s=args.rise,
            fall_s=args.fall,
        )
        awg.configure_ttl_pulse(
            ch=2,
            frequency_hz=args.rate,
            pulse_width_s=args.pulse_width,
            low_v=args.ttl_low,
            high_v=args.ttl_high,
            rise_s=args.rise,
            fall_s=args.fall,
        )

        awg.sync_phase()
        awg.set_phase_deg(2, ch2_phase_deg)

        awg.output_on(1)
        awg.output_on(2)

        print("\nTTL pulse simulation running on CH1 + CH2")
        print(f"Rate: {args.rate:.2f} Hz")
        print(f"Pulse width: {args.pulse_width * 1e9:.2f} ns")
        print(f"TTL levels: LOW={args.ttl_low:.3f} V HIGH={args.ttl_high:.3f} V")
        print(f"CH2 delay (requested): {args.delay * 1e9:.2f} ns")
        print(f"CH2 phase shift (applied): {ch2_phase_deg:.2f} deg")
        print("Stop with: q + Enter   (or Ctrl+C)\n")

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
