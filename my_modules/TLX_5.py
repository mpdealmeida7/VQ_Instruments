
import serial
import time
import sys

class TRL_5:
    
    def __init__(self):
        self.ser = None
        self.command = None

        self.laser_on = "LASer:ON: 1"
        self.laser_off = "LASer:ON: 0"
        self.laser_WL = None
        self.laser_power = "LASer:POWer?"
        self.laser_current_WL= "LASer:WAVElength?"
        


    
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
        WL="LASer:WAVElength:"+str(wl)
        return self.send_command(WL)
        #self.send_command(wavelength)
    #---------------------------------------------------------------------------
    def laser_current_wavelength(self):
        current_wavelength=self.send_command(self.laser_current_WL)
        print(f'Laser Wavelength={int(current_wavelength)/1000} nm')
    #---------------------------------------------------------------------------
    def power(self):
        power = self.send_command(self.laser_power)
        print(f'Power={float(power)/1000} dBm')
    #---------------------------------------------------------------------------
    def laser_OFF(self):
        return self.send_command(self.laser_off)
    
# -------------------------------------------------------------------------
if __name__ == "__main__":
    laser = TRL_5()
    
    port = 'COM4'
    laser.connect(port)

    laser.laser_ON()

    laser.change_WL('1570000')
    
    laser.laser_current_wavelength()
    
    laser.power()
    
    time.sleep(5.0)
    
    laser.laser_OFF()

