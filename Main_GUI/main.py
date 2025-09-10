#!/usr/bin/env python3
import sys
import os

pattern_generator_dir = os.path.join(os.path.dirname(__file__), "pattern_generator")
sys.path.insert(0, pattern_generator_dir)

from pattern_generator.gui.haptic_pattern_gui import main

if __name__ == "__main__":
    main()