from datetime import datetime
from ctypes import (
    c_uint32,
    byref,
    create_string_buffer,
    c_bool,
    c_char_p,
    c_int,
    c_int16,
    c_double,
)
from TLPMX import TLPMX, TLPM_DEFAULT_CHANNEL
import time


class PMDevice:
    """Class wrapper for Thorlabs PMXXX power meter using TLPMX."""

    def __init__(self):
        self.device = TLPMX()
        self.resource_name = None
        self.connected = False
        self.unit = None
        self.AvgCount = 1

    # ----------------------------------------------------------------------
    def find_devices(self):
        """Returns a list of available resource names."""
        device_count = c_uint32()
        self.device.findRsrc(byref(device_count))

        print(f"Number of found devices: {device_count.value}\n")

        self.resources = create_string_buffer(1024)
        resources = []

        for i in range(device_count.value):
            self.device.getRsrcName(c_int(i), self.resources)
            name = c_char_p(self.resources.raw).value.decode()
            print(f"Resource name of device {i}: {name}\n")
            resources.append(name)
            self.device.close()

    # ----------------------------------------------------------------------
    def connect(self):
        """Connect to the specified device."""
        if self.connected:
            self.disconnect()
        self.device.open(self.resources, c_bool(True), c_bool(True))
        self.connected = True

        # status = self.device.open(resource_name, c_bool(True), c_bool(True))
        # if status != 0:
        #     raise RuntimeError(
        #         f"Failed to open device '{resource_name}'. "
        #         f"TLPMX.open() returned error {status}"
        #     )

        # self.connected = True
        # self.resource_name = resource_name

        # Read calibration message
        msg = create_string_buffer(1024)
        self.device.getCalibrationMsg(msg, TLPM_DEFAULT_CHANNEL)

        print(f"Device connected")
        print("Last calibration date:", c_char_p(msg.raw).value.decode(), "\n")

    # ----------------------------------------------------------------------
    def set_wavelength(self, wavelength_nm: float):
        wl = c_double(wavelength_nm)
        status = self.device.setWavelength(wl, TLPM_DEFAULT_CHANNEL)
        # print(f"Wavelength set to: {wavelength_nm} nm \n")
        if status != 0:
            raise RuntimeError(f"setWavelength failed: {status}")

    # # ----------------------------------------------------------------------
    def set_autorange(self, enable=True):
        v = 1 if enable else 0
        status = self.device.setPowerAutoRange(c_int16(v), TLPM_DEFAULT_CHANNEL)
        if status != 0:
            raise RuntimeError(f"setPowerAutoRange failed: {status}")

    # # ----------------------------------------------------------------------
    def set_unit(self, unit):
        if unit == "W":
            n = 0
            self.unit = "W"
            print(f"Units set to Watts")
        else:
            n = 1
            print(f"Units set to dBm")
            self.unit = "dBm"
        status = self.device.setPowerUnit(c_int16(n), TLPM_DEFAULT_CHANNEL)
        if status != 0:
            raise RuntimeError(f"setPowerUnit failed: {status}")
    #-------------------------------------------------------------------------
    def newTimeOut(self,value):
        val=value*1000
        status=self.device.setTimeoutValue(c_uint32(val))
        if status != 0:
            raise RuntimeError(f"setTimeoutValue failed: {status}")
        
        
    # ------------------------------------------------------------------------
    def SetAvMeasureTime(self, AvTime):
        AvTime_cd = c_double(AvTime)
        status = self.device.setAvgTime(AvTime_cd, TLPM_DEFAULT_CHANNEL)
        if status != 0:
            raise RuntimeError(f"setAvgTime failed: {status}")
        

    # ------------------------------------------------------------------------
    def SetAvMeasure(self, AvgCount):
        self.AvgCount = AvgCount
        status = self.device.setAvgCnt(c_int16(self.AvgCount), TLPM_DEFAULT_CHANNEL)
        if status != 0:
            raise RuntimeError(f"setAvgCnt failed: {status}")

    # # ----------------------------------------------------------------------
    def read_power(self) -> float:
        p = c_double()
        status = self.device.measPower(byref(p), TLPM_DEFAULT_CHANNEL)
        if status != 0:
            raise RuntimeError(f"measPower failed: {status}")
        return p.value

    # ----------------------------------------------------------------------

    def measure_series(self, count=5, interval=1.0):
        timestamps = []
        values = []

        for i in range(count):
            value = self.read_power()
            t = datetime.now()
            timestamps.append(t)
            values.append(value)
            units = self.unit
            print(f"{t} : {value} {units}")
            time.sleep(interval)

        print("")
        return timestamps, values

    # ----------------------------------------------------------------------
    def disconnect(self):
        if self.connected:
            self.device.close()
            self.connected = False
            print("Power meter disconnected.\n")


# ==========================================================================
# Example usage
# ==========================================================================

if __name__ == "__main__":
    pm = PMDevice()

    # 1. Find devices
    resources = pm.find_devices()

    # names=pm.names()

    # if not resources:
    #     print("No devices found.")
    #     exit()

    # print(resources[-1])
    # # 2. Connect to last device
    pm.connect()

    time.sleep(1)

    # # 3. Configure device
    pm.set_wavelength(900)
    pm.set_autorange(True)
    pm.set_unit_watt("W")

    # # # 4. Read 5 measurements
    pm.measure_series(count=5, interval=1)

    # # # 5. Disconnect
    # pm.disconnect()

    # # print("End program")
