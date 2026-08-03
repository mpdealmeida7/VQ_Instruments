#!/usr/bin/env python3
"""
Rigol MHO-984 Oscilloscope - Automated Data Acquisition Script
===============================================================
This script automates data acquisition from the Rigol MHO-984 oscilloscope
using PyVISA for SCPI communication.

Requirements:
    pip install pyvisa pyvisa-py numpy matplotlib pandas

Usage:
    python rigol_mho984_data_acquisition.py
"""

import pyvisa
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import time
import os


class RigolMHO984:
    """Class to control Rigol MHO-984 Oscilloscope"""
    
    def __init__(self, resource_string=None):
        """
        Initialize connection to oscilloscope
        
        Args:
            resource_string: VISA resource string (e.g., 'USB0::0x1AB1::0x0515::MHO9AXXXXXXX::INSTR'
                           or 'TCPIP::192.168.1.100::INSTR')
        """
        self.rm = pyvisa.ResourceManager()
        
        if resource_string is None:
            # Auto-detect oscilloscope
            resources = self.rm.list_resources()
            print(f"Available resources: {resources}")
            
            # Look for Rigol device
            rigol_devices = [r for r in resources if 'RIGOL' in r.upper() or '0x1AB1' in r]
            
            if not rigol_devices:
                print("\nNo Rigol device found. Available devices:")
                for r in resources:
                    print(f"  - {r}")
                raise ConnectionError("No Rigol oscilloscope detected. Please specify resource string manually.")
            
            resource_string = rigol_devices[0]
            print(f"\nAuto-detected: {resource_string}")
        
        try:
            self.scope = self.rm.open_resource(resource_string)
            self.scope.timeout = 10000  # 10 second timeout
            self.scope.chunk_size = 1024 * 1024  # 1MB chunks for large data transfers
            
            # Get device identification
            idn = self.scope.query('*IDN?')
            print(f"Connected to: {idn.strip()}")
            
        except Exception as e:
            raise ConnectionError(f"Failed to connect to oscilloscope: {e}")
    
    def reset(self):
        """Reset oscilloscope to default settings"""
        self.scope.write('*RST')
        time.sleep(2)
        print("Oscilloscope reset to default settings")
    
    def auto_setup(self):
        """Perform auto setup"""
        self.scope.write(':AUT')
        time.sleep(3)
        print("Auto setup completed")
    
    def get_channel_status(self, channel):
        """
        Check if channel is enabled
        
        Args:
            channel: Channel number (1-4)
        
        Returns:
            bool: True if channel is on, False otherwise
        """
        status = self.scope.query(f':CHAN{channel}:DISP?')
        return '1' in status or 'ON' in status.upper()
    
    def enable_channel(self, channel, enable=True):
        """
        Enable or disable a channel
        
        Args:
            channel: Channel number (1-4)
            enable: True to enable, False to disable
        """
        state = 'ON' if enable else 'OFF'
        self.scope.write(f':CHAN{channel}:DISP {state}')
        print(f"Channel {channel} {'enabled' if enable else 'disabled'}")
    
    def set_channel_scale(self, channel, scale):
        """
        Set vertical scale for a channel
        
        Args:
            channel: Channel number (1-4)
            scale: Vertical scale in V/div (e.g., 0.5, 1, 2)
        """
        self.scope.write(f':CHAN{channel}:SCAL {scale}')
        print(f"Channel {channel} scale set to {scale} V/div")
    
    def set_timebase(self, scale):
        """
        Set horizontal timebase
        
        Args:
            scale: Time scale in s/div (e.g., 1e-6 for 1 µs/div)
        """
        self.scope.write(f':TIM:SCAL {scale}')
        print(f"Timebase set to {scale} s/div")
    
    def set_trigger_mode(self, mode='EDGE'):
        """
        Set trigger mode
        
        Args:
            mode: Trigger mode ('EDGE', 'PULSE', 'VIDEO', etc.)
        """
        self.scope.write(f':TRIG:MODE {mode}')
        print(f"Trigger mode set to {mode}")
    
    def set_trigger_source(self, source='CHAN1'):
        """
        Set trigger source
        
        Args:
            source: Trigger source ('CHAN1', 'CHAN2', 'CHAN3', 'CHAN4', 'EXT', 'AC')
        """
        self.scope.write(f':TRIG:EDGE:SOUR {source}')
        print(f"Trigger source set to {source}")
    
    def set_trigger_level(self, level):
        """
        Set trigger level
        
        Args:
            level: Trigger level in volts
        """
        self.scope.write(f':TRIG:EDGE:LEV {level}')
        print(f"Trigger level set to {level} V")
    
    def set_trigger_slope(self, slope='POS'):
        """
        Set trigger slope
        
        Args:
            slope: 'POS' for positive, 'NEG' for negative, 'RFAL' for either
        """
        self.scope.write(f':TRIG:EDGE:SLOP {slope}')
        print(f"Trigger slope set to {slope}")
    
    def get_waveform_preamble(self, channel):
        """
        Get waveform preamble information
        
        Args:
            channel: Channel number (1-4)
        
        Returns:
            dict: Dictionary with waveform parameters
        """
        self.scope.write(f':WAV:SOUR CHAN{channel}')
        preamble = self.scope.query(':WAV:PRE?').split(',')
        
        return {
            'format': int(preamble[0]),
            'type': int(preamble[1]),
            'points': int(preamble[2]),
            'count': int(preamble[3]),
            'xincrement': float(preamble[4]),
            'xorigin': float(preamble[5]),
            'xreference': float(preamble[6]),
            'yincrement': float(preamble[7]),
            'yorigin': float(preamble[8]),
            'yreference': float(preamble[9])
        }
    
    def acquire_waveform(self, channel, mode='NORM'):
        """
        Acquire waveform data from specified channel
        
        Args:
            channel: Channel number (1-4)
            mode: Waveform mode ('NORM', 'MAX', 'RAW')
        
        Returns:
            tuple: (time_array, voltage_array, preamble_dict)
        """
        # Check if channel is enabled
        if not self.get_channel_status(channel):
            print(f"Warning: Channel {channel} is not enabled. Enabling it now...")
            self.enable_channel(channel, True)
            time.sleep(0.5)
        
        # Set waveform source
        self.scope.write(f':WAV:SOUR CHAN{channel}')
        
        # Set waveform mode
        self.scope.write(f':WAV:MODE {mode}')
        
        # Set waveform format to BYTE for faster transfer
        self.scope.write(':WAV:FORM BYTE')
        
        # Get preamble
        preamble = self.get_waveform_preamble(channel)
        
        # Read waveform data
        self.scope.write(':WAV:DATA?')
        raw_data = self.scope.read_raw()
        
        # Parse data (skip header)
        # TMC header format: #NXXXXXXXXX where N is number of digits, X is data length
        header_len = 2 + int(chr(raw_data[1]))
        data = np.frombuffer(raw_data[header_len:-1], dtype=np.uint8)
        
        # Convert to voltage
        voltage = (data - preamble['yorigin'] - preamble['yreference']) * preamble['yincrement']
        
        # Create time array
        time_array = np.arange(len(voltage)) * preamble['xincrement'] + preamble['xorigin']
        
        print(f"Acquired {len(voltage)} points from Channel {channel}")
        
        return time_array, voltage, preamble
    
    def get_measurements(self, channel):
        """
        Get automatic measurements for a channel
        
        Args:
            channel: Channel number (1-4)
        
        Returns:
            dict: Dictionary with measurement values
        """
        measurements = {}
        
        # Set measurement source
        self.scope.write(f':MEAS:SOUR CHAN{channel}')
        
        # Common measurements
        meas_types = {
            'vpp': 'VPP',      # Peak-to-peak voltage
            'vmax': 'VMAX',    # Maximum voltage
            'vmin': 'VMIN',    # Minimum voltage
            'vtop': 'VTOP',    # Top voltage
            'vbase': 'VBAS',   # Base voltage
            'vamp': 'VAMP',    # Amplitude
            'vavg': 'VAVG',    # Average voltage
            'vrms': 'VRMS',    # RMS voltage
            'freq': 'FREQ',    # Frequency
            'period': 'PER',   # Period
            'rise_time': 'RIS',  # Rise time
            'fall_time': 'FALL', # Fall time
            'duty': 'DUTY',    # Duty cycle
        }
        
        for name, cmd in meas_types.items():
            try:
                value = self.scope.query(f':MEAS:{cmd}? CHAN{channel}')
                measurements[name] = float(value)
            except:
                measurements[name] = None
        
        return measurements
    
    def single_acquisition(self):
        """Set to single acquisition mode and wait for trigger"""
        self.scope.write(':SING')
        print("Waiting for trigger...")
        
        # Wait for acquisition to complete
        timeout = 30  # 30 second timeout
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.scope.query(':TRIG:STAT?').strip()
            if 'STOP' in status:
                print("Acquisition complete")
                return True
            time.sleep(0.1)
        
        print("Acquisition timeout")
        return False
    
    def run(self):
        """Start continuous acquisition"""
        self.scope.write(':RUN')
        print("Continuous acquisition started")
    
    def stop(self):
        """Stop acquisition"""
        self.scope.write(':STOP')
        print("Acquisition stopped")
    
    def save_screenshot(self, filename):
        """
        Save oscilloscope screenshot
        
        Args:
            filename: Output filename (PNG format)
        """
        self.scope.write(':DISP:DATA?')
        raw_data = self.scope.read_raw()
        
        # Save to file
        with open(filename, 'wb') as f:
            f.write(raw_data[11:])  # Skip TMC header
        
        print(f"Screenshot saved to {filename}")
    
    def close(self):
        """Close connection to oscilloscope"""
        self.scope.close()
        self.rm.close()
        print("Connection closed")
    
    # ==================== WAVE GENERATOR FUNCTIONS ====================
    
    def wgen_enable(self, enable=True):
        """
        Enable or disable the built-in wave generator
        
        Args:
            enable: True to enable, False to disable
        """
        state = 'ON' if enable else 'OFF'
        self.scope.write(f':WGEN:OUTP {state}')
        print(f"Wave generator {'enabled' if enable else 'disabled'}")
    
    def wgen_set_function(self, function='SIN'):
        """
        Set wave generator function type
        
        Args:
            function: Waveform type - 'SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'ARB'
        """
        valid_functions = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'ARB']
        if function.upper() not in valid_functions:
            raise ValueError(f"Invalid function. Must be one of: {valid_functions}")
        
        self.scope.write(f':WGEN:FUNC {function}')
        print(f"Wave generator function set to {function}")
    
    def wgen_set_frequency(self, frequency):
        """
        Set wave generator frequency
        
        Args:
            frequency: Frequency in Hz (range depends on waveform type)
                      Typical range: 0.1 Hz to 25 MHz for sine wave
        """
        self.scope.write(f':WGEN:FREQ {frequency}')
        print(f"Wave generator frequency set to {frequency} Hz")
    
    def wgen_set_amplitude(self, amplitude):
        """
        Set wave generator amplitude (peak-to-peak)
        
        Args:
            amplitude: Amplitude in Vpp (typically 0.002 to 5 Vpp into 50Ω)
        """
        self.scope.write(f':WGEN:VOLT {amplitude}')
        print(f"Wave generator amplitude set to {amplitude} Vpp")
    
    def wgen_set_offset(self, offset):
        """
        Set wave generator DC offset
        
        Args:
            offset: DC offset in volts (typically ±2.5V into 50Ω)
        """
        self.scope.write(f':WGEN:VOLT:OFFS {offset}')
        print(f"Wave generator offset set to {offset} V")
    
    def wgen_set_duty_cycle(self, duty):
        """
        Set duty cycle for square or pulse waveforms
        
        Args:
            duty: Duty cycle in percent (typically 20% to 80%)
        """
        self.scope.write(f':WGEN:FUNC:SQU:DCYC {duty}')
        print(f"Wave generator duty cycle set to {duty}%")
    
    def wgen_set_pulse_width(self, width):
        """
        Set pulse width for pulse waveforms
        
        Args:
            width: Pulse width in seconds
        """
        self.scope.write(f':WGEN:FUNC:PULS:WIDT {width}')
        print(f"Wave generator pulse width set to {width} s")
    
    def wgen_set_ramp_symmetry(self, symmetry):
        """
        Set ramp symmetry
        
        Args:
            symmetry: Symmetry in percent (0-100%)
                     0% = sawtooth down, 50% = triangle, 100% = sawtooth up
        """
        self.scope.write(f':WGEN:FUNC:RAMP:SYMM {symmetry}')
        print(f"Wave generator ramp symmetry set to {symmetry}%")
    
    def wgen_set_impedance(self, impedance='OMEG'):
        """
        Set output impedance setting
        
        Args:
            impedance: 'OMEG' for high impedance (>1MΩ), 'FIFT' for 50Ω
        """
        if impedance.upper() not in ['OMEG', 'FIFT']:
            raise ValueError("Impedance must be 'OMEG' (high-Z) or 'FIFT' (50Ω)")
        
        self.scope.write(f':WGEN:OUTP:IMP {impedance}')
        print(f"Wave generator impedance set to {impedance}")
    
    def wgen_get_status(self):
        """
        Get wave generator status and configuration
        
        Returns:
            dict: Dictionary with wave generator parameters
        """
        status = {}
        
        try:
            status['output'] = self.scope.query(':WGEN:OUTP?').strip()
            status['function'] = self.scope.query(':WGEN:FUNC?').strip()
            status['frequency'] = float(self.scope.query(':WGEN:FREQ?'))
            status['amplitude'] = float(self.scope.query(':WGEN:VOLT?'))
            status['offset'] = float(self.scope.query(':WGEN:VOLT:OFFS?'))
            status['impedance'] = self.scope.query(':WGEN:OUTP:IMP?').strip()
        except Exception as e:
            print(f"Error reading wave generator status: {e}")
        
        return status
    
    def wgen_configure_sine(self, frequency, amplitude, offset=0.0, enable=True):
        """
        Quick configuration for sine wave
        
        Args:
            frequency: Frequency in Hz
            amplitude: Amplitude in Vpp
            offset: DC offset in volts (default 0)
            enable: Enable output (default True)
        """
        self.wgen_set_function('SIN')
        self.wgen_set_frequency(frequency)
        self.wgen_set_amplitude(amplitude)
        self.wgen_set_offset(offset)
        if enable:
            self.wgen_enable(True)
        
        print(f"Wave generator configured: {frequency} Hz sine, {amplitude} Vpp, {offset} V offset")
    
    def wgen_configure_square(self, frequency, amplitude, duty_cycle=50, offset=0.0, enable=True):
        """
        Quick configuration for square wave
        
        Args:
            frequency: Frequency in Hz
            amplitude: Amplitude in Vpp
            duty_cycle: Duty cycle in percent (default 50)
            offset: DC offset in volts (default 0)
            enable: Enable output (default True)
        """
        self.wgen_set_function('SQU')
        self.wgen_set_frequency(frequency)
        self.wgen_set_amplitude(amplitude)
        self.wgen_set_duty_cycle(duty_cycle)
        self.wgen_set_offset(offset)
        if enable:
            self.wgen_enable(True)
        
        print(f"Wave generator configured: {frequency} Hz square, {amplitude} Vpp, {duty_cycle}% duty, {offset} V offset")
    
    def wgen_configure_ramp(self, frequency, amplitude, symmetry=50, offset=0.0, enable=True):
        """
        Quick configuration for ramp/triangle wave
        
        Args:
            frequency: Frequency in Hz
            amplitude: Amplitude in Vpp
            symmetry: Symmetry in percent (default 50 for triangle)
            offset: DC offset in volts (default 0)
            enable: Enable output (default True)
        """
        self.wgen_set_function('RAMP')
        self.wgen_set_frequency(frequency)
        self.wgen_set_amplitude(amplitude)
        self.wgen_set_ramp_symmetry(symmetry)
        self.wgen_set_offset(offset)
        if enable:
            self.wgen_enable(True)
        
        print(f"Wave generator configured: {frequency} Hz ramp, {amplitude} Vpp, {symmetry}% symmetry, {offset} V offset")
    
    def wgen_configure_pulse(self, frequency, amplitude, pulse_width=None, offset=0.0, enable=True):
        """
        Quick configuration for pulse wave
        
        Args:
            frequency: Frequency in Hz
            amplitude: Amplitude in Vpp
            pulse_width: Pulse width in seconds (if None, uses 50% duty cycle)
            offset: DC offset in volts (default 0)
            enable: Enable output (default True)
        """
        self.wgen_set_function('PULS')
        self.wgen_set_frequency(frequency)
        self.wgen_set_amplitude(amplitude)
        
        if pulse_width is not None:
            self.wgen_set_pulse_width(pulse_width)
        
        self.wgen_set_offset(offset)
        if enable:
            self.wgen_enable(True)
        
        print(f"Wave generator configured: {frequency} Hz pulse, {amplitude} Vpp, {offset} V offset")
    
    def wgen_configure_dc(self, offset, enable=True):
        """
        Quick configuration for DC output
        
        Args:
            offset: DC voltage level in volts
            enable: Enable output (default True)
        """
        self.wgen_set_function('DC')
        self.wgen_set_offset(offset)
        if enable:
            self.wgen_enable(True)
        
        print(f"Wave generator configured: DC output at {offset} V")
    
    def wgen_configure_noise(self, amplitude, offset=0.0, enable=True):
        """
        Quick configuration for noise output
        
        Args:
            amplitude: Noise amplitude in Vpp
            offset: DC offset in volts (default 0)
            enable: Enable output (default True)
        """
        self.wgen_set_function('NOIS')
        self.wgen_set_amplitude(amplitude)
        self.wgen_set_offset(offset)
        if enable:
            self.wgen_enable(True)
        
        print(f"Wave generator configured: Noise, {amplitude} Vpp, {offset} V offset")


def save_data_to_csv(time_data, voltage_data, filename, channel, measurements=None):
    """
    Save waveform data to CSV file
    
    Args:
        time_data: Time array
        voltage_data: Voltage array
        filename: Output filename
        channel: Channel number
        measurements: Optional measurements dictionary
    """
    df = pd.DataFrame({
        'Time (s)': time_data,
        f'Channel {channel} (V)': voltage_data
    })
    
    # Add measurements as metadata in header
    with open(filename, 'w') as f:
        f.write(f"# Rigol MHO-984 Data Acquisition\n")
        f.write(f"# Channel: {channel}\n")
        f.write(f"# Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        if measurements:
            f.write(f"# Measurements:\n")
            for key, value in measurements.items():
                if value is not None:
                    f.write(f"#   {key}: {value}\n")
        
        f.write("#\n")
    
    df.to_csv(filename, mode='a', index=False)
    print(f"Data saved to {filename}")


def plot_waveform(time_data, voltage_data, channel, measurements=None, filename=None):
    """
    Plot waveform data
    
    Args:
        time_data: Time array
        voltage_data: Voltage array
        channel: Channel number
        measurements: Optional measurements dictionary
        filename: Optional output filename for saving plot
    """
    plt.figure(figsize=(12, 6))
    plt.plot(time_data * 1e6, voltage_data, linewidth=0.5)  # Convert to microseconds
    plt.xlabel('Time (µs)')
    plt.ylabel('Voltage (V)')
    plt.title(f'Rigol MHO-984 - Channel {channel} Waveform')
    plt.grid(True, alpha=0.3)
    
    # Add measurements as text
    if measurements:
        text_str = "Measurements:\n"
        for key, value in measurements.items():
            if value is not None:
                if 'freq' in key:
                    text_str += f"{key}: {value/1e3:.2f} kHz\n"
                elif 'period' in key or 'time' in key:
                    text_str += f"{key}: {value*1e6:.2f} µs\n"
                elif 'duty' in key:
                    text_str += f"{key}: {value:.1f}%\n"
                else:
                    text_str += f"{key}: {value:.3f} V\n"
        
        plt.text(0.02, 0.98, text_str, transform=plt.gca().transAxes,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
                fontsize=9, family='monospace')
    
    plt.tight_layout()
    
    if filename:
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"Plot saved to {filename}")
    else:
        plt.show()
    
    plt.close()


def main():
    """Main data acquisition routine"""
    
    print("=" * 70)
    print("Rigol MHO-984 Oscilloscope - Automated Data Acquisition")
    print("=" * 70)
    print()
    
    # Create output directory
    output_dir = r'C:\Users\Experiment\Documents\Python\VQ_Instruments\my_modules\oscilloscope_data'
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # Connect to oscilloscope
        # Option 1: Auto-detect
        scope = RigolMHO984()
        
        # Option 2: Manual connection (uncomment and modify if needed)
        # scope = RigolMHO984('TCPIP::192.168.1.100::INSTR')
        # scope = RigolMHO984('USB0::0x1AB1::0x0515::MHO9AXXXXXXX::INSTR')
        
        print()
        print("-" * 70)
        print("Configuring Oscilloscope...")
        print("-" * 70)
        
        # Configure oscilloscope
        scope.enable_channel(1, True)
        scope.set_channel_scale(1, 1.0)  # 1V/div
        scope.set_timebase(1e-3)  # 1ms/div
        
        # Configure trigger
        scope.set_trigger_mode('EDGE')
        scope.set_trigger_source('CHAN1')
        scope.set_trigger_level(0.0)
        scope.set_trigger_slope('POS')
        
        print()
        print("-" * 70)
        print("Acquiring Data...")
        print("-" * 70)
        
        # Start acquisition
        scope.run()
        time.sleep(2)  # Wait for stable acquisition
        
        # Stop to capture current screen
        scope.stop()
        
        # Acquire waveform from Channel 1
        time_data, voltage_data, preamble = scope.acquire_waveform(1, mode='NORM')
        
        # Get measurements
        measurements = scope.get_measurements(1)
        
        print()
        print("-" * 70)
        print("Measurements:")
        print("-" * 70)
        for key, value in measurements.items():
            if value is not None:
                print(f"{key:15s}: {value}")
        
        # Generate timestamp for filenames
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save data to CSV
        csv_filename = f'{output_dir}/waveform_ch1_{timestamp}.csv'
        save_data_to_csv(time_data, voltage_data, csv_filename, 1, measurements)
        
        # Plot and save waveform
        plot_filename = f'{output_dir}/waveform_ch1_{timestamp}.png'
        plot_waveform(time_data, voltage_data, 1, measurements, plot_filename)
        
        # Save screenshot
        screenshot_filename = f'{output_dir}/screenshot_{timestamp}.png'
        scope.save_screenshot(screenshot_filename)
        
        print()
        print("-" * 70)
        print("Data Acquisition Complete!")
        print("-" * 70)
        print(f"Output files saved in: {output_dir}")
        
        # Close connection
        scope.close()
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
