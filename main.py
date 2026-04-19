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

# Patterns that indicate the node/launcher is finished
COMPLETION_PATTERNS = [
    r'all processes on this machine have terminated',
    r'user interrupted the process',
]

# Known error patterns and what they usually mean
ROOT_CAUSE_MAP = {
    r'uvc_find_device: No such device': 'HARDWARE: Camera USB connection failed or permissions issue.',
    r'exit code -11': 'CRASH: Segmentation Fault (Memory corruption or driver incompatibility).',
    r'exit code -6': 'CRASH: Abort signal (likely an assertion failure).',
    r'ResourceNotFound': 'ENVIRONMENT: Missing ROS2 package or sourcing error.',
    r'lookupTransform': 'TRANSFORM: TF2 Buffer lookup failure (check your robot_state_publisher).',
    r'SEVERE WARNING!!! A namespace collision': 'NOISE: Duplicate plugin libraries (usually harmless).'
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

    def print_report(self, timed_out, return_code):
        print("\n" + "="*60)
        print("DIAGNOSTIC SUMMARY")
        print("="*60)

        if self.possible_root_causes:
            print("\n[!] IDENTIFIED ROOT CAUSES:")
            for i, cause in enumerate(set(self.possible_root_causes)): # Unique items
                print(f"{i+1}   - {cause}\n")
        
        if self.exit_detected:
            print("\n[!] CRASH CONTEXT (Last lines before failure):")
            for l in self.output_history:
                print(f"    >>> {l}")

        print(f"\n[STDOUT/STDERR] Errors: {len(self.errors)} | Warnings: {len(self.warnings)}")
        
        if return_code != 0 and return_code is not None:
            print(f"Launcher exited with code: {return_code}")
        
        print("="*60 + "\n")

def read_output(proc, debugger):
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

    thread = threading.Thread(target=read_output, args=(proc, debugger), daemon=True)
    thread.start()

    last_output_time = time.time()
    
    try:
        while proc.poll() is None:
            # Check if we should timeout (if no logs are flowing)
            # You can implement more complex timeout logic here if needed
            time.sleep(0.5)
    except KeyboardInterrupt:
        proc.terminate()

    proc.wait()
    debugger.print_report(False, proc.returncode)

if __name__ == "__main__":
    main()