"""
Módulo de Exportação de Atas em Formato Microsoft Word (.docx)
"""

from src.exporter.docx_builder import DocxMeetingMinutesBuilder
from src.exporter.styles import CorporatePalette, DocumentStyles
from src.exporter.outlook_dispatcher import OutlookDispatcher

__all__ = [
    "DocxMeetingMinutesBuilder",
    "CorporatePalette",
    "DocumentStyles",
    "OutlookDispatcher",
]
