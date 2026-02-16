
import pyvisa
try:
    rm = pyvisa.ResourceManager()          # default backend
    resources = rm.list_resources()
    print("Default backend resources:", resources)
except Exception as e:
    print("Default backend failed:", e)

try:
    rm_py = pyvisa.ResourceManager('@py')  # pure Python backend
    resources_py = rm_py.list_resources()
    print("@py backend resources:", resources_py)
except Exception as e:
    print("@py backend failed:", e)
