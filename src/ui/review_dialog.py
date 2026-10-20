"""
Janela Executiva de Revisão e Exportação da Ata de Reunião
Permite ao usuário visualizar o progresso em tempo real, revisar e editar campos
da ata gerada pela IA e exportar o documento oficial em formato Microsoft Word (.docx).
"""

import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from PyQt6.QtCore import Qt, pyqtSignal, QThread
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
    QComboBox,
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

from src.config import OUTPUT_DIR, OLLAMA_URL, OLLAMA_MODEL, OLLAMA_KEEP_ALIVE
from src.minutes.parser import MinutesParser, MeetingMinutes, ActionItem
from src.minutes.ollama_client import OllamaClient
from src.minutes.prompts import generate_meeting_minutes_prompt
from src.minutes.generator import MinutesGenerator
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
        self._is_processing: bool = False

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

        # Aba 1: Editor da Ata Executiva / Resumo
        tab_minutes = QWidget()
        t1_layout = QVBoxLayout(tab_minutes)
        t1_layout.setSpacing(10)

        # Barra de seleção de formato do documento
        format_layout = QHBoxLayout()
        format_layout.setSpacing(8)
        lbl_format = QLabel("FORMATO DO DOCUMENTO:")
        lbl_format.setStyleSheet("color: #38BDF8; font-weight: bold;")
        format_layout.addWidget(lbl_format)

        self.combo_format = QComboBox(tab_minutes)
        self.combo_format.addItem("📄 Ata Executiva Completa (com Decisões e Plano de Ação)", "minutes")
        self.combo_format.addItem("📝 Resumo dos Temas Discutidos (Informativo / Sem Ações)", "theme_summary")
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        format_layout.addWidget(self.combo_format, 1)
        format_layout.addStretch()
        t1_layout.addLayout(format_layout)

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

        # Resumo Executivo / Visão Geral
        self.lbl_sec_summary = QLabel("1. RESUMO EXECUTIVO")
        t1_layout.addWidget(self.lbl_sec_summary)
        self.txt_summary = QTextEdit()
        self.txt_summary.setFixedHeight(70)
        t1_layout.addWidget(self.txt_summary)

        # Decisões Tomadas
        self.lbl_sec_decisions = QLabel("2. DECISÕES TOMADAS (UMA POR LINHA)")
        t1_layout.addWidget(self.lbl_sec_decisions)
        self.txt_decisions = QTextEdit()
        self.txt_decisions.setFixedHeight(65)
        t1_layout.addWidget(self.txt_decisions)

        # Matriz de Ações (Tabela Interativa)
        actions_header_layout = QHBoxLayout()
        self.lbl_sec_actions = QLabel("3. PLANO DE AÇÃO E RESPONSABILIDADES")
        actions_header_layout.addWidget(self.lbl_sec_actions)
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

        self.table_actions = QTableWidget(0, 4)
        self.table_actions.setHorizontalHeaderLabels(["Ação / Deliberação", "Responsável", "Prazo", "Evidência"])
        self.table_actions.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_actions.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_actions.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_actions.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_actions.setFixedHeight(120)
        self.table_actions.cellDoubleClicked.connect(self._on_action_double_clicked)
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

        self.btn_regenerate = QPushButton("✨ Gerar / Regenerar com IA", self)
        self.btn_regenerate.setObjectName("btnSecondary")
        self.btn_regenerate.clicked.connect(self._regenerate_minutes_with_ai)
        bottom_layout.addWidget(self.btn_regenerate)

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

    def set_processing_state(self, is_processing: bool, message: Optional[str] = None):
        """Bloqueia ou desbloqueia ações do usuário durante processamento de IA/pipeline."""
        self._is_processing = is_processing

        # Desabilita botões e seletores enquanto processa
        self.btn_export.setEnabled(not is_processing)
        self.btn_regenerate.setEnabled(not is_processing)
        self.btn_copy.setEnabled(not is_processing)
        self.combo_format.setEnabled(not is_processing)

        if is_processing:
            tip = "Aguarde o processamento em andamento para executar esta ação."
            self.btn_export.setToolTip(tip)
            self.btn_regenerate.setToolTip(tip)
            self.btn_copy.setToolTip(tip)
            self.combo_format.setToolTip(tip)
            if message:
                self.lbl_progress_status.setText(message)
        else:
            self.btn_export.setToolTip("")
            self.btn_regenerate.setToolTip("")
            self.btn_copy.setToolTip("")
            self.combo_format.setToolTip("")

    def append_stream_token(self, token: str):
        """Adiciona token gerado pelo Ollama na aba de streaming."""
        self.txt_streaming.moveCursor(self.txt_streaming.textCursor().MoveOperation.End)
        self.txt_streaming.insertPlainText(token)

    def _on_format_changed(self):
        """Atualiza a nomenclatura e elementos da interface conforme o formato selecionado."""
        is_theme = (self.combo_format.currentData() == "theme_summary")
        if is_theme:
            self.lbl_sec_summary.setText("1. VISÃO GERAL DA DISCUSSÃO")
            self.lbl_sec_decisions.setText("2. DELIBERAÇÕES MENCIONADAS (OPCIONAL NO RESUMO)")
            self.lbl_sec_actions.setText("3. AÇÕES MENCIONADAS (OPCIONAL NO RESUMO)")
            self.tabs.setTabText(0, "📝 Resumo de Temas")
            self.setWindowTitle("Revisão do Resumo Temático - Microsoft Teams")
            self.btn_export.setText("💾 Exportar Resumo para Word (.docx)")
        else:
            self.lbl_sec_summary.setText("1. RESUMO EXECUTIVO")
            self.lbl_sec_decisions.setText("2. DECISÕES TOMADAS (UMA POR LINHA)")
            self.lbl_sec_actions.setText("3. PLANO DE AÇÃO E RESPONSABILIDADES")
            self.tabs.setTabText(0, "📄 Ata Executiva")
            self.setWindowTitle("Revisão da Ata Executiva - Microsoft Teams")
            self.btn_export.setText("💾 Exportar para Microsoft Word (.docx)")

    def load_minutes(self, minutes: MeetingMinutes, transcript_text: str):
        """Preenche todos os campos com os dados estruturados da ata ou resumo."""
        self.set_processing_state(False)
        self.current_minutes = minutes
        self.transcript_text = transcript_text

        # Atualiza o combo de formato
        doc_type = getattr(minutes, "document_type", "minutes")
        idx = self.combo_format.findData(doc_type)
        if idx >= 0:
            self.combo_format.setCurrentIndex(idx)
        self._on_format_changed()

        default_title = "Resumo dos Temas Discutidos" if minutes.is_theme_summary else "Ata de Reunião Executiva"
        self.txt_title.setText(minutes.title or default_title)
        self.txt_date.setText(minutes.date or datetime.now().strftime("%d/%m/%Y"))
        self.txt_participants.setText(", ".join(minutes.participants) if minutes.participants else "")
        self.txt_summary.setPlainText(minutes.executive_summary)
        self.txt_decisions.setPlainText("\n".join(minutes.decisions))
        self.txt_transcript.setPlainText(transcript_text)

        # Preenche tabela de ações
        self.table_actions.setRowCount(0)
        for item in minutes.action_items:
            self._insert_action_row(item.action, item.owner, item.deadline, getattr(item, "evidence_ts", ""))

        # Seleciona a aba da ata
        self.tabs.setCurrentIndex(0)

    def _on_action_double_clicked(self, row: int, col: int):
        """Ao clicar duas vezes em uma ação, navega e salta para o ponto correspondente na transcrição."""
        evidence_item = self.table_actions.item(row, 3)
        act_item = self.table_actions.item(row, 0)
        ts = evidence_item.text().strip() if evidence_item else ""
        if not ts and act_item:
            m = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", act_item.text())
            if m:
                ts = m.group(1)

        if not ts:
            return

        # Alterna para a aba de transcrição
        self.tabs.setCurrentIndex(1)

        # Procura o timestamp no texto da transcrição
        doc = self.txt_transcript.document()
        cursor = doc.find(ts)
        if not cursor.isNull():
            self.txt_transcript.setTextCursor(cursor)
            self.txt_transcript.ensureCursorVisible()

    def _insert_action_row(self, action: str, owner: str, deadline: str, evidence_ts: str = ""):
        row = self.table_actions.rowCount()
        self.table_actions.insertRow(row)
        self.table_actions.setItem(row, 0, QTableWidgetItem(action))
        self.table_actions.setItem(row, 1, QTableWidgetItem(owner))
        self.table_actions.setItem(row, 2, QTableWidgetItem(deadline))
        item_ev = QTableWidgetItem(evidence_ts)
        item_ev.setToolTip("Clique duas vezes para navegar até a fala na transcrição")
        self.table_actions.setItem(row, 3, item_ev)

    def _add_action_row(self):
        self._insert_action_row("Nova ação a definir", "Responsável", "Prazo", "")

    def _remove_action_row(self):
        curr_row = self.table_actions.currentRow()
        if curr_row >= 0:
            self.table_actions.removeRow(curr_row)

    def _collect_edited_minutes(self) -> MeetingMinutes:
        """Coleta os dados editados pelo usuário na interface e retorna um MeetingMinutes atualizado."""
        doc_type = self.combo_format.currentData() or "minutes"
        default_title = "Resumo dos Temas Discutidos" if doc_type == "theme_summary" else "Ata de Reunião Executiva"

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
            evi_item = self.table_actions.item(r, 3)

            act = act_item.text().strip() if act_item else ""
            own = own_item.text().strip() if own_item else ""
            dea = dea_item.text().strip() if dea_item else ""
            evi = evi_item.text().strip() if evi_item else ""
            if act:
                action_items.append(ActionItem(action=act, owner=own, deadline=dea, evidence_ts=evi))

        # Tópicos mantidos da extração original se existirem
        topics = self.current_minutes.topics if self.current_minutes else []
        next_steps = self.current_minutes.next_steps if self.current_minutes else []

        return MeetingMinutes(
            title=self.txt_title.text().strip() or default_title,
            date=self.txt_date.text().strip() or datetime.now().strftime("%d/%m/%Y"),
            participants=participants,
            executive_summary=self.txt_summary.toPlainText().strip(),
            topics=topics,
            decisions=decisions,
            action_items=action_items,
            next_steps=next_steps,
            document_type=doc_type,
        )

    def _export_to_docx(self):
        """Gera o documento Word oficial com os dados da interface."""
        if self._is_processing:
            return

        minutes_to_export = self._collect_edited_minutes()

        has_content = bool(
            minutes_to_export.executive_summary.strip()
            or minutes_to_export.topics
            or minutes_to_export.decisions
        )

        if not has_content:
            reply = QMessageBox.question(
                self,
                "Documento sem Conteúdo",
                "O documento ainda não possui Resumo ou Tópicos preenchidos.\n\n"
                "Deseja gerar o conteúdo agora utilizando a IA local (Ollama)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._regenerate_minutes_with_ai()
                return
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        prefix = "Resumo_Temas" if minutes_to_export.is_theme_summary else "Ata"
        default_filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        default_filepath = OUTPUT_DIR / default_filename

        title_dialog = (
            "Salvar Resumo de Temas em Word (.docx)"
            if minutes_to_export.is_theme_summary
            else "Salvar Ata de Reunião em Word (.docx)"
        )

        filepath_str, _ = QFileDialog.getSaveFileName(
            self,
            title_dialog,
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

            doc_name = "Resumo Temático" if minutes_to_export.is_theme_summary else "Ata"
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(f"{doc_name} Exportado com Sucesso")
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

    def _regenerate_minutes_with_ai(self):
        """Regenera a ata ou resumo com IA a partir do texto presente na aba Transcrição."""
        if self._is_processing:
            return

        transcript = self.txt_transcript.toPlainText().strip()
        if not transcript:
            QMessageBox.warning(self, "Aviso", "Não há transcrição disponível para gerar o documento.")
            return

        client = OllamaClient()
        if not client.is_available():
            QMessageBox.critical(
                self,
                "Ollama Offline",
                f"O serviço do Ollama não está ativo em {OLLAMA_URL}.\n\n"
                f"Por favor, inicie o Ollama no Windows ou execute no terminal:\n"
                f"ollama run {OLLAMA_MODEL}"
            )
            return

        selected_format = self.combo_format.currentData() or "minutes"
        gen_label = "resumo temático" if selected_format == "theme_summary" else "ata executiva"

        self.set_processing_state(True, f"Conectando ao Ollama e gerando {gen_label}...")
        self.set_progress(f"Conectando ao Ollama e gerando {gen_label}...", 50)
        self.txt_streaming.clear()
        self.tabs.setCurrentIndex(2)

        class RegenerateWorker(QThread):
            token_received = pyqtSignal(str)
            progress_updated = pyqtSignal(str, int)
            finished_success = pyqtSignal(object)
            finished_error = pyqtSignal(str)

            def __init__(self, transcript_text: str, output_format: str = "minutes"):
                super().__init__()
                self.transcript_text = transcript_text
                self.output_format = output_format

            def run(self):
                try:
                    from src.config import get_typed_user_settings
                    user_settings = get_typed_user_settings()
                    user_speaker_name = user_settings.user_speaker_name

                    gen = MinutesGenerator()
                    minutes_obj, _ = gen.generate(
                        transcript_text=self.transcript_text,
                        user_speaker_name=user_speaker_name,
                        output_format=self.output_format,
                        progress_callback=lambda desc, pct: self.progress_updated.emit(desc, pct),
                        token_callback=lambda tok: self.token_received.emit(tok),
                    )
                    self.finished_success.emit(minutes_obj)
                except Exception as e:
                    self.finished_error.emit(str(e))

        self._regen_worker = RegenerateWorker(transcript, selected_format)
        self._regen_worker.token_received.connect(self.append_stream_token)
        self._regen_worker.progress_updated.connect(self.set_progress)

        def on_success(parsed_minutes):
            self.load_minutes(parsed_minutes, transcript)
            self.set_progress(f"{gen_label.capitalize()} sintetizado com sucesso pela IA!", 100)
            self.set_processing_state(False)
            self.tabs.setCurrentIndex(0)
            QMessageBox.information(self, "Sucesso", f"{gen_label.capitalize()} gerado e carregado com sucesso!")

        def on_error(err_msg):
            self.set_progress(f"Erro ao sintetizar com IA: {err_msg}", 0)
            self.set_processing_state(False)
            QMessageBox.critical(self, "Erro na Geração", f"Falha ao comunicar com Ollama:\n{err_msg}")

        self._regen_worker.finished_success.connect(on_success)
        self._regen_worker.finished_error.connect(on_error)
        self._regen_worker.start()

    def _copy_to_clipboard(self):
        """Copia o conteúdo estruturado para a área de transferência."""
        if self._is_processing:
            return
        minutes = self._collect_edited_minutes()
        if minutes.is_theme_summary:
            text_lines = [
                f"# {minutes.title}",
                f"Data: {minutes.date}",
                f"Participantes: {', '.join(minutes.participants)}",
                "",
                "## Visão Geral da Discussão",
                minutes.executive_summary,
                "",
            ]
            if minutes.topics:
                text_lines.append("## Temas Discutidos")
                for t in minutes.topics:
                    text_lines.append(f"### {t.get('topic', 'Tema')}")
                    if t.get("details"):
                        text_lines.append(t["details"])
                    text_lines.append("")
            if minutes.decisions:
                text_lines.append("## Deliberações Mencionadas")
                for d in minutes.decisions:
                    text_lines.append(f"- {d}")
                text_lines.append("")
            if minutes.action_items:
                text_lines.append("## Ações Mencionadas")
                for a in minutes.action_items:
                    text_lines.append(f"- {a.action} | Resp: {a.owner} | Prazo: {a.deadline}")
        else:
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
            QMessageBox.information(self, "Sucesso", "Texto copiado para a área de transferência!")

    def closeEvent(self, event):
        """Garante encerramento seguro de workers ao fechar a janela."""
        if hasattr(self, "_regen_worker") and self._regen_worker and self._regen_worker.isRunning():
            self._regen_worker.wait(1000)
        super().closeEvent(event)
