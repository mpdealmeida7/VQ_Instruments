"""Save input and coincidence counters values in a file each second.

Extended: add a scan mode to sweep different coincidence window values and
record total counts/coincidences, with optional plotting of results.

Requirements (install if missing):
    pip install matplotlib pandas
"""
# Check that packages below are installed.
# Install the missing packages with the following command in an instance of cmd.exe, opened as admin user.
# python.exe -m pip install "name of missing package"

# Python modules needed
import itertools
import os
import sys
import time
import datetime
import logging
import argparse
from pathlib import Path as _Path

# Optional libs for scan+plot features
try:
    import pandas as pd
except Exception:  # lazy import fallback
    pd = None
try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None

sys.path.append(str(_Path(__file__).parent.parent))
from utils.acquisitions import coincidences
from utils.common import connect

logger = logging.getLogger(__name__)

#################################################################
################# TO BE FILLED BY USER ######################
#################################################################
# Time Controller default IP address
DEFAULT_TC_ADDRESS = "169.254.224.106"

# Default interval between counters acquisitions in seconds
DEFAULT_ACQUISITION_INTERVAL = 1

# Default acquisition total duration in seconds (0 or None = infinite)
DEFAULT_ACQUISITION_DURATION = 10

# File path where histogram is saved in CSV format
DEFAULT_COUNTERS_FILEPATH = r"C:\\Users\\Experiment\\Documents\\Python\\VQ_Instruments\\ID1000\\ID_1000_data\\hist\\counters.csv"

# Default coincidence window in ps
DEFAULT_COINCIDENCE_WINDOW = 5e3

# Default counter integration time in ns (0 or None = endless accumulation of counts)
DEFAULT_COUNTERS_INTEGRATION_TIME = 1000

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = r"C:\\Users\\Experiment\\Documents\\Python\\VQ_Instruments\\ID1000\\ID_1000_data\\log\\log.txt"

#################################################################
#################### UTILS FUNCTIONS ########################
#################################################################

def acquire_coincidence_counters(tc, filepath, interval, duration=None):
    """Continuously record counters to CSV at fixed interval.

    Parameters
    ----------
    tc : object
        Time Controller / instrument object.
    filepath : str or Path
        Output CSV filepath.
    interval : float
        Seconds between queries.
    duration : float or None
        Total duration to run (s). None/0 means run forever until CTRL+C.
    """
    with open(filepath, "w") as file:
        # Acquire counters for the given duration or forever if no duration is provided
        start_time = time.time()
        for i in itertools.count():
            if duration and (time.time() - start_time) >= duration:
                break

            # Gather counters
            counters_gathering_time = time.time()
            counters = coincidences.read_counts(tc)

            if i == 0:
                # write header on first iteration
                file.write(f"time;{';'.join(counters)}\n")

            counts_string = [str(counts) for counts in counters.values()]

            # Save counters
            time_since_start = counters_gathering_time - start_time
            file.write(f"{time_since_start:.2f};{';'.join(counts_string)}\n")
            file.flush()

            # Wait for the given interval (minus the time it took to gather and save counters)
            wait_time = interval - (time.time() - counters_gathering_time)
            if wait_time > 0:
                time.sleep(wait_time)


def _ensure_dirs(path_like):
    p = _Path(path_like)
    if p.suffix:
        p.parent.mkdir(parents=True, exist_ok=True)
    else:
        p.mkdir(parents=True, exist_ok=True)
    return p


def _parse_windows(args):
    """Return a list of window values in ps based on CLI args."""
    if args.windows:
        vals = []
        for tok in args.windows.split(','):
            tok = tok.strip()
            if not tok:
                continue
            vals.append(float(tok))
        if not vals:
            raise ValueError("--windows provided but no valid numeric values found")
        return vals
    # else use start/stop/step
    if args.w_start is None or args.w_stop is None or args.w_step is None:
        raise ValueError("Provide either --windows or the trio --w-start, --w-stop, --w-step")
    if args.w_step == 0:
        raise ValueError("--w-step must be non-zero")
    # include stop if step divides exactly; otherwise go up to but not past stop
    windows = []
    w = float(args.w_start)
    stop = float(args.w_stop)
    step = float(args.w_step)
    if (step > 0 and w > stop) or (step < 0 and w < stop):
        raise ValueError("--w-step sign does not lead from start to stop")
    # generate values
    if step > 0:
        while w <= stop + 1e-12:
            windows.append(w)
            w += step
    else:
        while w >= stop - 1e-12:
            windows.append(w)
            w += step
    return windows


def _accumulate_samples(tc, n_samples, integration_ns, settle_cycles=1):
    """Accumulate counts over n_samples integration cycles.

    Notes
    -----
    The device reports counts integrated over the specified integration window.
    We wait for `integration_ns` between reads and sum the returned values.
    """
    totals = None
    # optional settling cycles after (re)config
    if integration_ns:
        sleep_s = integration_ns / 1_000_000_000.0
        for _ in range(max(0, int(settle_cycles))):
            time.sleep(sleep_s)
            _ = coincidences.read_counts(tc)
    # sampling loop
    for _ in range(int(n_samples)):
        if integration_ns:
            time.sleep(integration_ns / 1_000_000_000.0)
        counts = coincidences.read_counts(tc)
        if totals is None:
            totals = {k: int(v) for k, v in counts.items()}
        else:
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + int(v)
    elapsed_s = (n_samples * (integration_ns / 1_000_000_000.0)) if integration_ns else 0.0
    return totals or {}, elapsed_s


def scan_coincidence_windows(
    tc,
    windows_ps,
    integration_ns,
    n_samples,
    settle_cycles,
    per_sample_filepath=None,
    summary_filepath=None,
    show_plot=False,
    save_plot_dir=None,
):
    """Sweep coincidence windows and record totals + (optional) plots.

    Parameters
    ----------
    tc : object
        Connected instrument handle.
    windows_ps : list[float]
        List of coincidence window values (ps) to scan.
    integration_ns : int
        Counter integration time in ns.
    n_samples : int
        Number of integration samples to accumulate per window.
    settle_cycles : int
        Integration cycles to wait (and discard) after each reconfiguration.
    per_sample_filepath : str or Path or None
        If provided, write a long-form CSV with one row per window (totals) plus metadata.
    summary_filepath : str or Path or None
        If provided, write a summary CSV with totals & rates per window.
    show_plot : bool
        If True, show matplotlib windows at the end.
    save_plot_dir : str or Path or None
        If provided, save PNGs of plots here.
    """
    # Prepare outputs
    if per_sample_filepath:
        per_sample_path = _ensure_dirs(per_sample_filepath)
    else:
        per_sample_path = None

    if summary_filepath:
        summary_path = _ensure_dirs(summary_filepath)
    else:
        summary_path = None

    if save_plot_dir:
        plots_dir = _ensure_dirs(save_plot_dir)
    else:
        plots_dir = None

    records = []  # for per-window totals

    # Iterate windows
    for w_ps in windows_ps:
        logger.info(f"Configuring window={w_ps} ps, integration={integration_ns} ns")
        coincidences.configure(tc, w_ps, integration_ns)
        totals, elapsed_s = _accumulate_samples(
            tc, n_samples=n_samples, integration_ns=integration_ns, settle_cycles=settle_cycles
        )
        if not totals:
            logger.warning(f"No counters returned for window={w_ps} ps")
            continue
        # Flatten into record
        rec = {"window_ps": w_ps, "elapsed_s": elapsed_s}
        # cast to int to avoid strings
        for k, v in totals.items():
            try:
                rec[k] = int(v)
            except Exception:
                rec[k] = v
        records.append(rec)

    if not records:
        logger.error("No data collected during window scan.")
        return None

    # Build DataFrame (if pandas available); else write minimal CSVs
    if pd is not None:
        df = pd.DataFrame.from_records(records)
        # Compute rates if elapsed_s > 0
        if (df.get("elapsed_s") is not None) and df["elapsed_s"].gt(0).any():
            counter_cols = [c for c in df.columns if c not in ("window_ps", "elapsed_s")]
            for c in counter_cols:
                df[c + "_rate_hz"] = df[c] / df["elapsed_s"].replace(0, pd.NA)
        # Save summary
        if summary_path:
            df.sort_values("window_ps").to_csv(summary_path, index=False)
            logger.info(f"Saved scan summary: {summary_path}")
        # Plots
        if plt is not None:
            # One plot per counter (counts vs window)
            counter_cols = [c for c in df.columns if c not in ("window_ps", "elapsed_s") and not c.endswith("_rate_hz")]
            rate_cols = [c for c in df.columns if c.endswith("_rate_hz")]

            for cols, suffix, ylabel in (
                (counter_cols, "counts", "Counts (integrated)"),
                (rate_cols, "rate", "Rate (Hz)"),
            ):
                if not cols:
                    continue
                n = len(cols)
                fig, ax = plt.subplots(figsize=(8, 5))
                for c in cols:
                    ax.plot(df["window_ps"], df[c], marker="o", label=c)
                ax.set_xlabel("Coincidence window (ps)")
                ax.set_ylabel(ylabel)
                ax.set_title(f"Window scan — {suffix}")
                ax.grid(True, alpha=0.3)
                ax.legend(loc="best")
                fig.tight_layout()
                if plots_dir:
                    out = plots_dir / f"window_scan_{suffix}.png"
                    fig.savefig(out, dpi=150)
                    logger.info(f"Saved plot: {out}")
                if show_plot:
                    plt.show()
                else:
                    plt.close(fig)
    else:
        # Minimal CSV write without pandas
        header = sorted({k for r in records for k in r.keys()})
        if summary_path:
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(";".join(header) + "\n")
                for r in records:
                    row = [str(r.get(h, "")) for h in header]
                    f.write(";".join(row) + "\n")
            logger.info(f"Saved scan summary: {summary_path}")
        if show_plot:
            logger.warning("show_plot requested but pandas/matplotlib are unavailable.")

    return records

#################################################################
####################### MAIN FUNCTION #######################
#################################################################

def main():
    parser = argparse.ArgumentParser(description=__doc__)

    # Original continuous acquisition args
    parser.add_argument(
        "--interval",
        type=float,
        help="interval between counters acquisitions",
        metavar=("SECONDS"),
        default=DEFAULT_ACQUISITION_INTERVAL,
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="acquisition total duration",
        metavar=("SECONDS"),
        default=DEFAULT_ACQUISITION_DURATION,
    )
    parser.add_argument(
        "--address",
        type=str,
        help="Time Controller address",
        metavar=("IP"),
        default=DEFAULT_TC_ADDRESS,
    )
    parser.add_argument(
        "--file",
        type=str,
        help="save counters in a csv file",
        metavar="FILEPATH",
        dest="counters_filepath",
        default=DEFAULT_COUNTERS_FILEPATH,
    )
    parser.add_argument(
        "--window",
        type=float,
        help="coincidence window in ps",
        metavar="PS",
        dest="coincidence_window",
        default=DEFAULT_COINCIDENCE_WINDOW,
    )
    parser.add_argument(
        "--integration",
        type=int,
        help="counter integration time in ns",
        metavar="NS",
        default=DEFAULT_COUNTERS_INTEGRATION_TIME,
    )
    parser.add_argument(
        "--log-path",
        type=_Path,
        help="store output in log file",
        metavar=("FULLPATH"),
        default=DEFAULT_LOG_PATH,
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    # New: Scan mode arguments
    scan = parser.add_argument_group("scan", "Sweep multiple coincidence-window values and plot")
    scan.add_argument(
        "--scan",
        action="store_true",
        help="Enable window scan mode (sweep windows and aggregate totals)",
    )
    scan.add_argument(
        "--windows",
        type=str,
        default=None,
        help="Comma-separated list of window values in ps, e.g. '500,1000,2000'",
    )
    scan.add_argument("--w-start", dest="w_start", type=float, default=None, help="Window scan start (ps)")
    scan.add_argument("--w-stop", dest="w_stop", type=float, default=None, help="Window scan stop (ps)")
    scan.add_argument("--w-step", dest="w_step", type=float, default=None, help="Window scan step (ps)")

    scan.add_argument(
        "--samples-per-window",
        dest="samples_per_window",
        type=int,
        default=1,
        help="Number of integration samples to accumulate per window",
    )
    scan.add_argument(
        "--settle-cycles",
        dest="settle_cycles",
        type=int,
        default=1,
        help="Integration cycles to discard after each reconfiguration",
    )

    # Outputs for scan
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    scan.add_argument(
        "--scan-summary-file",
        dest="scan_summary_file",
        type=str,
        default=str(_Path(DEFAULT_COUNTERS_FILEPATH).with_name(f"window_scan_summary_{ts}.csv")),
        help="Path for scan summary CSV (one row per window)",
    )
    scan.add_argument(
        "--save-plot-dir",
        dest="save_plot_dir",
        type=str,
        default=str(_Path(DEFAULT_COUNTERS_FILEPATH).with_name(f"window_scan_plots_{ts}")),
        help="Directory to save PNG plots (created if missing)",
    )
    scan.add_argument(
        "--show-plot",
        dest="show_plot",
        action="store_true",
        help="Show plots interactively at the end",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        filename=args.log_path,
    )

    try:
        tc = connect(args.address)

        if args.scan:
            # Window scan mode
            windows_ps = _parse_windows(args)
            logger.info(
                f"Starting window scan over {len(windows_ps)} value(s); integration={args.integration} ns; "
                f"samples/window={args.samples_per_window}"
            )
            # Perform scan (this function configures the device internally for each window)
            scan_coincidence_windows(
                tc=tc,
                windows_ps=windows_ps,
                integration_ns=args.integration,
                n_samples=args.samples_per_window,
                settle_cycles=args.settle_cycles,
                per_sample_filepath=None,
                summary_filepath=args.scan_summary_file,
                show_plot=args.show_plot,
                save_plot_dir=args.save_plot_dir,
            )
        else:
            # Original continuous logging mode
            coincidences.configure(tc, args.coincidence_window, args.integration)

            # let counter gather some count after the TC has been configured
            if args.integration:
                integration_in_seconds = args.integration / 1000  # ns -> us? (legacy)
                # Correct conversion: ns to s
                integration_in_seconds = args.integration / 1_000_000_000.0
                time.sleep(integration_in_seconds)
                if integration_in_seconds > args.interval:
                    logger.warning(
                        "counter integration time > counters acquisition interval. Script may record duplicated counter values."
                    )

            message = (
                f"recording counters into {os.path.realpath(args.counters_filepath)} every {args.interval} seconds"
            )
            if args.duration:
                logger.info(f"{message} for {args.duration} seconds...\n")
            else:
                logger.info(f"{message} (press CTRL + C to stop)...\n")

            acquire_coincidence_counters(
                tc, args.counters_filepath, args.interval, args.duration
            )

    except KeyboardInterrupt:
        logger.info("Stop recording counters.")
    except ConnectionError as e:
        logger.exception(e)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
