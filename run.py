#!/usr/bin/env python3
"""Convenience script to run the DigitalPet generator from the root directory."""
import sys
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from main import main

if __name__ == "__main__":
    main()
