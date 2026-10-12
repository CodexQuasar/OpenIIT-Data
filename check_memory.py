import os
import sys

print("Python executable:", sys.executable)
print("Platform:", sys.platform)
print("Argv:", sys.argv)

# Try to get memory info without psutil
try:
    with open('/proc/self/status', 'r') as f:
        for line in f:
            if line.startswith('Vm'):
                print(f"  {line.strip()}")
except:
    print("Could not read /proc/self/status (not Linux)")

# Check if we can find the backend process
try:
    import subprocess
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe'], 
                          capture_output=True, text=True, timeout=5)
    # Find our backend pids
    pids = [line.split()[1] for line in result.stdout.split('\n')[4:] if 'python' in line.lower()]
    print(f"Python processes found: {pids}")
except Exception as e:
    print(f"Could not list processes: {e}")