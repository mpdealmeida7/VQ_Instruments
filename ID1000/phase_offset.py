import math

def calculate_relative_generator_phase(frequency_hz, visual_delay_ns, 
                                     len1_m=3.0, len2_m=3.0, 
                                     vf=0.70):
    """
    Calculates the generator phase required to see a specific time 
    offset at the end of two SMA cables.
    
    Args:
        frequency_hz: Signal frequency (Hz)
        visual_delay_ns: Desired time between pulses at the cable ends (ns)
        len1_m: Length of cable on Channel 1 (m)
        len2_m: Length of cable on Channel 2 (m)
        vf: Velocity Factor (default 0.70 for RG316/RG58)
    """
    c = 299792458  # Speed of light m/s
    
    # 1. Propagation delay for each cable
    delay1 = len1_m / (c * vf)
    delay2 = len2_m / (c * vf)
    
    # 2. Relative cable delay (Channel 2 relative to Channel 1)
    # If len2 > len1, the signal in cable 2 arrives LATER naturally.
    cable_diff_s = delay2 - delay1
    
    # 3. Required generator delay to reach visual target
    # Generator_Delay + Cable_Diff = Visual_Target
    gen_delay_s = (visual_delay_ns * 1e-9) - cable_diff_s
    
    # 4. Convert to Phase
    phase_deg = (360.0 * frequency_hz * gen_delay_s) % 360
    
    return {
        "cable_1_delay_ns": delay1 * 1e9,
        "cable_2_delay_ns": delay2 * 1e9,
        "net_cable_skew_ns": cable_diff_s * 1e9,
        "required_phase_deg": phase_deg
    }

# --- CONFIGURATION ---
FREQ = 10e6           # 5 MHz
WANT_DELAY = 10.0    # Want to see 40ns gap on the scope

res = calculate_relative_generator_phase(FREQ, WANT_DELAY, len1_m=3.0, len2_m=3.0)

print(f"To see a {WANT_DELAY}ns offset at the end of 3m cables:")
print(f"Set Channel 2 Phase to: {res['required_phase_deg']:.2f}°")
print(f"(Note: Cable skew is {res['net_cable_skew_ns']:.2f}ns if lengths are identical)")
