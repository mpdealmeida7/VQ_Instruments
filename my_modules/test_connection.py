#!/usr/bin/env python3
"""
Connection Test Script for Rigol MHO-984
=========================================
This script tests your PyVISA installation and helps you find your oscilloscope.
"""

import sys


def test_imports():
    """Test if all required packages are installed"""
    print("=" * 70)
    print("Testing Python Package Installation")
    print("=" * 70)
    print()
    
    packages = {
        'pyvisa': 'PyVISA',
        'numpy': 'NumPy',
        'matplotlib': 'Matplotlib',
        'pandas': 'Pandas'
    }
    
    all_installed = True
    
    for package, name in packages.items():
        try:
            module = __import__(package)
            version = getattr(module, '__version__', 'unknown')
            print(f"✓ {name:20s} version {version}")
        except ImportError:
            print(f"✗ {name:20s} NOT INSTALLED")
            all_installed = False
    
    print()
    
    if not all_installed:
        print("❌ Some packages are missing!")
        print("\nInstall missing packages with:")
        print("  pip install pyvisa pyvisa-py numpy matplotlib pandas")
        return False
    else:
        print("✓ All required packages are installed!")
        return True


def test_pyvisa_backends():
    """Test available PyVISA backends"""
    print()
    print("=" * 70)
    print("Testing PyVISA Backends")
    print("=" * 70)
    print()
    
    import pyvisa
    
    backends = ['@py', '@ivi', '@sim']
    working_backends = []
    
    for backend in backends:
        try:
            rm = pyvisa.ResourceManager(backend)
            print(f"✓ Backend '{backend}' is available")
            working_backends.append(backend)
        except Exception as e:
            print(f"✗ Backend '{backend}' failed: {e}")
    
    print()
    
    if working_backends:
        print(f"✓ Found {len(working_backends)} working backend(s)")
        return working_backends[0]  # Return first working backend
    else:
        print("❌ No working backends found!")
        print("\nInstall pyvisa-py with:")
        print("  pip install pyvisa-py")
        return None


def list_resources(backend):
    """List all available VISA resources"""
    print()
    print("=" * 70)
    print("Scanning for VISA Resources")
    print("=" * 70)
    print()
    
    import pyvisa
    
    try:
        rm = pyvisa.ResourceManager(backend)
        resources = rm.list_resources()
        
        if not resources:
            print("⚠ No VISA resources found")
            print("\nPossible reasons:")
            print("  1. Oscilloscope is not powered on")
            print("  2. USB/Ethernet cable is not connected")
            print("  3. USB drivers are not installed (Windows)")
            print("  4. Permission issues (Linux - see README for udev rules)")
            return []
        
        print(f"Found {len(resources)} resource(s):\n")
        
        rigol_devices = []
        
        for i, resource in enumerate(resources, 1):
            print(f"{i}. {resource}")
            
            # Try to identify the device
            try:
                inst = rm.open_resource(resource, timeout=5000)
                idn = inst.query('*IDN?').strip()
                print(f"   → {idn}")
                
                if 'RIGOL' in idn.upper() or 'MHO' in idn.upper():
                    rigol_devices.append((resource, idn))
                    print(f"   ✓ This is a Rigol device!")
                
                inst.close()
            except Exception as e:
                print(f"   ⚠ Could not identify: {e}")
            
            print()
        
        return rigol_devices
        
    except Exception as e:
        print(f"❌ Error scanning resources: {e}")
        return []


def test_connection(resource_string):
    """Test connection to a specific resource"""
    print()
    print("=" * 70)
    print("Testing Connection to Oscilloscope")
    print("=" * 70)
    print()
    
    import pyvisa
    
    try:
        rm = pyvisa.ResourceManager('@py')
        scope = rm.open_resource(resource_string, timeout=10000)
        
        print(f"✓ Connected to: {resource_string}\n")
        
        # Get identification
        idn = scope.query('*IDN?').strip()
        print(f"Device ID: {idn}\n")
        
        # Test basic commands
        print("Testing basic SCPI commands...")
        
        # Get channel 1 status
        ch1_status = scope.query(':CHAN1:DISP?').strip()
        print(f"  Channel 1 Status: {ch1_status}")
        
        # Get timebase
        timebase = scope.query(':TIM:SCAL?').strip()
        print(f"  Timebase Scale: {timebase} s/div")
        
        # Get trigger status
        trig_status = scope.query(':TRIG:STAT?').strip()
        print(f"  Trigger Status: {trig_status}")
        
        print("\n✓ All basic commands working!")
        
        scope.close()
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def main():
    """Main test routine"""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "Rigol MHO-984 Connection Test" + " " * 24 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    
    # Test 1: Check imports
    if not test_imports():
        print("\n❌ Please install required packages first!")
        sys.exit(1)
    
    # Test 2: Check PyVISA backends
    backend = test_pyvisa_backends()
    if not backend:
        print("\n❌ No working PyVISA backend found!")
        sys.exit(1)
    
    # Test 3: List resources
    rigol_devices = list_resources(backend)
    
    if not rigol_devices:
        print()
        print("=" * 70)
        print("Connection Test Result")
        print("=" * 70)
        print()
        print("⚠ No Rigol oscilloscopes detected")
        print()
        print("Next steps:")
        print("  1. Verify oscilloscope is powered on")
        print("  2. Check USB/Ethernet connection")
        print("  3. For USB on Linux, you may need udev rules (see README)")
        print("  4. For Ethernet, verify IP address and LXI is enabled")
        print()
        sys.exit(1)
    
    # Test 4: Test connection to first Rigol device
    resource_string, idn = rigol_devices[0]
    
    if test_connection(resource_string):
        print()
        print("=" * 70)
        print("✓ SUCCESS! Connection Test Passed")
        print("=" * 70)
        print()
        print("Your oscilloscope is ready to use!")
        print()
        print("Quick start:")
        print(f"  python simple_example.py")
        print()
        print("Or in your code:")
        print(f"  from rigol_mho984_data_acquisition import RigolMHO984")
        print(f"  scope = RigolMHO984('{resource_string}')")
        print()
    else:
        print()
        print("=" * 70)
        print("❌ Connection test failed")
        print("=" * 70)
        print()
        print("Please check:")
        print("  1. Oscilloscope is not in remote lock mode")
        print("  2. No other software is using the oscilloscope")
        print("  3. Firmware is up to date")
        print()


if __name__ == "__main__":
    main()
