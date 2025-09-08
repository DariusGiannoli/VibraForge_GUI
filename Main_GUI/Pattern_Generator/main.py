#!/usr/bin/env python3
"""
Main entry point for Pattern Generator
"""
import sys
import os

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from gui.haptic_pattern_gui import main
    main()