"""Entry point used by PyInstaller (and handy for `python run_drift.py`)."""
from drift.app import main

if __name__ == "__main__":
    raise SystemExit(main())
