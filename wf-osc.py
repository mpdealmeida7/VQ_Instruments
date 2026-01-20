
# moku_mim_wavegen_osc.py
# Multi-Instrument: Slot 1 = Waveform Generator, Slot 2 = Oscilloscope
# Signal: 1 MHz sine, 0.5 Vpp on Output 1; scope reads Input 1.

from moku.instruments import MultiInstrument, WaveformGenerator, Oscilloscope
import matplotlib.pyplot as plt

MOKU_IP = "localhost:8090"  # <-- set your Moku:Lab IP here

# User-desired signal
FREQ_HZ = 1e6    # 1 MHz
VPP = 0.5               # 0.5 Vpp
OFFSET = 0.0            # 0 V DC offset

# Scope view settings (show a few microseconds around trigger)
T_LEFT = -2e-6
T_RIGHT = 2e-6

# Connect to Multi-Instrument Mode (platform_id=2 enables 2-slot MIM layouts on Moku:Lab)
mim = MultiInstrument(MOKU_IP, force_connect=True, platform_id=2)  # MIM selection via platform_id
try:
    # Load instruments into slots
    wfg = mim.set_instrument(1, WaveformGenerator)  # Slot 1: Waveform Generator
    osc = mim.set_instrument(2, Oscilloscope)       # Slot 2: Oscilloscope
    
    connections = [dict(source="Input1", destination="Slot1InA"),
               dict(source="Slot1OutA", destination="Slot2InA"),
               dict(source="Slot1OutA", destination="Slot2InB"),
               dict(source="Slot2OutA", destination="Output1")]
    
    mim.set_connections(connections=connections)
    
    

    # --- Physical cabling: Out 1 -> In 1.
    # No internal MIM connection required in this case.

    # Configure Waveform Generator: Sine on Channel 1
    # Note: amplitude parameter is the requested amplitude; strict=True (default) enforces validity.
    mim.set_frontend(channel=1, impedance="50Ohm", coupling="DC", gain="0dB", strict=True)
    
    wfg.generate_waveform(
        channel=1,
        type='Sine',
        frequency=FREQ_HZ,
        amplitude=VPP,
        offset=OFFSET
    )  # Waveform Generator API and generate_waveform usage documented here. [1](https://apis.liquidinstruments.com/api/reference/waveformgenerator/)

    # Output termination: choose 'HiZ' if you're feeding a 1 MΩ scope input to avoid halving Vpp.
    # If you set 50 Ω here and also 50 Ω on the oscilloscope input, your on-screen Vpp will be ~VPP/2.
    #wfg.set_output_termination(channel=1, termination='HiZ')  # or '50Ohm' as needed. [1](https://apis.liquidinstruments.com/api/reference/waveformgenerator/)

    # Configure Oscilloscope front-end for Input 1
    # Use high-impedance DC-coupled input and a sensible range (e.g., ±1 V).
    # set_frontend lets you control impedance, coupling, and input range. [2](https://apis.liquidinstruments.com/api/reference/oscilloscope/)
    # osc.set_frontend(
    #     channel=1,
    #     impedance='1MOhm',     # '1MOhm' to avoid loading; use '50Ohm' if you need matched termination
    #     coupling='DC',
    #     range='1Vpp', # ±1 V full scale is ample for a 0.5 Vpp signal
    #     bandwidth='300MHz',
    #     strict=True
    # )

    # Timebase and trigger (trigger on CH1 @ 0 V rising)
    # osc.set_timebase(T_LEFT, T_RIGHT)  # timebase definition in API. [5](https://apis.liquidinstruments.com/api/reference/oscilloscope/set_timebase.html)
    # osc.set_trigger(
    #     source='Input1',         # trigger source
    #     edge='Rising',
    #     level=0.0,               # 0 V crossing
    #     mode='Auto'
    # )  # Trigger configuration is part of Oscilloscope API. [2](https://apis.liquidinstruments.com/api/reference/oscilloscope/)

    # Optional: synchronize phases if you were using multiple outputs (not necessary for single-channel)
    # wfg.sync_phase()  # Waveform Generator phase sync. [1](https://apis.liquidinstruments.com/api/reference/waveformgenerator/)

    # Acquire a frame
    data = osc.get_data()        # get_data returns {'time', 'ch1', 'ch2'} arrays. [2](https://apis.liquidinstruments.com/api/reference/oscilloscope/)

    # Plot
    t = data['time']
    y = data['ch1']
    plt.figure(figsize=(8, 4))
    plt.plot(t, y, label='CH1 (In 1)')
    plt.title('Moku:Lab - 1 MHz, 0.5 Vpp Sine (Out1 → In1)')
    plt.xlabel('Time [µs]')
    plt.ylabel('Voltage [V]')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

finally:
    # Always relinquish ownership so others (or the UI) can access the device again
    try:
        mim.relinquish_ownership()
    except Exception:
        pass
