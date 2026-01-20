
import time
import math
from moku.instruments import MultiInstrument, ArbitraryWaveformGenerator, Phasemeter

# ===== User settings =====
HOST ='localhost:8090'       # IPv4 or USB IPv6+%zone on Windows (e.g., 'fe80::7269:79ff:feb7:d15a%41')
FREQ_HZ = 1e6         # 1 MHz test tone
AMP_VPP = 0.5               # per-channel output amplitude (Vpp)
PHASE_CH1_DEG = 0.0
PHASE_CH2_DEG = 45.0

# Phasemeter PLL configuration
PLL_BW_HZ = '1kHz'           # 0.3–5 kHz typical; increase if source drifts, decrease if noisy

# Front-end settings (match your bench and loads)
INPUT_IMPEDANCE = '50Ohm'   # 'FiftyOhm' or 'OneMeg'
COUPLING = 'DC'                # 'DC' or 'AC'
RANGE_VPP = '1Vpp'                # choose the smallest non-clipping range

# Acquisition parameters
READS = 10
READ_DT = 0.2  # seconds between reads

def wrap_deg(x):
    """Wrap angle to (-180, 180]."""
    y = (x + 180.0) % 360.0 - 180.0
    return 180.0 if y == -180.0 else y

def detect_deg(delta_raw):
    """
    Convert raw phase difference (PM may report radians or cycles) to degrees.
    Pick the interpretation that is "more wrapped" (smaller absolute wrapped magnitude).
    """
    d_rad = math.degrees(delta_raw)
    d_cyc = delta_raw * 360.0
    return d_rad if abs(wrap_deg(d_rad)) <= abs(wrap_deg(d_cyc)) else d_cyc

# ===== Build a 2-slot Multi-Instrument config: Slot1=WG, Slot2=Phasemeter =====
mim = MultiInstrument(HOST, platform_id=2, force_connect=True)  # take ownership if needed
wg = mim.set_instrument(1, ArbritraryWaveformGenerator)
pm = mim.set_instrument(2, Phasemeter)

try:
    # --- Lossless internal routing (no cables) ---
    # Slot1OutA (WG CH1) -> Slot2InA (PM CH1)
    # Slot1OutB (WG CH2) -> Slot2InB (PM CH2)
    mim.set_connections([
        dict(source="Slot1OutA", destination="Slot2InA"),
        dict(source="Slot1OutB", destination="Slot2InB"),
    ])  # [2](https://res.cloudinary.com/iwh/image/upload/q_auto,g_center/assets/1/26/Liquid-Moku-Lab-FSB-QSG.pdf)

    # --- Configure Waveform Generator (two coherent sines) ---
    # Terminations (optional): 'FiftyOhm' or 'HiZ'
    try:
        wg.set_output_termination(1, '50Ohms')
        wg.set_output_termination(2, '50Ohms')
    except Exception:
        # Older client versions may use set_output_load/load semantics
        pass

    # Program both channels with explicit phase
    wg.generate_waveform(channel=1, type='Sine',
                         amplitude=AMP_VPP, frequency=FREQ_HZ, phase=PHASE_CH1_DEG)
    wg.generate_waveform(channel=2, type='Sine',
                         amplitude=AMP_VPP, frequency=FREQ_HZ, phase=PHASE_CH2_DEG)
    # Force both outputs to share a common phase reference (applies their offsets atomically)
    wg.sync_phase()  # ← the key to “force phase sync” on Moku WG  [1](https://apis.liquidinstruments.com/api/getting-started/ip-address.html)

    # --- Configure Phasemeter front-end and lock ---
    pm.set_frontend(1, impedance=INPUT_IMPEDANCE, coupling=COUPLING, range=RANGE_VPP)
    pm.set_frontend(2, impedance=INPUT_IMPEDANCE, coupling=COUPLING, range=RANGE_VPP)
    pm.enable_input(1, True); pm.enable_input(2, True)

    pm.set_pm_loop(1, frequency=FREQ_HZ, bandwidth=PLL_BW_HZ)
    pm.set_pm_loop(2, frequency=FREQ_HZ, bandwidth=PLL_BW_HZ)
    pm.reacquire(); time.sleep(0.3)  # let PLLs settle  [5](https://knowledge.liquidinstruments.com/python-api-examples)

    # Use CH1 as reference
    pm.zero_phase(1); time.sleep(0.2)

    print(f"Measuring Δφ(CH2 - CH1) at {FREQ_HZ/1e6:.3f} MHz (expect ≈ {PHASE_CH2_DEG:.1f}°):")
    vals = []
    for _ in range(READS):
        data = pm.get_data()  # {'ch1': {'phase',...}, 'ch2': {...}, ...}
        phi1 = data['ch1']['phase']
        phi2 = data['ch2']['phase']
        vals.append(detect_deg(phi2 - phi1))
        time.sleep(READ_DT)

    # Average and print
    vals = [wrap_deg(v) for v in vals]
    avg = sum(vals) / len(vals)
    jitter = (sum((x-avg)**2 for x in vals) / len(vals)) ** 0.5
    print(f"Δφ ≈ {avg:.2f}°  (±{jitter:.2f}° over {len(vals)} samples)")

finally:
    # Always relinquish ownership so later scripts can connect cleanly
    try:
        mim.relinquish_ownership()
    except Exception:
        pass
