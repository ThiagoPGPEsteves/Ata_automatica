"""
Estilos e Identidade Visual Corporativa para Documentos Word (.docx)
Define paleta executiva (Azul Marinho #1F4E79, Cinza Escuro #262626),
tipografia padronizada e utilitários XML para tabelas zebradas e caixas de destaque.
"""

from dataclasses import dataclass
from docx.shared import RGBColor, Pt, Inches
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn


@dataclass(frozen=True)
class CorporatePalette:
    """Paleta de cores sóbria e moderna para atas corporativas."""
    NAVY: RGBColor = RGBColor(31, 78, 121)          # #1F4E79 - Títulos e cabeçalhos
    STEEL_BLUE: RGBColor = RGBColor(46, 117, 182)   # #2E75B6 - Subtítulos e bordas
    TEXT_DARK: RGBColor = RGBColor(38, 38, 38)      # #262626 - Corpo de texto
    TEXT_MUTED: RGBColor = RGBColor(115, 115, 115)  # #737373 - Metadados e rodapé
    WHITE: RGBColor = RGBColor(255, 255, 255)       # #FFFFFF - Texto em cabeçalhos escuros

    # Cores Hexadecimais para Shading XML
    HEX_NAVY: str = "1F4E79"
    HEX_STEEL_BLUE: str = "2E75B6"
    HEX_LIGHT_BG: str = "F2F4F8"
    HEX_DECISION_BG: str = "EBF3FA"
    HEX_DECISION_BORDER: str = "2E75B6"
    HEX_TABLE_HEADER: str = "1F4E79"
    HEX_ZEBRA_EVEN: str = "FFFFFF"
    HEX_ZEBRA_ODD: str = "F8FAFC"


@dataclass(frozen=True)
class DocumentStyles:
    """Configurações tipográficas padrão."""
    FONT_FAMILY: str = "Calibri"
    TITLE_SIZE: Pt = Pt(20)
    SECTION_SIZE: Pt = Pt(13)
    SUBSECTION_SIZE: Pt = Pt(11)
    BODY_SIZE: Pt = Pt(10)
    TABLE_SIZE: Pt = Pt(9.5)
    FOOTER_SIZE: Pt = Pt(8.5)

    PAGE_MARGIN: Inches = Inches(1.0)  # Margens de 2.54 cm


def set_cell_background(cell, hex_color: str):
    """Define a cor de fundo (shading) de uma célula de tabela no Word."""
    tcPr = cell._tc.get_or_add_tcPr()
    # Remove sombreamento anterior se existir
    for child in list(tcPr):
        if child.tag.endswith("shd"):
            tcPr.remove(child)
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top: int = 120, bottom: int = 120, left: int = 160, right: int = 160):
    """Define o espaçamento interno (padding em dxa) de uma célula."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)


def set_callout_border(cell, hex_border_color: str = CorporatePalette.HEX_DECISION_BORDER):
    """Cria uma borda esquerda espessa e estilizada (estilo callout box)."""
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="none"/>'
        f'<w:left w:val="single" w:sz="36" w:space="0" w:color="{hex_border_color}"/>'
        f'<w:bottom w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)


def set_table_borders(table, hex_border_color: str = "D3D3D3"):
    """Aplica bordas suaves e discretas na tabela."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{hex_border_color}"/>'
        f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="{CorporatePalette.HEX_NAVY}"/>'
        f'<w:left w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{hex_border_color}"/>'
        f'<w:insideV w:val="none"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)
