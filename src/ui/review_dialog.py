"""
Janela Executiva de Revisão e Exportação da Ata de Reunião
Permite ao usuário visualizar o progresso em tempo real, revisar e editar campos
da ata gerada pela IA e exportar o documento oficial em formato Microsoft Word (.docx).
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QTabWidget,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QMessageBox,
    QFileDialog,
    QApplication,
    QGroupBox,
    QFormLayout,
)
from PyQt6.QtGui import QFont

from src.config import OUTPUT_DIR
from src.minutes.parser import MeetingMinutes, ActionItem
from src.exporter.docx_builder import DocxMeetingMinutesBuilder


class ReviewDialog(QDialog):
    """
    Janela moderna para revisão pós-reunião e exportação para Word.
    """

    export_completed = pyqtSignal(str)  # Caminho do arquivo .docx gerado

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Revisão da Ata Executiva - Microsoft Teams")
        self.resize(900, 680)
        self.setMinimumSize(750, 500)

        self.current_minutes: Optional[MeetingMinutes] = None
        self.transcript_text: str = ""
        self.last_exported_path: Optional[Path] = None

        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(
            """
            QDialog {
                background-color: #1A1D27;
                color: #FFFFFF;
                font-family: 'Segoe UI', Calibri, sans-serif;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 11px;
                font-weight: bold;
            }
            QLineEdit, QTextEdit {
                background-color: #242938;
                color: #F8FAFC;
                border: 1px solid #3B4252;
                border-radius: 5px;
                padding: 6px;
                font-size: 12px;
                selection-background-color: #2E75B6;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #2E75B6;
            }
            QTabWidget::pane {
                border: 1px solid #2E75B6;
                border-radius: 6px;
                background-color: #1F2430;
                padding: 8px;
            }
            QTabBar::tab {
                background: #161922;
                color: #A0AEC0;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1F2430;
                color: #FFFFFF;
                border-top: 2px solid #2E75B6;
            }
            QTableWidget {
                background-color: #242938;
                color: #F8FAFC;
                gridline-color: #3B4252;
                border: 1px solid #3B4252;
                border-radius: 5px;
            }
            QHeaderView::section {
                background-color: #1F4E79;
                color: #FFFFFF;
                font-weight: bold;
                padding: 5px;
                border: 1px solid #2E75B6;
            }
            QProgressBar {
                border: 1px solid #3B4252;
                border-radius: 6px;
                background-color: #161922;
                text-align: center;
                color: #FFFFFF;
                font-weight: bold;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #2E75B6;
                border-radius: 5px;
            }
            QPushButton {
                background-color: #2E75B6;
                color: #FFFFFF;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #3584CC;
            }
            QPushButton#btnExport {
                background-color: #1F4E79;
                border: 1px solid #2E75B6;
                font-size: 13px;
                padding: 10px 20px;
            }
            QPushButton#btnExport:hover {
                background-color: #276299;
            }
            QPushButton#btnSecondary {
                background-color: #2D3748;
                border: 1px solid #4A5568;
            }
            QPushButton#btnSecondary:hover {
                background-color: #4A5568;
            }
            """
        )

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Barra de Progresso Superior (ativa durante IA)
        self.progress_container = QWidget(self)
        p_layout = QVBoxLayout(self.progress_container)
        p_layout.setContentsMargins(0, 0, 0, 0)
        p_layout.setSpacing(4)

        self.lbl_progress_status = QLabel("Aguardando processamento...", self.progress_container)
        self.lbl_progress_status.setStyleSheet("color: #38BDF8; font-size: 12px;")
        self.progress_bar = QProgressBar(self.progress_container)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        p_layout.addWidget(self.lbl_progress_status)
        p_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.progress_container)

        # 2. Navegador por Abas
        self.tabs = QTabWidget(self)

        # Aba 1: Editor da Ata Executiva
        tab_minutes = QWidget()
        t1_layout = QVBoxLayout(tab_minutes)
        t1_layout.setSpacing(10)

        # Metadados rápidos
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(10)

        v_title = QVBoxLayout()
        v_title.addWidget(QLabel("TÍTULO DA REUNIÃO"))
        self.txt_title = QLineEdit()
        self.txt_title.setPlaceholderText("Ex: Alinhamento de Sprint e Arquitetura")
        v_title.addWidget(self.txt_title)
        meta_layout.addLayout(v_title, 3)

        v_date = QVBoxLayout()
        v_date.addWidget(QLabel("DATA"))
        self.txt_date = QLineEdit()
        self.txt_date.setText(datetime.now().strftime("%d/%m/%Y"))
        v_date.addWidget(self.txt_date)
        meta_layout.addLayout(v_date, 1)

        v_parts = QVBoxLayout()
        v_parts.addWidget(QLabel("PARTICIPANTES (SEPARADOS POR VÍRGULA)"))
        self.txt_participants = QLineEdit()
        self.txt_participants.setPlaceholderText("Ex: Thiago Esteves, Equipe de TI")
        v_parts.addWidget(self.txt_participants)
        meta_layout.addLayout(v_parts, 3)

        t1_layout.addLayout(meta_layout)

        # Resumo Executivo
        t1_layout.addWidget(QLabel("1. RESUMO EXECUTIVO"))
        self.txt_summary = QTextEdit()
        self.txt_summary.setFixedHeight(70)
        t1_layout.addWidget(self.txt_summary)

        # Decisões Tomadas
        t1_layout.addWidget(QLabel("2. DECISÕES TOMADAS (UMA POR LINHA)"))
        self.txt_decisions = QTextEdit()
        self.txt_decisions.setFixedHeight(65)
        t1_layout.addWidget(self.txt_decisions)

        # Matriz de Ações (Tabela Interativa)
        actions_header_layout = QHBoxLayout()
        actions_header_layout.addWidget(QLabel("3. PLANO DE AÇÃO E RESPONSABILIDADES"))
        actions_header_layout.addStretch()

        self.btn_add_action = QPushButton("+ Adicionar Ação", tab_minutes)
        self.btn_add_action.setObjectName("btnSecondary")
        self.btn_add_action.clicked.connect(self._add_action_row)
        actions_header_layout.addWidget(self.btn_add_action)

        self.btn_remove_action = QPushButton("- Remover Ação", tab_minutes)
        self.btn_remove_action.setObjectName("btnSecondary")
        self.btn_remove_action.clicked.connect(self._remove_action_row)
        actions_header_layout.addWidget(self.btn_remove_action)

        t1_layout.addLayout(actions_header_layout)

        self.table_actions = QTableWidget(0, 3)
        self.table_actions.setHorizontalHeaderLabels(["Ação / Deliberação", "Responsável", "Prazo"])
        self.table_actions.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_actions.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_actions.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_actions.setFixedHeight(120)
        t1_layout.addWidget(self.table_actions)

        self.tabs.addTab(tab_minutes, "📄 Ata Executiva")

        # Aba 2: Diálogo Transcrito
        tab_transcript = QWidget()
        t2_layout = QVBoxLayout(tab_transcript)
        t2_layout.addWidget(QLabel("DIÁLOGO COMPLETO DA REUNIÃO (SINCRONIZADO POR TIMESTAMPS)"))
        self.txt_transcript = QTextEdit()
        self.txt_transcript.setReadOnly(True)
        self.txt_transcript.setFont(QFont("Consolas", 10))
        t2_layout.addWidget(self.txt_transcript)
        self.tabs.addTab(tab_transcript, "🎙️ Transcrição Completa")

        # Aba 3: Streaming da IA / Logs
        tab_logs = QWidget()
        t3_layout = QVBoxLayout(tab_logs)
        t3_layout.addWidget(QLabel("GERAÇÃO EM TEMPO REAL DO MODELO (LLM STREAMING)"))
        self.txt_streaming = QTextEdit()
        self.txt_streaming.setReadOnly(True)
        self.txt_streaming.setFont(QFont("Consolas", 9))
        t3_layout.addWidget(self.txt_streaming)
        self.tabs.addTab(tab_logs, "⚙️ Streaming / Logs")

        main_layout.addWidget(self.tabs)

        # 3. Barra Inferior de Ações
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.btn_copy = QPushButton("📋 Copiar Texto", self)
        self.btn_copy.setObjectName("btnSecondary")
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        bottom_layout.addWidget(self.btn_copy)

        bottom_layout.addStretch()

        self.btn_close = QPushButton("Fechar", self)
        self.btn_close.setObjectName("btnSecondary")
        self.btn_close.clicked.connect(self.close)
        bottom_layout.addWidget(self.btn_close)

        self.btn_export = QPushButton("💾 Exportar para Microsoft Word (.docx)", self)
        self.btn_export.setObjectName("btnExport")
        self.btn_export.clicked.connect(self._export_to_docx)
        bottom_layout.addWidget(self.btn_export)

        main_layout.addLayout(bottom_layout)

    def set_progress(self, message: str, percent: int):
        """Atualiza a barra de progresso e mensagem de status."""
        self.lbl_progress_status.setText(message)
        self.progress_bar.setValue(percent)
        if percent >= 100:
            self.lbl_progress_status.setStyleSheet("color: #4ADE80; font-weight: bold;")
        else:
            self.lbl_progress_status.setStyleSheet("color: #38BDF8; font-weight: bold;")

    def append_stream_token(self, token: str):
        """Adiciona token gerado pelo Ollama na aba de streaming."""
        self.txt_streaming.moveCursor(self.txt_streaming.textCursor().MoveOperation.End)
        self.txt_streaming.insertPlainText(token)

    def load_minutes(self, minutes: MeetingMinutes, transcript_text: str):
        """Preenche todos os campos com os dados estruturados da ata."""
        self.current_minutes = minutes
        self.transcript_text = transcript_text

        self.txt_title.setText(minutes.title or "Ata de Reunião Executiva")
        self.txt_date.setText(minutes.date or datetime.now().strftime("%d/%m/%Y"))
        self.txt_participants.setText(", ".join(minutes.participants) if minutes.participants else "")
        self.txt_summary.setPlainText(minutes.executive_summary)
        self.txt_decisions.setPlainText("\n".join(minutes.decisions))
        self.txt_transcript.setPlainText(transcript_text)

        # Preenche tabela de ações
        self.table_actions.setRowCount(0)
        for item in minutes.action_items:
            self._insert_action_row(item.action, item.owner, item.deadline)

        # Seleciona a aba da ata
        self.tabs.setCurrentIndex(0)

    def _insert_action_row(self, action: str, owner: str, deadline: str):
        row = self.table_actions.rowCount()
        self.table_actions.insertRow(row)
        self.table_actions.setItem(row, 0, QTableWidgetItem(action))
        self.table_actions.setItem(row, 1, QTableWidgetItem(owner))
        self.table_actions.setItem(row, 2, QTableWidgetItem(deadline))

    def _add_action_row(self):
        self._insert_action_row("Nova ação a definir", "Responsável", "Prazo")

    def _remove_action_row(self):
        curr_row = self.table_actions.currentRow()
        if curr_row >= 0:
            self.table_actions.removeRow(curr_row)

    def _collect_edited_minutes(self) -> MeetingMinutes:
        """Coleta os dados editados pelo usuário na interface e retorna um MeetingMinutes atualizado."""
        # Participantes
        raw_parts = self.txt_participants.text().split(",")
        participants = [p.strip() for p in raw_parts if p.strip()]

        # Decisões
        raw_decs = self.txt_decisions.toPlainText().splitlines()
        decisions = [d.strip() for d in raw_decs if d.strip()]

        # Matriz de Ações
        action_items: List[ActionItem] = []
        for r in range(self.table_actions.rowCount()):
            act_item = self.table_actions.item(r, 0)
            own_item = self.table_actions.item(r, 1)
            dea_item = self.table_actions.item(r, 2)

            act = act_item.text().strip() if act_item else ""
            own = own_item.text().strip() if own_item else ""
            dea = dea_item.text().strip() if dea_item else ""
            if act:
                action_items.append(ActionItem(action=act, owner=own, deadline=dea))

        # Tópicos mantidos da extração original se existirem
        topics = self.current_minutes.topics if self.current_minutes else []
        next_steps = self.current_minutes.next_steps if self.current_minutes else []

        return MeetingMinutes(
            title=self.txt_title.text().strip() or "Ata de Reunião Executiva",
            date=self.txt_date.text().strip() or datetime.now().strftime("%d/%m/%Y"),
            participants=participants,
            executive_summary=self.txt_summary.toPlainText().strip(),
            topics=topics,
            decisions=decisions,
            action_items=action_items,
            next_steps=next_steps,
        )

    def _export_to_docx(self):
        """Gera o documento Word oficial com os dados da interface."""
        minutes_to_export = self._collect_edited_minutes()

        default_filename = f"Ata_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        default_filepath = OUTPUT_DIR / default_filename

        filepath_str, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Ata de Reunião em Word (.docx)",
            str(default_filepath),
            "Documentos Microsoft Word (*.docx)",
        )

        if not filepath_str:
            return

        out_path = Path(filepath_str)
        try:
            builder = DocxMeetingMinutesBuilder()
            builder.build(minutes_to_export, out_path)
            self.last_exported_path = out_path

            # Notifica e abre o arquivo
            self.export_completed.emit(str(out_path))

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Ata Exportada com Sucesso")
            msg_box.setText(f"O documento Word foi gerado com sucesso:\n\n{out_path.name}")
            btn_open = msg_box.addButton("Abrir no Word", QMessageBox.ButtonRole.ActionRole)
            btn_ok = msg_box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            msg_box.exec()

            if msg_box.clickedButton() == btn_open:
                try:
                    os.startfile(str(out_path.resolve()))
                except Exception as ex:
                    QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o Word: {ex}")

        except Exception as err:
            QMessageBox.critical(self, "Erro na Exportação", f"Falha ao gerar documento Word:\n{err}")

    def _copy_to_clipboard(self):
        """Copia o conteúdo estruturado da ata para a área de transferência."""
        minutes = self._collect_edited_minutes()
        text_lines = [
            f"# {minutes.title}",
            f"Data: {minutes.date}",
            f"Participantes: {', '.join(minutes.participants)}",
            "",
            "## Resumo Executivo",
            minutes.executive_summary,
            "",
            "## Decisões Tomadas",
        ]
        for d in minutes.decisions:
            text_lines.append(f"- {d}")
        text_lines.append("")
        text_lines.append("## Matriz de Ações")
        for a in minutes.action_items:
            text_lines.append(f"- {a.action} | Resp: {a.owner} | Prazo: {a.deadline}")

        full_text = "\n".join(text_lines)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(full_text)
            QMessageBox.information(self, "Sucesso", "Texto da ata copiado para a área de transferência!")
