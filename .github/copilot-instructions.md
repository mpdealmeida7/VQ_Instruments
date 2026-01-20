# VQ_Instruments Codebase Guide

## Project Overview
VQ_Instruments is a Python library for controlling laboratory test equipment via USB/serial interfaces. It provides wrapper classes around hardware drivers for optical and RF instruments used in photonics research and testing at VeriQuantix.

## Architecture & Components

### Device Controller Pattern
Three main device wrapper patterns exist:

1. **PyVISA-Based Drivers** (for VISA-compliant USB instruments)
   - **[DH1022.py](DH1022.py)**: Rigol waveform generator (USB VISA protocol)
   - Uses `pyvisa` ResourceManager to communicate via VISA over USB
   - Commands sent as SCPI strings via `inst.write()` and `inst.query()`
   - Key pattern: Always set `inst.timeout`, `write_termination`, `read_termination` after opening

2. **ctypes-Based Low-Level Drivers** (for closed-source C libraries)
   - **[TLPMX.py](TLPMX.py)**: Thorlabs power meter SDK wrapper (~7400 lines)
   - Loads platform-specific `.dll`/`.so` via `ctypes.cdll.LoadLibrary()`
   - Defines USB device PIDs and VISA find patterns for all supported Thorlabs PM models
   - **[PMDevice.py](PMDevice.py)**: High-level OOP wrapper around TLPMX raw C interface
   - Translates C ctypes calls to Pythonic methods (wavelength, autorange, measurements)

3. **Serial Port Drivers** (for legacy RS-232/USB serial instruments)
   - **[BCB-4_V2.py](BCB-4_V2.py)**: Fiber optic controller (9600 baud, 8-N-1, CR+LF termination)
   - **[TLX_5.py](TLX_5.py)**: Thorlabs TLX5 laser (115200 baud, ASCII commands)
   - Pattern: `serial.Serial()` with explicit protocol settings (no flow control)
   - Commands are ASCII strings with `\r\n` or `\n` line terminators

### Moku Integration
- **[moku_test.py](moku_test.py)**: Python SDK for Liquid Instruments Moku oscilloscope
- Uses IP-based connection over network (`'localhost:8090'` or IP address)
- Higher abstraction level: methods like `set_trigger()`, `generate_waveform()`, `get_data()`
- Force-reconnect via `force_connect=True` parameter

## Critical Patterns & Conventions

### Hardware Communication
- **USB VISA**: Always use `pyvisa.ResourceManager()` for VISA-compliant instruments; set timeout/termination immediately
- **Serial Port**: Use `pyserial` with explicit protocol config; always call `time.sleep()` after connect/before read for device handshake
- **Network**: Moku uses IP connection; supports force_connect to override existing sessions

### Command Structure
- **SCPI Protocol**: `/SOURce{ch}:APPLy:{wave}` pattern for function generators (channel-based)
- **Laser Control**: `LASer:ON:1`, `LASer:WAVElength:{nm}`, `LASer:POWer?` format
- **Device Commands**: Addressed via device number (0–9) in BCB-4: `SETADD:X`, `command:X`

### Error Handling
- PyVISA: Check `inst.query('*OPC?')` to wait for command completion
- ctypes Drivers: Check return status codes (0 = success, non-zero = error)
- Serial: Catch `serial.SerialException` and `serial.SerialTimeoutException`

## Development Workflow

### Device Discovery
```python
# PyVISA discovery
import pyvisa
rm = pyvisa.ResourceManager()
resources = rm.list_resources("USB?*INSTR")

# Thorlabs Power Meter (uses TLPMX pattern matching)
# Pre-defined VISA patterns in TLPMX.py: TLPM_FIND_PATTERN, PM100USB_FIND_PATTERN, etc.
```

### Testing & Debugging
- **PM100USB.ipynb**: Jupyter notebook for interactive power meter testing
- Script files (e.g., `moku_phase_test_5.py`) are experimental test harnesses
- `Test.py`: Minimal placeholder for quick validation
- Use `instruments/` venv for isolated testing environment

### Virtual Environment
- `instruments/` directory contains Python venv with required packages
- Activate: `source instruments/bin/activate`
- Key packages: `pyserial`, `pyvisa`, `pyvisa-py`, `ctypes` (stdlib), `moku`

## File Organization & Key Locations
- Root-level device scripts: Production-ready device controllers
- `PMDevice.py`: Recommended wrapper for power meter access (better than raw TLPMX)
- `PM100USB.ipynb`: Start here for power meter troubleshooting
- `moku_phase_test_*.py`: Examples of networked instrument control

## Integration Points
- **Power Measurement**: Use `PMDevice.connect()` → `set_wavelength()` → `get_power()` sequence
- **Waveform Generation**: Import `DH1022.py` functions; use `set_waveform(inst, ch, wave, freq, ampl, offset)`
- **Laser Control**: Use `TLX_5.connect(port)` → `send_command()` for wavelength/power adjustments
- **Fiber Switch**: Use `BCB4Controller(port)` for channel routing
- **Phase Measurement**: See `moku_phase_test_*.py` for oscilloscope-based phase/amplitude measurements

## Common Troubleshooting
- **VISA Device Not Found**: Check USB cable, run `ResourceManager().list_resources()` to inspect all devices; verify device PIDs in TLPMX.py match hardware
- **Serial Port Timeout**: Increase `timeout` parameter in `serial.Serial()`; add `time.sleep(0.5)` after `connect()`
- **ctypes Library Load Failure**: Ensure 32/64-bit compatibility between Python interpreter and `.dll`/`.so`; check LD_LIBRARY_PATH on Linux
- **Power Reading Errors**: Always set wavelength before reading (`set_wavelength()` required for Thorlabs); check `set_autorange()` status
