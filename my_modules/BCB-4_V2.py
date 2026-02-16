
import serial
import time
from typing import Optional, Iterable


class BCB4Controller:
    """
    Controller for BCB-4 device over a serial port.

    Serial settings: 9600 8-N-1, no flow control, CR+LF termination.
    device_address: integer 0–9
    """

    def __init__(self, port: str, device_address: int = 1, timeout: float = 1.0):
        if not (0 <= device_address <= 9):
            raise ValueError("Device address must be 0–9.")
        self.device_address = device_address

        # Initialize serial port
        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE,
            parity=serial.PARITY_NONE,
            timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            write_timeout=timeout,
        )
        time.sleep(0.5)

    # --------------------------
    # Low-level I/O
    # --------------------------
    def send_cmd(self, cmd: str) -> str:
        """
        Send a command terminated with CR+LF and read a line response.
        Returns the response string with surrounding whitespace stripped.
        """
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port is not open.")

        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

        packet = (cmd + "\r\n").encode("ascii", errors="ignore")
        self.ser.write(packet)
        self.ser.flush()

        line = self.ser.readline().decode("ascii", errors="ignore").strip()
        return line

    # --------------------------
    # Device commands
    # --------------------------
    def set_device_address(self, new_address: int) -> str:
        if not (0 <= new_address <= 9):
            raise ValueError("Address must be 0–9.")
        cmd = f"SETADD:{new_address}"
        reply = self.send_cmd(cmd)
        self.device_address = new_address
        return reply

    def read_firmware(self) -> str:
        return self.send_cmd(f"RFW{self.device_address}")

    def reset_device(self) -> str:
        return self.send_cmd(f"RESET{self.device_address}")

    def set_bias_mode(self, mode: int) -> str:
        if mode not in range(1, 7):
            raise ValueError("Mode must be 1–6.")
        return self.send_cmd(f"SET{self.device_address}M:{mode}")

    def read_bias_voltage(self) -> str:
        return self.send_cmd(f"READ{self.device_address}V")

    def set_bias_voltage_MAX(self) -> str:
        return self.send_cmd(f"SET{self.device_address}V:00000")

    def read_Vpi(self) -> str:
        return self.send_cmd(f"READ{self.device_address}VPI")

    # --------------------------
    # Helpers / UI
    # --------------------------
    @staticmethod
    def _prompt_int(prompt: str,
                    valid: Optional[Iterable[int]] = None,
                    default: Optional[int] = None) -> int:
        valid_set = set(valid) if valid is not None else None
        while True:
            suffix = f" [default: {default}] " if default is not None else " "
            raw = input(f"{prompt}{suffix}").strip()
            if not raw and default is not None:
                return default
            try:
                val = int(raw)
                if valid_set is not None and val not in valid_set:
                    print(f"Please enter one of: {sorted(valid_set)}")
                    continue
                return val
            except ValueError:
                print("Please enter an integer.")

    @staticmethod
    def _countdown_wait(seconds: int) -> None:
        for s in range(seconds, 0, -1):
            print(f"\rStabilizing... {s}s remaining", end="", flush=True)
            time.sleep(1)
        print("\rStabilizing... done!            ")

    # --------------------------
    # Top-level interactive flow
    # --------------------------
    def run(self) -> None:
        """
        Interactive menu:
          1) Select bias mode and wait to stabilize (no reading)  -> WILL RESET
          2) Read Bias and Vpi voltages now                       -> NO RESET
        Always closes the serial device at the end.
        """
        try:
            print("\nChoose operation:")
            print("1) Select bias mode and wait to stabilize (no reading)")
            print("2) Read Bias and Vpi voltages now")
            choice = self._prompt_int("Enter 1 or 2:", valid={1, 2})

            V_coeff = (10.97 + 10.98) / 16384.0  # ADC scale factor

            if choice == 1:
                # Only reset for option 1
                try:
                    print("Resetting device:", self.reset_device())
                except Exception as e:
                    print(f"Warning: could not reset device ({e}). Continuing...")

                print("\nBias modes: Q+=1, Q-=2, MAX=3, Min=4, Manual w/out dither=5, Manual w/ dither=6")
                bias_mode = self._prompt_int(
                    "Select bias mode (1-6):",
                    valid={1, 2, 3, 4, 5, 6},
                    default=1
                )
                try:
                    result = self.set_bias_mode(bias_mode)
                    print(f"Setting Bias Mode to {bias_mode}: {result}")
                except Exception as e:
                    print(f"Error setting bias mode: {e}")
                    return

                t = self._prompt_int("Enter stabilization wait time in seconds:", default=90)
                print(f"Waiting for voltage to stabilize for {t} seconds...")
                self._countdown_wait(t)
                print("Stabilization complete. (No voltage reading performed.)")

            else:
                # Option 2: Read Bias and Vpi voltages now (no reset here)
                try:
                    raw_bias_str = self.read_bias_voltage().strip()
                    raw_bias_adc = float(raw_bias_str)
                    V_bias = 10.97 - (V_coeff * raw_bias_adc)
                    print(f"Bias Voltage: {round(V_bias, 3)} V")
                except Exception as e:
                    print(f"Error reading Bias Voltage: {e}")

                try:
                    raw_vpi_str = self.read_Vpi().strip()
                    raw_vpi_adc = float(raw_vpi_str)
                    V_pi = raw_vpi_adc * V_coeff
                    print(f"Vpi Voltage: {round(V_pi, 3)} V")
                except Exception as e:
                    print(f"Error reading Vpi Voltage: {e}")

                print("\nDone.")
        finally:
            try:
                self.close()
                print("Device connection closed.")
            except Exception as e:
                print(f"Warning: failed to close device cleanly ({e}).")

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()


if __name__ == "__main__":
    # Adjust the port for your system if needed:
    #   Windows: "COM5"
    #   Linux:   "/dev/ttyUSB0" or "/dev/ttyACM0"
    #   macOS:   "/dev/tty.usbserial-XXXX" or "/dev/tty.usbmodem-XXXX"
    dev = BCB4Controller("COM5", device_address=1, timeout=2.0)
    dev.run()
