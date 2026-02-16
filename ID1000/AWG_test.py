import pyvisa, time
VISA = "USB0::0x1AB1::0x0646::DG9R280300043::INSTR"   # adjust
rm = pyvisa.ResourceManager()
inst = rm.open_resource(VISA, timeout=10000)
print(inst.query("*IDN?"))
inst.write("*RST;*CLS")
inst.write(":SOUR2:APPL:SQU 1e6,2,1")   # 1 MHz, 2 Vpp, +1 V offset
inst.write(":OUTP2:LOAD 50")
inst.write(":OUTP2 ON")
time.sleep(2)
print("SOUR2:APPL? ->", inst.query(":SOUR1:APPL?"))
print("SYST:ERR?   ->", inst.query(":SYST:ERR?"))
input("Look at the scope; press Enter to turn OFF...")
inst.write(":OUTP2 OFF")
inst.close()