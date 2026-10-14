"""
Ícone na Bandeja do Sistema (Windows System Tray)
Fornece controle em segundo plano, menu de contexto e notificações nativas.
Gera ícones dinamicamente via QPixmap/QPainter eliminando dependência de arquivos externos.
"""

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen, QAction

from src.config import OUTPUT_DIR
from src.ui.floating_widget import RecorderState


def create_tray_icon(color_hex: str = "#1F4E79") -> QIcon:
    """Desenho vetorial de ícone circular moderno para a bandeja do sistema."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Círculo base
    painter.setBrush(QBrush(QColor(color_hex)))
    painter.setPen(QPen(QColor("#FFFFFF"), 1))
    painter.drawEllipse(2, 2, 28, 28)

    # Símbolo interno (Letra 'A' de Ata)
    painter.setPen(QPen(QColor("#FFFFFF"), 2))
    font = painter.font()
    font.setPixelSize(16)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "A")

    painter.end()
    return QIcon(pixmap)


class AtaSystemTrayIcon(QSystemTrayIcon):
    """
    Ícone de bandeja com menu de contexto e controle global.
    """

    start_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    show_widget_requested = pyqtSignal()
    open_output_dir_requested = pyqtSignal()
    exit_requested = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.state = RecorderState.IDLE

        self.icon_idle = create_tray_icon("#1F4E79")      # Azul Marinho
        self.icon_recording = create_tray_icon("#E74C3C") # Vermelho Gravação
        self.icon_paused = create_tray_icon("#F39C12")    # Âmbar Pausa
        self.icon_processing = create_tray_icon("#8E44AD")# Roxo Processamento

        self.setIcon(self.icon_idle)
        self.setToolTip("Ata Automática - Reuniões Teams")

        self._init_menu()
        self.activated.connect(self._on_activated)

    def _init_menu(self):
        self.menu = QMenu()
        self.menu.setStyleSheet(
            """
            QMenu {
                background-color: #1F2430;
                color: #FFFFFF;
                border: 1px solid #2E75B6;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2E75B6;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3B4252;
                margin: 4px 8px;
            }
            """
        )

        self.act_start = QAction("● Iniciar Gravação", self)
        self.act_start.triggered.connect(self.start_requested.emit)
        self.menu.addAction(self.act_start)

        self.act_pause_resume = QAction("❚❚ Pausar Gravação", self)
        self.act_pause_resume.setEnabled(False)
        self.act_pause_resume.triggered.connect(self._on_pause_resume_triggered)
        self.menu.addAction(self.act_pause_resume)

        self.act_stop = QAction("■ Concluir e Gerar Ata", self)
        self.act_stop.setEnabled(False)
        self.act_stop.triggered.connect(self.stop_requested.emit)
        self.menu.addAction(self.act_stop)

        self.menu.addSeparator()

        self.act_show = QAction("Mostrar Barra Flutuante", self)
        self.act_show.triggered.connect(self.show_widget_requested.emit)
        self.menu.addAction(self.act_show)

        self.act_open_dir = QAction("Abrir Pasta de Atas (output/)", self)
        self.act_open_dir.triggered.connect(self._open_output_dir)
        self.menu.addAction(self.act_open_dir)

        self.menu.addSeparator()

        self.act_exit = QAction("Sair", self)
        self.act_exit.triggered.connect(self.exit_requested.emit)
        self.menu.addAction(self.act_exit)

        self.setContextMenu(self.menu)

    def _on_pause_resume_triggered(self):
        if self.state == RecorderState.RECORDING:
            self.pause_requested.emit()
        elif self.state == RecorderState.PAUSED:
            self.resume_requested.emit()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Ao clicar duas vezes ou clicar no ícone, restaura o widget."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_widget_requested.emit()

    def _open_output_dir(self):
        """Abre a pasta de saída de documentos no Windows Explorer."""
        out_dir = str(OUTPUT_DIR.resolve())
        os.makedirs(out_dir, exist_ok=True)
        try:
            os.startfile(out_dir)
        except Exception:
            pass
        self.open_output_dir_requested.emit()

    def update_state(self, state: RecorderState):
        """Atualiza visual e opções do menu conforme o estado."""
        self.state = state

        if state == RecorderState.IDLE:
            self.setIcon(self.icon_idle)
            self.setToolTip("Ata Automática - Pronto")
            self.act_start.setEnabled(True)
            self.act_pause_resume.setEnabled(False)
            self.act_pause_resume.setText("❚❚ Pausar Gravação")
            self.act_stop.setEnabled(False)

        elif state == RecorderState.RECORDING:
            self.setIcon(self.icon_recording)
            self.setToolTip("Ata Automática - Gravando Reunião do Teams...")
            self.act_start.setEnabled(False)
            self.act_pause_resume.setEnabled(True)
            self.act_pause_resume.setText("❚❚ Pausar Gravação")
            self.act_stop.setEnabled(True)

        elif state == RecorderState.PAUSED:
            self.setIcon(self.icon_paused)
            self.setToolTip("Ata Automática - Gravação Pausada")
            self.act_start.setEnabled(False)
            self.act_pause_resume.setEnabled(True)
            self.act_pause_resume.setText("▶ Retomar Gravação")
            self.act_stop.setEnabled(True)

        elif state == RecorderState.PROCESSING:
            self.setIcon(self.icon_processing)
            self.setToolTip("Ata Automática - Processando Ata Executiva...")
            self.act_start.setEnabled(False)
            self.act_pause_resume.setEnabled(False)
            self.act_stop.setEnabled(False)

    def notify(self, title: str, message: str, icon_type=QSystemTrayIcon.MessageIcon.Information):
        """Exibe notificação nativa do Windows."""
        self.showMessage(title, message, icon_type, 4000)
