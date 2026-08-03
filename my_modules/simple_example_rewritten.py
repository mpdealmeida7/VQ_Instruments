#!/usr/bin/env python3
"""
Simple Example - Rigol MHO-984 Quick Start
===========================================
Reads a waveform from Channel 2, performs automatic measurements,
and saves the trace, plot, and oscilloscope screenshot.
"""

from datetime import datetime
import math
import os
import time

from rigol_mho984_data_acquisition import (
    RigolMHO984,
    plot_waveform,
    save_data_to_csv,
)


# ---------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------
CHANNEL = 1

OUTPUT_DIR = (
    r"C:\Users\Experiment\Documents\Python"
    r"\VQ_Instruments\my_modules\oscilloscope_data"
)

VERTICAL_SCALE_V_PER_DIV = 1.0
TIMEBASE_S_PER_DIV = 1e-9
TRIGGER_LEVEL_V = -131e-3
ACQUISITION_SETTLING_TIME_S = 2.0


def format_measurement(value, scale=1.0, decimals=3, unit="MHz"):
    """Safely format an oscilloscope measurement."""
    if value is None:
        return "Unavailable"

    try:
        numeric_value = float(value)

        if not math.isfinite(numeric_value) or abs(numeric_value) >= 1e30:
            return "Unavailable"

        scaled_value = numeric_value * scale
        return f"{scaled_value:.{decimals}f} {unit}".rstrip()

    except (TypeError, ValueError, OverflowError):
        return "Unavailable"


def print_measurements(measurements):
    """Print selected measurements without failing on missing values."""
    print("Measurements:")
    print(
        "   Peak-to-Peak:",
        format_measurement(measurements.get("vpp"), decimals=3, unit="V"),
    )
    print(
        "   RMS Voltage: ",
        format_measurement(measurements.get("vrms"), decimals=3, unit="V"),
    )
    print(
        "   Frequency:   ",
        format_measurement(
            measurements.get("freq"),
            scale=1e-3,
            decimals=2,
            unit="kHz",
        ),
    )
    print(
        "   Period:      ",
        format_measurement(
            measurements.get("period"),
            scale=1e6,
            decimals=3,
            unit="µs",
        ),
    )
    print(
        "   Duty Cycle:  ",
        format_measurement(measurements.get("duty"), decimals=1, unit="%"),
    )


def main():
    print("=" * 60)
    print("Rigol MHO-984 - Simple Example")
    print(f"Waveform source: Channel {CHANNEL}")
    print("=" * 60)
    print()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    scope = None

    try:
        print("Step 1: Connecting to oscilloscope...")
        scope = RigolMHO984()
        print("Connected successfully.\n")

        print(f"Step 2: Configuring Channel {CHANNEL}...")
        scope.enable_channel(CHANNEL, True)
        scope.set_channel_scale(CHANNEL, VERTICAL_SCALE_V_PER_DIV)
        scope.set_timebase(TIMEBASE_S_PER_DIV)
        scope.set_trigger_mode("EDGE")
        scope.set_trigger_source(f"CHAN{CHANNEL}")
        scope.set_trigger_level(TRIGGER_LEVEL_V)
        scope.set_trigger_slope("POS")
        print("Configuration complete.\n")

        print("Step 3: Acquiring waveform data...")
        scope.run()
        time.sleep(ACQUISITION_SETTLING_TIME_S)
        scope.stop()
        print("Acquisition complete.\n")

        print(f"Step 4: Reading Channel {CHANNEL} waveform...")
        time_data, voltage_data, preamble = scope.acquire_waveform(
            CHANNEL,
            mode="NORM",
        )
        print(f"Captured {len(voltage_data)} data points.\n")

        print("Step 5: Performing measurements...")
        measurements = scope.get_measurements(CHANNEL)
        print_measurements(measurements)
        print()

        print("Step 6: Saving data...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_file = os.path.join(
            OUTPUT_DIR,
            f"waveform_ch{CHANNEL}_{timestamp}.csv",
        )
        save_data_to_csv(
            time_data,
            voltage_data,
            csv_file,
            CHANNEL,
            measurements,
        )
        print(f"CSV saved: {csv_file}")

        plot_file = os.path.join(
            OUTPUT_DIR,
            f"waveform_ch{CHANNEL}_{timestamp}.png",
        )
        plot_waveform(
            time_data,
            voltage_data,
            CHANNEL,
            measurements,
            plot_file,
        )
        print(f"Plot saved: {plot_file}")

        screenshot_file = os.path.join(
            OUTPUT_DIR,
            f"screenshot_ch{CHANNEL}_{timestamp}.png",
        )
        scope.save_screenshot(screenshot_file)
        print(f"Screenshot saved: {screenshot_file}")
        print()

        print("=" * 60)
        print("SUCCESS")
        print(f"All files saved to: {OUTPUT_DIR}")
        print("=" * 60)

    except Exception as error:
        print(f"\nError: {error}")
        print("\nTroubleshooting:")
        print("1. Confirm that the oscilloscope is powered on.")
        print("2. Confirm that Channel 2 is connected and displaying a signal.")
        print("3. Check the USB or Ethernet connection.")
        print("4. Confirm that PyVISA is installed.")
        print("5. Confirm that rigol_mho984_data_acquisition.py is in the same folder.")

        import traceback
        traceback.print_exc()

    finally:
        if scope is not None:
            try:
                print("\nClosing oscilloscope connection...")
                scope.close()
                print("Connection closed.")
            except Exception as close_error:
                print(f"Warning: connection could not be closed cleanly: {close_error}")


if __name__ == "__main__":
    main()
