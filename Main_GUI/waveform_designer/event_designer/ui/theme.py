# theme.py
"""
Theme and styling utilities for the haptic waveform designer
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor

def apply_ultra_clean_theme(app: QApplication) -> None:
    """Apply the ultra clean theme palette to the application."""
    try: 
        app.setStyle("Fusion")
    except Exception: 
        pass
    
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#FAFBFC"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F8F9FA"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#1A202C"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1A202C"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1A202C"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#A0AEC0"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#4299E1"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#E53E3E"))
    app.setPalette(pal)

def load_ultra_clean_qss(app: QApplication) -> None:
    """Load the ultra clean stylesheet for the application."""
    qss = """
    QWidget { 
        font-size: 12.5pt; 
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif; 
    }
    
    QGroupBox { 
        border: 1px solid #E2E8F0; 
        border-radius: 10px; 
        margin-top: 14px; 
        padding: 12px; 
        background: #FFFFFF; 
    }
    
    QGroupBox::title { 
        subcontrol-origin: margin; 
        left: 10px; 
        padding: 0 6px; 
        color: #2D3748; 
        font-weight: 700; 
        font-size: 13pt; 
        background: #FFFFFF; 
    }
    
    QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        height: 34px; 
        border: 1px solid #E2E8F0; 
        border-radius: 8px; 
        padding: 0 10px; 
        background: #FFFFFF; 
        color: #1A202C; 
        font-size: 12pt; 
        font-weight: 500;
    }
    
    QPushButton { 
        font-weight: 600; 
    }
    
    QPushButton:hover { 
        background: #F7FAFC; 
        border-color: #4299E1; 
    }
    
    QPushButton:pressed { 
        background: #EDF2F7; 
    }
    
    QLabel { 
        color: #4A5568; 
        font-weight: 500; 
        font-size: 11.5pt; 
    }
    
    QListWidget, QTreeWidget, QTextEdit { 
        border: 1px solid #E2E8F0; 
        border-radius: 8px; 
        background: #FFFFFF; 
        padding: 8px; 
    }
    
    QTabWidget::pane { 
        border: 1px solid #E2E8F0; 
        border-radius: 10px; 
        background: #FFFFFF; 
    }
    
    QTabBar::tab { 
        padding: 10px 16px; 
        background: #F7FAFC; 
        color: #4A5568; 
        border: 1px solid #E2E8F0; 
        border-bottom: none;
        border-top-left-radius: 8px; 
        border-top-right-radius: 8px; 
        margin-right: 2px; 
    }
    
    QTabBar::tab:selected { 
        background: #FFFFFF; 
        color: #2D3748; 
        font-weight: 600; 
    }
    
    QSplitter::handle { 
        background: #E2E8F0; 
        width: 4px; 
        border-radius: 2px; 
    }
    """
    app.setStyleSheet(qss)