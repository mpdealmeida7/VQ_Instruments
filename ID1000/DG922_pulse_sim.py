# -*- coding: utf-8 -*-
"""
DG922 (Rigol DG900 Pro) – Single-photon detector pulse simulator
Author: Marcelo-ready helper
Tested with: pyVISA 1.13+, Rigol DG900 Pro series SCPI (LAN/USB)
What it does:
  * Builds Poisson pulse trains for CH1
  * Builds correlated CH2 with a set coincidence fraction + delay + background
  * Uploads ARB to DG922 (binary DAC or ASCII fallback) and loops
  * Sets amplitude/offset to produce ~0..2 V TTL-like pulses for ID1000
"""

import time
import math
import numpy as np
import pyvisa

# ===================== USER PARAMETERS ===================== #
# --- VISA resource (pick one) ---
# Example LAN: 'TCPIP::192.168.1.120::INSTR'
# Example USB: e.g. 'USB0::0x1AB1::0x0647::DG9A123456789::INSTR'
VISA_RESOURCE = 'TCPIP::192.168.1.120::INSTR'  # <- set me

# --- Waveform / physics knobs ---
duration_s            = 0.010       # 10 ms fits in memory comfortably (1.25 MS at 125 MSa/s)
fs                     = 125e6       # 125 MSa/s (leaves headroom vs. 16 Mpts)
pulse_width_ns         = 20.0        # SPD-like electrical pulse width (~10–30 ns typical)
jitter_rms_ns          = 0.5         # RMS timing jitter to smear edges (optional)
dead_time_ns           = 50.0        # Detector-like dead time emulation (0 disables)
mean_rate_ch1_cps      = 5e5         # CH1 mean counts/s
mean_rate_bkg_ch2_cps  = 2e5         # CH2 independent background counts/s
coinc_fraction         = 0.30        # Fraction of CH1 events replicated on CH2 (0..1)
coinc_delay_ns         = 12.0        # Delay of true coincidences (ns), sign allowed
coinc_jitter_rms_ns    = 0.5         # Extra jitter applied to coincident copies

# --- Electrical / output ---
ampl_vpp               = 2.0         # 2 Vpp -> about 0..2 V with +1 V offset
dc_offset_v            = +1.0
load_ohms              = 50          # 50 Ω system
low_level_v            = 0.0         # Baseline (for 0)
high_level_v           = 2.0         # Pulse top (for 1)

# --- Playback ---
continuous_loop        = True
sequence_name          = 'VOLATILE'  # volatile ARB store (typical)
channel_enable         = (1, 2)      # which channels to turn on

# =========================================================== #

def poisson_events(duration, rate, dead_time=0.0):
    """Return event start times (seconds) following Poisson process with optional nonparalyzable dead time."""
    if rate <= 0:
        return np.array([], dtype=float)
    rng = np.random.default_rng()
    times = []
    t = 0.0
    while True:
        t += rng.exponential(1.0 / rate)
        if t > duration:
            break
        # enforce dead time
        if not times or (t - times[-1]) >= dead_time:
            times.append(t)
    return np.array(times, dtype=float)

def times_to_waveform(times_s, duration_s, fs, width_s, jitter_rms_s=0.0, low=0.0, high=1.0):
    """Rasterize event start times into a 0/1 waveform with given pulse width and optional Gaussian jitter."""
    n = int(round(duration_s * fs))
    wf = np.full(n, low, dtype=np.float32)
    if len(times_s) == 0:
        return wf
    rng = np.random.default_rng()
    # Quantize with jitter
    for t in times_s:
        tj = t + (rng.normal(0.0, jitter_rms_s) if jitter_rms_s > 0 else 0.0)
        k0 = int(round(tj * fs))
        k1 = k0 + int(round(width_s * fs))
        if k1 <= 0 or k0 >= n:
            continue
        k0 = max(0, k0)
        k1 = min(n, k1)
        wf[k0:k1] = high
    return wf

def build_channels():
    # Convert ns to s
    w_s   = pulse_width_ns     * 1e-9
    dt_s  = dead_time_ns       * 1e-9
    cd_s  = coinc_delay_ns     * 1e-9
    jit1  = jitter_rms_ns      * 1e-9
    jitc  = coinc_jitter_rms_ns* 1e-9

    # CH1: Poisson with dead time
    t1 = poisson_events(duration_s, mean_rate_ch1_cps, dead_time=dt_s)

    # CH2: a fraction of CH1, delayed + jitter, plus independent background
    rng = np.random.default_rng()
    mask = rng.random(len(t1)) < max(0.0, min(1.0, coinc_fraction))
    t2_coinc = t1[mask] + cd_s + (rng.normal(0.0, jitc, size=mask.sum()) if mask.sum()>0 else 0.0)
    # Reject out-of-window coincident samples (negative/after duration)
    t2_coinc = t2_coinc[(t2_coinc >= 0.0) & (t2_coinc <= duration_s)]
    # Independent background
    t2_bkg = poisson_events(duration_s, mean_rate_bkg_ch2_cps, dead_time=dt_s)
    # Merge and sort unique times with dead-time enforcement
    t2_all = np.sort(np.concatenate([t2_coinc, t2_bkg]))
    if dt_s > 0 and len(t2_all) > 1:
        pruned = [t2_all[0]]
        for t in t2_all[1:]:
            if t - pruned[-1] >= dt_s:
                pruned.append(t)
        t2_all = np.array(pruned)

    # Rasterize
    y1 = times_to_waveform(t1, duration_s, fs, w_s, jitter_rms_s=jit1, low=low_level_v, high=high_level_v)
    y2 = times_to_waveform(t2_all, duration_s, fs, w_s, jitter_rms_s=jit1, low=low_level_v, high=high_level_v)
    return y1, y2

def normalize_to_dac_i16(y, vpp=2.0, offset=0.0):
    """
    Convert a voltage waveform to signed 16-bit DAC codes spanning [-1.0, +1.0] nominal.
    We first normalise by expected low/high, then map to int16.
    """
    # Expect the user mapped low/high already; just rescale around offset/amplitude
    # Build a normalized -1..+1
    y_norm = (y - offset) / (vpp/2.0)
    y_norm = np.clip(y_norm, -1.0, 1.0)
    # Map to int16 full scale
    return np.array((y_norm * 32767.0).round(), dtype=np.int16)

def build_block_data(binbytes):
    """RIGOL binary block: #9<length><data>"""
    n = len(binbytes)
    header = f"#{len(str(n))}{n}".encode('ascii')
    return header + binbytes

def upload_arb_dg900_pro(inst, ch, y, fs, name='VOLATILE'):
    """
    Try preferred binary DAC upload for DG900 Pro, then fallback to ASCII.
    Returns True if upload succeeded.
    """
    # 1) Preferred: :MMEMory:TRACe:ARB:DATA:DAC {name},#9<bin16>
    try:
        inst.write(f":SOURce{ch}:FUNCtion ARBitrary")
        inst.write(f":SOURce{ch}:ARBitrary:SRATe {fs}")
        # Make sure output is OFF during load
        inst.write(f":OUTPut{ch} OFF")
        dac = normalize_to_dac_i16(y, ampl_vpp, dc_offset_v)
        payload = build_block_data(dac.tobytes(order='C'))
        # Some firmwares require clearing volatile first:
        # inst.write(f":MMEMory:DELete {name}")
        inst.write_raw(f":MMEMory:TRACe:ARB:DATA:DAC {name},".encode('ascii') + payload)
        # Apply and couple amplitude/offset
        inst.write(f":SOURce{ch}:APPLy:ARBitrary {name},{ampl_vpp},{dc_offset_v}")
        inst.write(f":OUTPut{ch}:LOAD {load_ohms}")
        return True
    except Exception as e:
        print(f"[WARN] Binary DAC upload failed on CH{ch}: {e}. Trying ASCII path...")
        # 2) Fallback: older/alternate syntax using TRACE:DATA with ASCII values
        try:
            inst.write(f":SOURce{ch}:FUNCtion ARBitrary")
            inst.write(f":SOURce{ch}:ARBitrary:SRATe {fs}")
            inst.write(f":OUTPut{ch} OFF")
            # ASCII volts, comma-delimited; keep it compact (float32 strings)
            data = ",".join(f"{v:.5f}" for v in y.astype(np.float32))
            inst.write(f":SOURce{ch}:TRACe:DATA {name},{data}")
            inst.write(f":SOURce{ch}:APPLy:ARBitrary {name},{ampl_vpp},{dc_offset_v}")
            inst.write(f":OUTPut{ch}:LOAD {load_ohms}")
            return True
        except Exception as e2:
            print(f"[ERROR] ASCII upload failed on CH{ch}: {e2}")
            return False

def main():
    # Build waveforms
    y1, y2 = build_channels()
    assert len(y1) == len(y2)
    npts = len(y1)
    print(f"Waveform length = {npts} points ({duration_s*1e3:.1f} ms @ {fs/1e6:.1f} MSa/s)")

    rm = pyvisa.ResourceManager()
    if VISA_RESOURCE.lower() == 'auto':
        print("Available VISA resources:", rm.list_resources())
        return

    inst = rm.open_resource(VISA_RESOURCE, timeout=20000)  # 20 s for long transfers
    print("Connected to:", inst.query("*IDN?").strip())
    # Gentle start
    inst.write("*RST"); inst.write("*CLS")
    time.sleep(0.5)

    ok1 = upload_arb_dg900_pro(inst, 1, y1, fs, name=sequence_name)
    ok2 = upload_arb_dg900_pro(inst, 2, y2, fs, name=sequence_name)

    if not (ok1 and ok2):
        print("Upload failed. Tip: check DG922 firmware and SCPI programming guide for exact ARB commands.")
        inst.close(); return

    # Continuous mode
    if continuous_loop:
        # On many Rigol gens ARBs loop by default; ensure continuous
        inst.write(":INITiate1:CONTinuous ON")
        inst.write(":INITiate2:CONTinuous ON")

    # Turn on outputs
    if 1 in channel_enable:
        inst.write(":OUTPut1:POLarity NORM"); inst.write(":OUTPut1 ON")
    if 2 in channel_enable:
        inst.write(":OUTPut2:POLarity NORM"); inst.write(":OUTPut2 ON")

    print("Outputs enabled. You should now see TTL-like pulse trains on CH1/CH2.")
    print("Press Ctrl+C to quit; outputs will remain on until you turn them off or *RST.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Closing session...")
        inst.close()

if __name__ == "__main__":
    main()