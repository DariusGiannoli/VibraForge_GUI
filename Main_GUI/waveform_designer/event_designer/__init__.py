"""
Event Designer Package
Contains the event data model and universal event designer.
"""

from .event_data_model import HapticEvent, EventCategory, WaveformData
from .universal_event_designer import UniversalEventDesigner

__all__ = ['HapticEvent', 'EventCategory', 'WaveformData', 'UniversalEventDesigner']