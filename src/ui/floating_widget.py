"""
Widget Flutuante Always-On-Top para Controle de Gravação
Interface minimalista, sem bordas do sistema operacional (frameless), arrastável,
com botões de controle, cronômetro digital e mini VU meter dual (Mic / Teams).
Consumo de RAM mantido estritamente abaixo de 40 MB.
"""

import time
from typing import Optional, Tuple
from enum import Enum

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFont

from src.audio.recorder import DualAudioRecorder


class RecorderState(Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"
    PROCESSING = "PROCESSING"


class DualVUMeterWidget(QWidget):
    """Mini VU Meter compacto com 2 canais (Mic e Teams) desenhado via QPainter."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(60, 24)
        self.mic_level = 0.0      # 0.0 a 1.0
        self.teams_level = 0.0    # 0.0 a 1.0

    def set_levels(self, mic: float, teams: float):
        self.mic_level = max(0.0, min(1.0, mic))
        self.teams_level = max(0.0, min(1.0, teams))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fundo do VU meter
        painter.setBrush(QBrush(QColor("#0F111A")))
        painter.setPen(QPen(QColor("#2B3042"), 1))
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 4, 4)

        # Canal 1: Microfone (Você) - Barra Superior (Verde/Azul)
        mic_width = int((self.width() - 8) * self.mic_level)
        if mic_width > 0:
            painter.setBrush(QBrush(QColor("#2ECC71")))  # Verde esmeralda
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(4, 4, mic_width, 6, 2, 2)

        # Canal 2: Teams (Participantes) - Barra Inferior (Azul Aço)
        teams_width = int((self.width() - 8) * self.teams_level)
        if teams_width > 0:
            painter.setBrush(QBrush(QColor("#3498DB")))  # Azul
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(4, 14, teams_width, 6, 2, 2)


class FloatingWidget(QWidget):
    """
    Barra Flutuante Always-on-Top minimalista para Teams.
    """

    # Sinais de eventos para orquestração
    start_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    minimize_tray_requested = pyqtSignal()

    def __init__(
        self,
        recorder: Optional[DualAudioRecorder] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.recorder = recorder
        self.state = RecorderState.IDLE
        self._drag_pos = QPoint()

        # Configurações de Janela: Sem moldura, fica no topo de tudo
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._init_ui()
        self._setup_timer()

    def _init_ui(self):
        # Container Principal com Borda Estilizada e Cantos Arredondados
        self.main_container = QFrame(self)
        self.main_container.setObjectName("mainContainer")
        self.main_container.setStyleSheet(
            """
            #mainContainer {
                background-color: #1A1D27;
                border: 1px solid #2E75B6;
                border-radius: 10px;
            }
            QLabel {
                color: #FFFFFF;
                font-family: 'Segoe UI', Calibri, sans-serif;
            }
            QPushButton {
                border-radius: 6px;
                font-family: 'Segoe UI', Calibri, sans-serif;
                font-weight: bold;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton#btnRecord {
                background-color: #27AE60;
                color: #FFFFFF;
                border: 1px solid #2ECC71;
            }
            QPushButton#btnRecord:hover {
                background-color: #2ECC71;
            }
            QPushButton#btnPause {
                background-color: #D35400;
                color: #FFFFFF;
                border: 1px solid #E67E22;
            }
            QPushButton#btnPause:hover {
                background-color: #E67E22;
            }
            QPushButton#btnStop {
                background-color: #C0392B;
                color: #FFFFFF;
                border: 1px solid #E74C3C;
            }
            QPushButton#btnStop:hover {
                background-color: #E74C3C;
            }
            QPushButton#btnStop:disabled {
                background-color: #3A3F50;
                border: 1px solid #4B5267;
                color: #7B849C;
            }
            QPushButton#btnMinimize {
                background-color: transparent;
                color: #A0AEC0;
                border: none;
                font-size: 14px;
                padding: 0 4px;
            }
            QPushButton#btnMinimize:hover {
                color: #FFFFFF;
            }
            """
        )

        layout = QHBoxLayout(self.main_container)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # 1. Ícone de Arraste (Grip)
        self.lbl_grip = QLabel("⋮⋮", self.main_container)
        self.lbl_grip.setStyleSheet("color: #718096; font-size: 14px; cursor: sizeall;")
        self.lbl_grip.setToolTip("Clique e arraste para reposicionar a barra flutuante")
        layout.addWidget(self.lbl_grip)

        # 2. Status e Timer
        status_box = QVBoxLayout()
        status_box.setSpacing(1)

        self.lbl_status = QLabel("PRONTO", self.main_container)
        self.lbl_status.setStyleSheet("font-size: 9px; font-weight: bold; color: #2E75B6;")

        self.lbl_timer = QLabel("00:00:00", self.main_container)
        font_timer = QFont("Consolas", 12, QFont.Weight.Bold)
        self.lbl_timer.setFont(font_timer)
        self.lbl_timer.setStyleSheet("color: #F7FAFC;")

        status_box.addWidget(self.lbl_status)
        status_box.addWidget(self.lbl_timer)
        layout.addLayout(status_box)

        # 3. Mini Dual VU Meter
        self.vu_meter = DualVUMeterWidget(self.main_container)
        self.vu_meter.setToolTip("Nível de Áudio: Superior = Microfone | Inferior = Participantes (Teams)")
        layout.addWidget(self.vu_meter)

        # 4. Botão Gravar / Pausar
        self.btn_record = QPushButton("● Gravar", self.main_container)
        self.btn_record.setObjectName("btnRecord")
        self.btn_record.clicked.connect(self._on_record_clicked)
        layout.addWidget(self.btn_record)

        # 5. Botão Parar e Gerar Ata
        self.btn_stop = QPushButton("■ Parar", self.main_container)
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self.btn_stop)

        # 6. Botão Minimizar para a bandeja
        self.btn_minimize = QPushButton("🗕", self.main_container)
        self.btn_minimize.setObjectName("btnMinimize")
        self.btn_minimize.setToolTip("Minimizar para a Bandeja do Sistema")
        self.btn_minimize.clicked.connect(self._on_minimize_clicked)
        layout.addWidget(self.btn_minimize)

        # Layout da Janela
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.main_container)

        self.adjustSize()

    def _setup_timer(self):
        """Timer para atualização periódica de áudio e cronômetro."""
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(80)  # 12.5 FPS de atualização leve
        self.update_timer.timeout.connect(self._on_tick)

    def _on_tick(self):
        if not self.recorder:
            return

        # Atualiza cronômetro
        if self.state in (RecorderState.RECORDING, RecorderState.PAUSED):
            elapsed = self.recorder.get_elapsed_seconds()
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self.lbl_timer.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

        # Atualiza VU meter se gravando
        if self.state == RecorderState.RECORDING:
            mic_lvl, loop_lvl = self.recorder.get_audio_levels()
            self.vu_meter.set_levels(mic_lvl, loop_lvl)
        else:
            self.vu_meter.set_levels(0.0, 0.0)

    def _on_record_clicked(self):
        if self.state == RecorderState.IDLE:
            self.set_state(RecorderState.RECORDING)
            self.start_requested.emit()
        elif self.state == RecorderState.RECORDING:
            self.set_state(RecorderState.PAUSED)
            self.pause_requested.emit()
        elif self.state == RecorderState.PAUSED:
            self.set_state(RecorderState.RECORDING)
            self.resume_requested.emit()

    def _on_stop_clicked(self):
        if self.state in (RecorderState.RECORDING, RecorderState.PAUSED):
            self.set_state(RecorderState.PROCESSING)
            self.stop_requested.emit()

    def _on_minimize_clicked(self):
        self.minimize_tray_requested.emit()

    def set_state(self, state: RecorderState):
        """Atualiza a interface conforme o estado da aplicação."""
        self.state = state

        if state == RecorderState.IDLE:
            self.lbl_status.setText("PRONTO")
            self.lbl_status.setStyleSheet("font-size: 9px; font-weight: bold; color: #2E75B6;")
            self.lbl_timer.setText("00:00:00")
            self.btn_record.setText("● Gravar")
            self.btn_record.setObjectName("btnRecord")
            self.btn_record.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.update_timer.stop()
            self.vu_meter.set_levels(0.0, 0.0)

        elif state == RecorderState.RECORDING:
            self.lbl_status.setText("● GRAVANDO")
            self.lbl_status.setStyleSheet("font-size: 9px; font-weight: bold; color: #E74C3C;")
            self.btn_record.setText("❚❚ Pausar")
            self.btn_record.setObjectName("btnPause")
            self.btn_record.setEnabled(True)
            self.btn_stop.setEnabled(True)
            if not self.update_timer.isActive():
                self.update_timer.start()

        elif state == RecorderState.PAUSED:
            self.lbl_status.setText("❚❚ PAUSADO")
            self.lbl_status.setStyleSheet("font-size: 9px; font-weight: bold; color: #F39C12;")
            self.btn_record.setText("▶ Retomar")
            self.btn_record.setObjectName("btnRecord")
            self.btn_record.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self.vu_meter.set_levels(0.0, 0.0)

        elif state == RecorderState.PROCESSING:
            self.lbl_status.setText("⚙ PROCESSANDO ATA...")
            self.lbl_status.setStyleSheet("font-size: 9px; font-weight: bold; color: #9B59B6;")
            self.btn_record.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.update_timer.stop()
            self.vu_meter.set_levels(0.0, 0.0)

        # Força reaplicação de estilo QSS
        self.btn_record.style().unpolish(self.btn_record)
        self.btn_record.style().polish(self.btn_record)
        self.btn_stop.style().unpolish(self.btn_stop)
        self.btn_stop.style().polish(self.btn_stop)

    # Suporte a Arrastar e Soltar (Draggable Window)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
