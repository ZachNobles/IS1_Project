#!/usr/bin/env python3

import sys
import subprocess
import re

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

    while True:
        line = proc.stdout.readline()
        if not line:
            break
        output_lines.append(line.strip())
        print(line.strip())  # Print in real-time

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

    print(f"\nCommand exited with code: {proc.returncode}")

if __name__ == "__main__":
    main()