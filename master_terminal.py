#!/usr/bin/env python3
"""
Master Terminal — Orchestrates all scanners sequentially.
"""

import subprocess
import sys
import os
import time
from datetime import datetime

SCRIPTS = [
    "run_scanner.py"
]


def check_dependencies():
    try:
        import pandas
        import numpy
        import yfinance
        return True
    except ImportError as e:
        print(f"\n  [!] Missing dependency: {e.name}")
        print("  Run: pip install -r requirements.txt")
        return False


def run_script(script_name):
    print(f"\n{'='*60}")
    print(f"  STARTING: {script_name}")
    print(f"  Time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    try:
        process = subprocess.Popen(
            [sys.executable, script_name],
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True
        )
        process.wait()

        if process.returncode == 0:
            print(f"\n  {script_name} completed successfully.")
        else:
            print(f"\n  {script_name} failed with return code {process.returncode}.")

    except Exception as e:
        print(f"\n  Unexpected error running {script_name}: {e}")


def main():
    if not check_dependencies():
        sys.exit(1)

    start_total = time.time()

    print("\n" + "#" * 70)
    print("#" + " " * 24 + "MASTER TRADING TERMINAL" + " " * 23 + "#")
    print("#" + " " * 17 + "Running All Institutional Scanners" + " " * 18 + "#")
    print("#" * 70)

    for script in SCRIPTS:
        if os.path.exists(script):
            run_script(script)
        else:
            print(f"\n  Skipping: {script} (File not found)")

    end_total = time.time()
    duration = end_total - start_total

    print("\n" + "#" * 70)
    print("  ALL SCANS COMPLETE!")
    print(f"  Total Execution Time: {duration/60:.2f} minutes")
    print("  Check your folder for updated Excel reports.")
    print("#" * 70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Master Terminal stopped by user.")
        sys.exit(0)
