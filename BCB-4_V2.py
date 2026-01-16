import serial
import time

class BCB4Controller:
    def __init__(self, port: str, device_address: int = 1, timeout: float = 1.0):
        """
        Initialize serial connection.
        Settings: 9600 8-N-1, no flow control, CR+LF termination
        device_address: integer 0–9
        """
        if not (0 <= device_address <= 9):
            raise ValueError("Device address must be 0–9.")
        self.device_address = device_address

        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE,
            parity=serial.PARITY_NONE,
            timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )
        time.sleep(0.5)

    def send_cmd(self, cmd: str) -> str:
        """
        Send a command with CR+LF and read response.
        """
        packet = (cmd + "\r\n").encode("ascii")  # CR+LF
        self.ser.write(packet)
        time.sleep(0.1)
        return self.ser.readline().decode(errors="ignore").strip()

    # ----------------------------
    # Device commands (all include address)
    # ----------------------------

    def set_device_address(self, new_address: int):
        """
        SETADD:X : Set device address (0–9)
        """
        if not (0 <= new_address <= 9):
            raise ValueError("Address must be 0–9.")
        cmd = f"SETADD:{new_address}"
        reply = self.send_cmd(cmd)
        self.device_address = new_address
        return reply

    def read_firmware(self):
        """
        RFW[ADDR] : Read firmware version
        """
        return self.send_cmd(f"RFW{self.device_address}")

    def reset_device(self):
        """
        RESET[ADDR] : Reset device
        """
        return self.send_cmd(f"RESET{self.device_address}")

    def set_bias_mode(self, mode: int):
        """
        SET[ADDR]M:X : Set bias mode (1–6)
        """
        if mode not in range(1, 7):
            raise ValueError("Mode must be 1–6.")
        return self.send_cmd(f"SET{self.device_address}M:{mode}")

    def read_bias_voltage(self):
        """
        READ[ADDR]V : Read bias voltage
        """
        return self.send_cmd(f"READ{self.device_address}V")
    
    def set_bias_voltage_MAX(self):
        """
        SET[ADDR]V:00000 : Set bias voltage to MAX
        """
        return self.send_cmd(f"SET{self.device_address}V:00000")
    
    
    
    

    def close(self):
        if self.ser.is_open:
            self.ser.close()


if __name__ == "__main__":
    dev = BCB4Controller("COM5", device_address=1, timeout=2.0)

    # Optional: change device address to 2
    # print("Setting device address to 2:", dev.set_device_address(2))
    
    #print firmware version
    print("Firmware:", dev.read_firmware()) #print firmware version

    ##reset device
    #print("Resetting device:", dev.reset_device()) 


    #Set Bias mode Q+=1, Q-=2, MAX=3, Min=4
    print("Setting bias mode to MIN (4):", dev.set_bias_mode(2))

    #Sleep
    t=3*60 #3 minutes
    print(f'Wating for voltate to stabilize for {t} seconds...')
    time.sleep(3*60)

    #Read and print Bias Voltage
    print("Bias Voltage:", dev.read_bias_voltage())
    
    #Read Bisas Voltate
    print("Bias Voltage:", dev.read_bias_voltage())

    #Set Bias Voltate to MAX
    #print("Bias Voltage MAX",dev.set_bias_voltage_MAX())

    dev.close()
