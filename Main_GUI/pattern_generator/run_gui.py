#!/usr/bin/env python3
"""
Script de lancement pour l'interface GUI du générateur de patterns haptiques
"""
import sys
import os

# Ajouter les répertoires nécessaires au PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))  # pattern_generator
gui_dir = os.path.join(current_dir, 'gui')               # pattern_generator/gui
main_gui_dir = os.path.dirname(current_dir)              # Main_GUI

# Ajouter gui_dir en premier pour les imports directs des modules gui
if gui_dir not in sys.path:
    sys.path.insert(0, gui_dir)

# Ajouter main_gui_dir pour waveform_designer et autres
if main_gui_dir not in sys.path:
    sys.path.insert(0, main_gui_dir)

if __name__ == "__main__":
    try:
        from gui.main_gui import main
        main()
    except ImportError:
        # Fallback si les imports relatifs ne marchent pas
        from main_gui import main
        main()