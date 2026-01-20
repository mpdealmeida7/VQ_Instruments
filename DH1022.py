import pyvisa

import time

rm = (
    pyvisa.ResourceManager()
)  # or ResourceManager('@py') to force the pure Python backend
# print(rm.list_resources())

# usb_resources = rm.list_resources("USB?*INSTR")
# print(usb_resources)

inst = rm.open_resource("USB0::0x1AB1::0x0642::DG1ZA231701902::INSTR")


# Optional: speed it up
inst.timeout = 5000  # ms
inst.write_termination = "\n"
inst.read_termination = "\n"

# Identify
print(inst.query("*IDN?"))


def set_waveform(
    inst, ch: int, wave: str, freq_hz: float, ampl_vpp: float, offset_v: float = 0.0
):
    """
    wave: 'SIN', 'SQU', 'RAMP', 'PULSE', 'NOIS', 'ARB', 'DC'
    """
    assert ch in (1, 2)
    cmd = f":SOURce{ch}:APPLy:{wave} {freq_hz},{ampl_vpp},{offset_v}"
    inst.write(cmd)
    inst.query("*OPC?")  # wait until applied


def ch_on(inst, ch: int):
    cmd = f":OUTP{ch} ON"
    inst.write(cmd)


def ch_off(inst, ch: int):
    cmd = f":OUTP{ch} OFF"
    inst.write(cmd)


# Set Load
def set_load(inst, ch: int, load: str):
    """
    Load: "50" or "INF
    """
    if load == "50":
        cmd = f":OUTP{ch}:LOAD 50"
    else:
        cmd = f":OUTP{ch}:LOAD INF"
    inst.write(cmd)


# Set Phase
def set_phase_deg(inst, ch: int, phase_deg: float):
    assert ch in (1, 2)
    inst.write(f":SOURce{ch}:PHAS {phase_deg}")
    inst.query("*OPC?")


# Sync Phase
def sunc_phase(inst, ch: int):
    cmd = f":SORce{ch}:PHAS:SYNC"
    inst.write(cmd)
    inst.query("*OPC?")


# Examples:
freq1 = 100_000.0

freq2 = 100_000.0

ch_on(inst, 1)
ch_on(inst, 2)

set_phase_deg(inst, 2, 25.0)

set_load(inst, 1, "50")
set_load(inst, 2, "50")


set_waveform(inst, 1, "SIN", freq1, 2.0, 0.0)  # set ch1 freq, Vpp and offset
set_waveform(inst, 2, "SIN", freq2, 2.0, 0.0)  #  set ch2 freq, Vpp and offset


# time.sleep(60)

# # Enable outputs
# ch_off(inst,1)
# ch_off(inst,2)
