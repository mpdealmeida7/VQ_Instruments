#!/usr/bin/env python3
"""
sample_test-rewriten.py

Rigol MHO-984 acquisition example for MHz-rate signals.

This script:
- acquires Channel 2;
- sets a timebase suitable for MHz signals;
- triggers from Channel 2;
- reports frequency in MHz and timing in ns;
- avoids formatting errors when a measurement is unavailable;
- prints the effective sampling rate and samples per period;
- saves the waveform as CSV, a PNG plot, and an oscilloscope screenshot.

The companion file rigol_mho984_data_acquisition.py must be in the same folder.
"""

from datetime import datetime
from pathlib import Path
import time
import traceback

import matplotlib.pyplot as plt

from rigol_mho984_data_acquisition_fixed import (
    RigolMHO984,
    save_data_to_csv,
)


# =====================================================================
# USER SETTINGS
# =====================================================================

CHANNEL = 2

# Approximate frequency of the signal being measured.
# Change this value to match your experiment.
EXPECTED_FREQUENCY_HZ = 1e6

# Number of periods to show across the oscilloscope's 10 horizontal divisions.
DISPLAYED_PERIODS = 5

# Vertical settings.
CHANNEL_SCALE_V_PER_DIV = 0.5

# Set this near the midpoint between the low and high voltage levels.
# Example: for a 0–1 V pulse, use approximately 0.5 V.
TRIGGER_LEVEL_V = 0.0
TRIGGER_SLOPE = "NEG"

# Allow the trace to stabilise before stopping and reading it.
ACQUISITION_SETTLING_TIME_S = 2.0

OUTPUT_DIR = Path(
    r"C:\Users\Experiment\Documents\Python\VQ_Instruments"
    r"\my_modules\oscilloscope_data"
)


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

def calculate_timebase(
    expected_frequency_hz: float,
    displayed_periods: float = 5,
    horizontal_divisions: int = 10,
) -> float:
    """
    Calculate the oscilloscope horizontal scale in seconds per division.

    Example:
        50 MHz -> period = 20 ns.
        Five periods occupy 100 ns.
        Across 10 divisions, the required scale is 10 ns/div.
    """
    if expected_frequency_hz <= 0:
        raise ValueError("EXPECTED_FREQUENCY_HZ must be greater than zero.")

    if displayed_periods <= 0:
        raise ValueError("DISPLAYED_PERIODS must be greater than zero.")

    period_s = 1.0 / expected_frequency_hz
    return displayed_periods * period_s / horizontal_divisions


def valid_measurement(value) -> bool:
    """
    Return True only for a usable oscilloscope measurement.

    Rigol instruments can return None or a very large sentinel value when a
    measurement cannot be calculated.
    """
    if value is None:
        return False

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return False

    return abs(numeric_value) < 1e30


def format_measurement(value, scale=1.0, unit="", decimals=3) -> str:
    """Safely format a measurement without raising a NoneType error."""
    if not valid_measurement(value):
        return "unavailable"

    return f"{float(value) * scale:.{decimals}f} {unit}".strip()


def print_measurements(measurements: dict) -> None:
    """Print the main measurements using units suitable for MHz signals."""
    print("Measurements:")
    print(
        "   Peak-to-Peak: "
        + format_measurement(measurements.get("vpp"), unit="V")
    )
    print(
        "   RMS Voltage:  "
        + format_measurement(measurements.get("vrms"), unit="V")
    )
    print(
        "   Frequency:    "
        + format_measurement(
            measurements.get("freq"),
            scale=1e-6,
            unit="MHz",
            decimals=6,
        )
    )
    print(
        "   Period:       "
        + format_measurement(
            measurements.get("period"),
            scale=1e9,
            unit="ns",
            decimals=3,
        )
    )
    print(
        "   Duty Cycle:   "
        + format_measurement(
            measurements.get("duty"),
            unit="%",
            decimals=2,
        )
    )
    print(
        "   Rise Time:    "
        + format_measurement(
            measurements.get("rise_time"),
            scale=1e9,
            unit="ns",
            decimals=3,
        )
    )
    print(
        "   Fall Time:    "
        + format_measurement(
            measurements.get("fall_time"),
            scale=1e9,
            unit="ns",
            decimals=3,
        )
    )


def plot_waveform_ns(
    time_data,
    voltage_data,
    channel: int,
    measurements: dict,
    filename: Path,
) -> None:
    """Plot a fast waveform with the horizontal axis shown in nanoseconds."""
    time_ns = time_data * 1e9

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(time_ns, voltage_data, linewidth=0.8)
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("Voltage (V)")
    ax.set_title(f"Rigol MHO-984 — Channel {channel} waveform")
    ax.grid(True, alpha=0.3)

    lines = ["Measurements"]

    if valid_measurement(measurements.get("vpp")):
        lines.append(f"Vpp: {measurements['vpp']:.3f} V")

    if valid_measurement(measurements.get("vrms")):
        lines.append(f"Vrms: {measurements['vrms']:.3f} V")

    if valid_measurement(measurements.get("freq")):
        lines.append(f"Frequency: {measurements['freq'] / 1e6:.6f} MHz")

    if valid_measurement(measurements.get("period")):
        lines.append(f"Period: {measurements['period'] * 1e9:.3f} ns")

    if valid_measurement(measurements.get("duty")):
        lines.append(f"Duty cycle: {measurements['duty']:.2f} %")

    ax.text(
        0.02,
        0.98,
        "\n".join(lines),
        transform=ax.transAxes,
        verticalalignment="top",
        fontsize=9,
        family="monospace",
        bbox={
            "boxstyle": "round",
            "facecolor": "white",
            "alpha": 0.8,
        },
    )

    fig.tight_layout()
    fig.savefig(filename, dpi=300, bbox_inches="tight")
    plt.close(fig)


# =====================================================================
# MAIN ROUTINE
# =====================================================================

def main() -> None:
    print("=" * 70)
    print("Rigol MHO-984 — MHz Signal Acquisition")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timebase_s_per_div = calculate_timebase(
        EXPECTED_FREQUENCY_HZ,
        DISPLAYED_PERIODS,
    )

    expected_period_s = 1.0 / EXPECTED_FREQUENCY_HZ

    print(f"Channel:             CH{CHANNEL}")
    print(f"Expected frequency:  {EXPECTED_FREQUENCY_HZ / 1e6:.6f} MHz")
    print(f"Expected period:     {expected_period_s * 1e9:.3f} ns")
    print(f"Horizontal scale:    {timebase_s_per_div * 1e9:.3f} ns/div")
    print()

    scope = None

    try:
        # Auto-detect the connected Rigol oscilloscope.
        scope = RigolMHO984()

        print("\nConfiguring oscilloscope...")

        scope.enable_channel(CHANNEL, True)
        scope.set_input_impedance(CHANNEL, "50")
        scope.set_channel_scale(CHANNEL, CHANNEL_SCALE_V_PER_DIV)
        scope.set_timebase(timebase_s_per_div)

        scope.set_trigger_mode("EDGE")
        scope.set_trigger_source(f"CHAN{CHANNEL}")
        scope.set_trigger_level(TRIGGER_LEVEL_V)
        scope.set_trigger_slope(TRIGGER_SLOPE)

        print("\nAcquiring waveform...")

        scope.run()
        time.sleep(2.0)
        measurements = scope.get_measurements(CHANNEL)
        
        # ###################################################
        #  Diagnostic queries (ADD THIS BLOCK)                                
        # ###################################################
        raw_frequency = scope.scope.query(
            f":MEASure:ITEM? FREQuency,CHANnel{CHANNEL}"
        ).strip()
        
        raw_period = scope.scope.query(
            f":MEASure:ITEM? PERiod,CHANnel{CHANNEL}"
        ).strip()

        raw_vpp = scope.scope.query(
        f":MEASure:ITEM? VPP,CHANnel{CHANNEL}"
        ).strip()
        
        scope_error = scope.scope.query(
        ":SYSTem:ERRor?"
        ).strip()
        
        impedance = scope.scope.query(
        f":CHANnel{CHANNEL}:IMPedance?"
        ).strip()
        
        print("\n===== SCPI Diagnostics =====")
        print(f"Raw Frequency : {raw_frequency}")
        print(f"Raw Period    : {raw_period}")
        print(f"Raw Vpp       : {raw_vpp}")
        print(f"Scope Error   : {scope_error}")
        print(f"Input impedance: {impedance}")
        print("============================\n")

        #####################################################
        scope.stop()
        
        time.sleep(2.0)

        time_data, voltage_data, preamble = scope.acquire_waveform(
            CHANNEL,
            mode="NORM",
        )

        

        sample_interval_s = preamble.get("xincrement")
        sample_rate_hz = None
        samples_per_expected_period = None

        if sample_interval_s is not None and sample_interval_s > 0:
            sample_rate_hz = 1.0 / sample_interval_s
            samples_per_expected_period = (
                sample_rate_hz / EXPECTED_FREQUENCY_HZ
            )

        print("\nAcquisition information:")
        print(f"   Captured points:  {len(voltage_data)}")

        if sample_interval_s is not None and sample_interval_s > 0:
            print(
                f"   Sample interval:  {sample_interval_s * 1e12:.3f} ps"
            )
            print(
                f"   Effective rate:   {sample_rate_hz / 1e9:.6f} GSa/s"
            )
            print(
                "   Samples/period:  "
                f"{samples_per_expected_period:.1f}"
            )
        else:
            print("   Sample interval:  unavailable")
            print("   Effective rate:   unavailable")
            print("   Samples/period:   unavailable")

        print()
        print_measurements(measurements)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"waveform_ch{CHANNEL}_{timestamp}"

        csv_file = OUTPUT_DIR / f"{base_name}.csv"
        plot_file = OUTPUT_DIR / f"{base_name}.png"
        screenshot_file = OUTPUT_DIR / f"screenshot_ch{CHANNEL}_{timestamp}.png"

        print("\nSaving files...")

        save_data_to_csv(
            time_data,
            voltage_data,
            str(csv_file),
            CHANNEL,
            measurements,
        )
        print(f"   CSV:        {csv_file}")

        plot_waveform_ns(
            time_data,
            voltage_data,
            CHANNEL,
            measurements,
            plot_file,
        )
        print(f"   Plot:       {plot_file}")

        try:
            scope.save_screenshot(str(screenshot_file))
            print(f"   Screenshot: {screenshot_file}")
        except Exception as screenshot_error:
            print(
                "   Screenshot could not be saved: "
                f"{screenshot_error}"
            )

        print("\nAcquisition completed successfully.")

        if (
            samples_per_expected_period is not None
            and samples_per_expected_period < 10
        ):
            print(
                "\nWarning: fewer than 10 samples per expected period were "
                "captured. Reduce the displayed time span or increase the "
                "oscilloscope sample rate before relying on pulse-shape or "
                "duty-cycle measurements."
            )

    except Exception as error:
        print(f"\nAcquisition error: {error}")
        traceback.print_exc()

        print("\nChecks:")
        print("1. Confirm that rigol_mho984_data_acquisition.py is present.")
        print("2. Confirm that the signal is connected to Channel 2.")
        print("3. Adjust CHANNEL_SCALE_V_PER_DIV for the signal amplitude.")
        print("4. Set TRIGGER_LEVEL_V between the low and high levels.")
        print("5. Set EXPECTED_FREQUENCY_HZ near the actual frequency.")
        print("6. Verify the USB/VISA connection to the oscilloscope.")

    finally:
        if scope is not None:
            try:
                scope.close()
            except Exception as close_error:
                print(f"Warning: could not close the connection: {close_error}")


if __name__ == "__main__":
    main()
