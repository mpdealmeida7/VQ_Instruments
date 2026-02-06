
import serial
import time
import sys

class TRL_5:
    
    def __init__(self):
        self.ser = None
        self.command = None

        self.laser_on = "LASer:ON: 1"
        self.laser_off = "LASer:ON: 0"
        self.laser_WL = "LASer:WAVElength: "
        self.laser_power = "LASer:POWer?"
    
    #-------------------------------------------------------------
    def connect(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        """Connect to the Thorlabs TLX5 laser."""
        try:
            self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
            time.sleep(0.5)
            return self.ser
        except serial.SerialException as e:
            raise ConnectionError(f"Failed to connect to TLX5 on {port}: {e}")

    #-----------------------------------------------------------------------------
    def send_command(self, command: str):
        ser = self.ser
        if not ser or not ser.is_open:
            raise ConnectionError("Serial port is not open.")

        cmd = command.strip() + "\n"

        try:
            ser.write(cmd.encode('ascii'))
            time.sleep(0.05)
            response = ser.readline().decode('ascii', errors='ignore').strip()
            return response
        except serial.SerialTimeoutException:
            print("Write timeout occurred.")
            return None
        except serial.SerialException as e:
            print(f"Serial communication error: {e}")
            return None

    #---------------------------------------------------------------------------
    def laser_ON(self):
        return self.send_command(self.laser_on)
    #---------------------------------------------------------------------------
    def change_WL(self,wl):
        wl=wl*1000
        wls=str(wl)
        wavelength=self.laser_WL+wl
        self.send_command(wavelength)
    #---------------------------------------------------------------------------
    #---------------------------------------------------------------------------
    def laser_OFF(self):
        return self.send_command(self.laser_off)


# -------------------------------------------------------------------------
if __name__ == "__main__":
    laser = TRL_5()
    
    port = 'COM4'
    laser.connect(port)

    laser.laser_ON()
    
    laser.change_WL('1600')
    
    time.sleep(5.0)
    
    #laser.laser_OFF()

