#!/usr/bin/env python3
"""
Simple Example - Rigol MHO-984 Quick Start
===========================================
A minimal example to get started quickly with the Rigol MHO-984 oscilloscope.
"""

from rigol_mho984_data_acquisition import RigolMHO984, save_data_to_csv, plot_waveform
import time
import os


def main():
    print("=" * 60)
    print("Rigol MHO-984 - Simple Example")
    print("=" * 60)
    print()
    
    # Create output directory
    output_dir = r'C:\Users\Experiment\Documents\Python\VQ_Instruments\my_modules\oscilloscope_data'
   # os.makedirs(output_dir, exist_ok=True)
    
    CHANNEL = 2
    
    try:
        # Step 1: Connect to oscilloscope (auto-detect)
        print("Step 1: Connecting to oscilloscope...")
        scope = RigolMHO984()
        print("✓ Connected successfully!\n")
        
        # Step 2: Configure oscilloscope
        print("Step 2: Configuring oscilloscope...")
        scope.enable_channel(CHANNEL, True)           # Enable Channel 1
        scope.set_channel_scale(CHANNEL, 1.0)         # Set to 1V per division
        scope.set_timebase(1e-3)                # Set to 1ms per division
        scope.set_trigger_source(f'CHAN{CHANNEL}')       # Trigger on Channel 1
        scope.set_trigger_level(0.0)            # Trigger at 0V
        print("✓ Configuration complete!\n")
        
        # Step 3: Start acquisition
        print("Step 3: Acquiring waveform data...")
        scope.run()                             # Start continuous acquisition
        time.sleep(2)                           # Wait for stable signal
        scope.stop()                            # Stop and capture
        print("✓ Acquisition complete!\n")
        
        # Step 4: Get waveform data
        print("Step 4: Reading waveform data...")
        time_data, voltage_data, preamble = scope.acquire_waveform(CHANNEL)
        print(f"✓ Captured {len(voltage_data)} data points!\n")
        
        # Step 5: Get measurements
        print("Step 5: Performing measurements...")
        measurements = scope.get_measurements(CHANNEL)
        print("✓ Measurements:")
        print(f"   Peak-to-Peak: {measurements['vpp']:.3f} V")
        print(f"   RMS Voltage:  {measurements['vrms']:.3f} V")
        print(f"   Frequency:    {measurements['freq']/1e3:.2f} kHz")
        print(f"   Duty Cycle:   {measurements['duty']:.1f} %")
        print()
        
        # Step 6: Save data
        print("Step 6: Saving data...")
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save CSV
        csv_file = f'{output_dir}/waveform_ch{CHANNEL}_{timestamp}.csv'
        save_data_to_csv(time_data, voltage_data, csv_file, CHANNEL, measurements)
        print(f"✓ CSV saved: {csv_file}")
        
        # Save plot
        plot_file = f'{output_dir}/waveform_ch{CHANNEL}_{timestamp}.png'
        plot_waveform(time_data, voltage_data, CHANNEL, measurements, plot_file)
        print(f"✓ Plot saved: {plot_file}")
        
        # Save screenshot
        screenshot_file = f'{output_dir}/screenshot_{timestamp}.png'
        scope.save_screenshot(screenshot_file)
        print(f"✓ Screenshot saved: {screenshot_file}")
        print()
        
        # Step 7: Close connection
        print("Step 7: Closing connection...")
        scope.close()
        print("✓ Connection closed!\n")
        
        print("=" * 60)
        print("SUCCESS! All files saved to:", output_dir)
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting tips:")
        print("1. Make sure the oscilloscope is powered on")
        print("2. Check USB/Ethernet connection")
        print("3. Verify PyVISA is installed: pip install pyvisa pyvisa-py")
        print("4. Try running: python -c 'import pyvisa; print(pyvisa.ResourceManager().list_resources())'")


if __name__ == "__main__":
    main()
