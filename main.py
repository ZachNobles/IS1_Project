#!/usr/bin/env python3

import sys
import subprocess
import re
import time
import threading
import queue

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

def read_output_thread(proc, output_queue, done_event):
    """Background thread to read output without blocking."""
    try:
        for line in iter(proc.stdout.readline, ''):
            output_queue.put(line)
        done_event.set()
    except Exception as e:
        output_queue.put(f"[ERROR] Reader thread: {e}")
        done_event.set()

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <ros2 command>")
        print("Example: python main.py ros2 launch package thing.py")
        sys.exit(1)

    command = sys.argv[1:]
    print(f"Running command: {' '.join(command)}")
    print("Monitoring for bugs...\n")

    # run the command and capture output
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    output_lines = []
    errors = []
    warnings = []
    last_output_time = time.time()
    timed_out = False
    
    # Queue for thread-safe output reading
    output_queue = queue.Queue()
    done_event = threading.Event()
    
    # Start background thread to read output
    reader_thread = threading.Thread(target=read_output_thread, args=(proc, output_queue, done_event), daemon=True)
    reader_thread.start()

    while True:
        # Check for available output (non-blocking)
        try:
            line = output_queue.get_nowait()
            last_output_time = time.time()
        except queue.Empty:
            line = None

        # Check for timeout
        current_time = time.time()
        time_since_last = current_time - last_output_time
        
        # Show countdown when idle
        if time_since_last > 5 and line is None:
            remaining = TIMEOUT_SECONDS - int(time_since_last)
            if remaining > 0:
                print(f"\r[WAITING] Timeout in {remaining}s...", end='', flush=True)
            else:
                print(f"\n[WARNING] No output for {TIMEOUT_SECONDS} seconds - possible loop or stuck process")
                timed_out = True
                break
        
        if line is None:
            # Check if process ended
            if done_event.is_set() and output_queue.empty():
                break
            time.sleep(0.1)  # Small sleep to avoid busy-waiting
            continue
        
        # Clear the countdown line when we get output
        if time_since_last > 5:
            print()  # New line after countdown
        
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