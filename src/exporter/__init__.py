"""
Módulo de Exportação de Atas em Formato Microsoft Word (.docx)
"""

from src.exporter.docx_builder import DocxMeetingMinutesBuilder
from src.exporter.styles import CorporatePalette, DocumentStyles

__all__ = [
    "DocxMeetingMinutesBuilder",
    "CorporatePalette",
    "DocumentStyles",
]
