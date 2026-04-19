#!/usr/bin/env python3

import sys
import subprocess
import re
import time

# Configuration
TIMEOUT_SECONDS = 30  # No output for this long = possible loop/stuck

# ROS2 completion patterns
COMPLETION_PATTERNS = [
    r'Exiting',
    r'Shutting down',
    r'Done',
    r'process has finished',
    r'Respawning',
    r'KeyboardInterrupt',
    r'Shutting down completed',
]

def is_completion(line):
    """Check if line indicates normal completion."""
    return any(re.search(p, line, re.IGNORECASE) for p in COMPLETION_PATTERNS)

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <ros2 command>")
        print("Example: python main.py ros2 launch package thing.py")
        sys.exit(1)

    command = sys.argv[1:]
    print(f"Running command: {' '.join(command)}")
    print("Monitoring for bugs...\n")

    # run the command and capture output
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output_lines = []
    errors = []
    warnings = []
    last_output_time = time.time()
    timed_out = False

    while True:
        line = proc.stdout.readline()
        
        # Check for timeout (no output for TIMEOUT_SECONDS)
        current_time = time.time()
        time_since_last = current_time - last_output_time
        
        # Show countdown when idle
        if time_since_last > 5 and not line:
            remaining = TIMEOUT_SECONDS - int(time_since_last)
            if remaining > 0:
                print(f"\r[WAITING] Timeout in {remaining}s...", end='', flush=True)
        
        if time_since_last > TIMEOUT_SECONDS:
            print(f"\n[WARNING] No output for {TIMEOUT_SECONDS} seconds - possible loop or stuck process")
            timed_out = True
            break
        
        if not line:
            break
        
        # Clear the countdown line when we get output
        if time_since_last > 5:
            print()  # New line after countdown
        
        last_output_time = current_time
        output_lines.append(line.strip())
        print(line.strip())  # Print in real-time

        # Check for completion
        if is_completion(line):
            print(f"\n[INFO] Detected completion signal: {line.strip()}")

        # common ROS2 issues
        if re.search(r'\bERROR\b', line, re.IGNORECASE):
            errors.append(line.strip())
        elif re.search(r'\bWARNING\b', line, re.IGNORECASE):
            warnings.append(line.strip())
        # patterns for ROS2 specific errors
        elif 'Failed to create' in line:
            errors.append(line.strip())
        elif 'Exception' in line:
            errors.append(line.strip())

    proc.wait()

    print("\n" + "="*50)
    print("Debug report")
    print("="*50)

    if timed_out:
        print(f"\n[RESULT] Process timed out after {TIMEOUT_SECONDS}s with no output")
        print("  Possible causes: infinite loop, deadlock, or waiting for input")
    else:
        print(f"\n[RESULT] Process completed normally")

    if errors:
        print(f"\nFound {len(errors)} errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("\nNo errors detected.")

    if warnings:
        print(f"\nFound {len(warnings)} warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("\nNo warnings detected.")

    if not timed_out:
        print(f"\nCommand exited with code: {proc.returncode}")

if __name__ == "__main__":
    main()