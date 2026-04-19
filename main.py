#!/usr/bin/env python3

import sys
import subprocess
import re
import time
import threading
import queue
from collections import deque

# Configuration
TIMEOUT_SECONDS = 20
CONTEXT_SIZE = 10  # Number of lines to keep before a crash

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
PURPLE = "\033[35m"
RESET = "\033[0m"

# Patterns that indicate the node/launcher is finished
COMPLETION_PATTERNS = [
    r'all processes on this machine have terminated',
    r'user interrupted the process',
]

# Known error patterns and what they usually mean
ROOT_CAUSE_MAP = {
    r'exit code -11': 'CRASH: Segmentation Fault (Memory corruption or driver incompatibility).',
    r'exit code -6': 'CRASH: Abort signal (likely an assertion failure).',
    r'ResourceNotFound': 'ENVIRONMENT: Missing ROS2 package or sourcing error.',
    r'lookupTransform': 'TRANSFORM: TF2 Buffer lookup failure (check your robot_state_publisher).',
    
    # Networking & DDS
    r'incompatible QoS': 'COMMUNICATION: Publisher and Subscriber have mismatched Quality of Service settings.',
    r'RTPS_READER.*matched': 'DDS: Discovery issue. Nodes see each other but cannot handshake.',
    r'multicast_join': 'NETWORK: DDS cannot join multicast group. Check firewall/VPN/Network Interface.',

    # Hardware & Permissions
    r'uvc_find_device: No such device': 'HARDWARE: Camera USB connection failed or permissions issue.',
    r'Permission denied.*ttyUSB': 'PERMISSIONS: Cannot access Serial port. Run: sudo usermod -a -G dialout $USER',
    r'could not open port': 'HARDWARE: Controller/Sensor unplugged or wrong /dev/ port specified.',
    r'out of memory.*buffer': 'USB: Bus bandwidth exceeded. Lower the camera resolution or FPS.',

    # Lifecycle & Logic
    r'taking too long to execute': 'PERFORMANCE: Callback hung or loop rate too high for CPU.',
    r'use_sim_time': 'CLOCK: Potential mismatch between real-time and simulation-time.',
    r'cannot create a publisher on topic': 'NAMING: Invalid topic name (check for illegal characters or double slashes).',

    # Noise (To be filtered out)
    r'Optimization Guide': 'NOISE: Standard library optimization suggestion.',
    r'deprecated': 'NOISE: Using old API calls; usually not the cause of a crash.'
}

class ROS2Debugger:
    def __init__(self):
        self.output_history = deque(maxlen=CONTEXT_SIZE)
        self.errors = []
        self.warnings = []
        self.possible_root_causes = []
        self.exit_detected = False

    def analyze_line(self, line):
        clean_line = line.strip()
        if not clean_line:
            return

        self.output_history.append(clean_line)

        # 1. Identify Root Causes using Regex
        for pattern, description in ROOT_CAUSE_MAP.items():
            if re.search(pattern, clean_line):
                # Don't add noisy warnings to the root cause list
                if "NOISE" not in description:
                    self.possible_root_causes.append(f"{description} -> '{clean_line}'")

        # 2. Categorize Logs
        if '[ERROR]' in clean_line or 'ERROR:' in clean_line:
            self.errors.append(clean_line)
        elif '[WARN]' in clean_line or 'Warning:' in clean_line:
            # Filter out the specific noise you saw in your log
            if 'namespace collision' not in clean_line:
                self.warnings.append(clean_line)

        # 3. Detect Crash/Death
        if 'process has died' in clean_line or 'process has finished' in clean_line:
            self.exit_detected = True
    
    def shorten_ros_line(self, line):
        if 'process has died' in line and len(line) > 200:
            # Look for the start of the command and the end remappings
            # We look for the first instance of --params-file to cut it off
            try:
                # Keep up to the start of parameters
                start_marker = line.find('--params-file')
                # Keep from the last remapping
                end_marker = line.rfind('-r /')
                
                if start_marker != -1 and end_marker != -1:
                    header = line[:start_marker]
                    footer = line[end_marker:]
                    count = line.count('--params-file')
                    return f"{header} {PURPLE}... [TRUNCATED {count} PARAMS] ...{RESET} {footer}"
            except Exception:
                pass # Fall back to basic truncation if logic fails
                
            return line[:150] + f" {PURPLE}... [TRUNCATED SOME PARAMS] ...{RESET}"
            
        return line

    def print_report(self, timed_out, return_code):
        print(f"\n{CYAN}" + "="*60)
        print("DIAGNOSTIC SUMMARY")
        print("="*60 + f"{RESET}")

        if self.possible_root_causes:
            print(f"\n{GREEN}[!] IDENTIFIED ROOT CAUSES:{RESET}")
            for i, cause in enumerate(set(self.possible_root_causes)): # Unique items
                print(f"{i+1}   - {cause}\n")
        
        if self.exit_detected:
            print(f"\n{RED}[!] CRASH CONTEXT (Last lines before failure):{RESET}")
            for l in self.output_history:
                print(f"    >>> {self.shorten_ros_line(l)}")

        print(f"\n[STDOUT/STDERR] Errors: {len(self.errors)} | Warnings: {len(self.warnings)}")
        
        if timed_out:
            print(f"\n{YELLOW}[!] TIMEOUT: Process was terminated after inactivity.{RESET}")
        
        if return_code != 0 and return_code is not None:
            print(f"Launcher exited with code: {return_code}")
        
        print("="*60 + "\n")

def read_output(proc, debugger, last_output_time_ref):
    last_line = ""
    max_width = 120  # Maximum line width to display
    for line in iter(proc.stdout.readline, ''):
        last_line = line.strip()
        if len(last_line) > max_width:
            last_line = last_line[:max_width]
        # Pad with spaces to clear any leftover characters from longer previous lines
        padded_line = last_line.ljust(max_width)
        print(f"\r{padded_line}", end="", flush=True)
        debugger.analyze_line(line)
        last_output_time_ref[0] = time.time()  # Update last output time
    print()  # Final newline after the loop ends

def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_ros.py <ros2 command>")
        sys.exit(1)

    command = sys.argv[1:]
    debugger = ROS2Debugger()

    print(f"Monitoring: {' '.join(command)}\n")

    proc = subprocess.Popen(
        command, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT, 
        text=True, 
        bufsize=1
    )

    last_output_time_ref = [time.time()]
    thread = threading.Thread(target=read_output, args=(proc, debugger, last_output_time_ref), daemon=True)
    thread.start()

    last_displayed_second = -1
    timed_out = False
    
    try:
        while proc.poll() is None:
            elapsed = time.time() - last_output_time_ref[0]
            remaining = int(TIMEOUT_SECONDS - elapsed)
            
            if remaining <= (TIMEOUT_SECONDS - 5) and remaining != last_displayed_second and remaining >= 0:
                print(f"\rtiming out in {remaining} seconds", end="", flush=True)
                last_displayed_second = remaining
            
            if remaining <= 0:
                print("\nTimeout reached. Terminating process.")
                proc.terminate()
                timed_out = True
                break
            
            time.sleep(0.5)
    except KeyboardInterrupt:
        proc.terminate()

    proc.wait()
    debugger.print_report(timed_out, proc.returncode)

if __name__ == "__main__":
    main()