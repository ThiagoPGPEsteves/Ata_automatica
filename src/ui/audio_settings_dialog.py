"""
Diálogo Moderno de Configuração e Teste de Dispositivos de Áudio
Permite selecionar o microfone do usuário e o dispositivo de saída/fone (Teams Loopback),
com proteção ativa para cancelamento de crosstalk em fones P3 (3.5mm).
"""

from typing import Optional, List
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QFrame,
    QProgressBar,
    QMessageBox,
)
from PyQt6.QtGui import QFont

from src.audio.devices import (
    list_available_inputs,
    list_available_outputs_loopback,
    get_default_devices,
    AudioDeviceInfo,
)


class AudioSettingsDialog(QDialog):
    """
    Diálogo para seleção e teste de dispositivos de entrada e saída.
    """

    devices_selected = pyqtSignal(int, int)  # (mic_device_id, loopback_device_id)

    def __init__(
        self,
        current_mic_id: Optional[int] = None,
        current_loopback_id: Optional[int] = None,
        parent: Optional[QDialog] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Configuração de Áudio & Fones de Ouvido")
        self.setFixedSize(520, 420)

        self.current_mic_id = current_mic_id
        self.current_loopback_id = current_loopback_id

        self.input_devices: List[AudioDeviceInfo] = []
        self.loopback_devices: List[AudioDeviceInfo] = []

        self._init_ui()
        self._load_devices()

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
                font-size: 12px;
            }
            QComboBox {
                background-color: #2D3748;
                color: #FFFFFF;
                border: 1px solid #4A5568;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2D3748;
                color: #FFFFFF;
                selection-background-color: #2E75B6;
                selection-color: #FFFFFF;
            }
            QPushButton {
                border-radius: 6px;
                font-family: 'Segoe UI', Calibri, sans-serif;
                font-weight: bold;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton#btnSave {
                background-color: #2E75B6;
                color: #FFFFFF;
                border: 1px solid #3B82F6;
            }
            QPushButton#btnSave:hover {
                background-color: #3B82F6;
            }
            QPushButton#btnCancel {
                background-color: #2D3748;
                color: #E2E8F0;
                border: 1px solid #4A5568;
            }
            QPushButton#btnCancel:hover {
                background-color: #4A5568;
            }
            #cardShield {
                background-color: #1E293B;
                border: 1px solid #38BDF8;
                border-radius: 8px;
                padding: 10px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Cabeçalho
        lbl_title = QLabel("Dispositivos de Captura da Reunião", self)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Selecione o microfone para sua voz e o dispositivo onde você ouve o Teams.",
            self,
        )
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(lbl_desc)

        # 1. Microfone do Usuário
        layout.addWidget(QLabel("MICROFONE (SUA VOZ / CANAL 0):", self))
        self.combo_mic = QComboBox(self)
        layout.addWidget(self.combo_mic)

        # 2. Saída / Fone de Ouvido
        layout.addWidget(QLabel("SAÍDA DE ÁUDIO / FONES DE OUVIDO (TEAMS / CANAL 1):", self))
        self.combo_loopback = QComboBox(self)
        layout.addWidget(self.combo_loopback)

        # 3. Card Informativo de Proteção Anti-Crosstalk
        card_shield = QFrame(self)
        card_shield.setObjectName("cardShield")
        c_layout = QVBoxLayout(card_shield)
        c_layout.setContentsMargins(10, 8, 10, 8)
        c_layout.setSpacing(4)

        lbl_shield_title = QLabel("🛡️ Blindagem Ativa contra Crosstalk em Fones P3 (3.5mm)", card_shield)
        lbl_shield_title.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 11px;")
        lbl_shield_desc = QLabel(
            "O pipeline possui cancelamento cruzado de eco e indução elétrica de hardware. "
            "Mesmo com fones de plugue compartilhado, o vazamento elétrico é filtrado automaticamente.",
            card_shield,
        )
        lbl_shield_desc.setWordWrap(True)
        lbl_shield_desc.setStyleSheet("color: #CBD5E1; font-size: 10px;")

        c_layout.addWidget(lbl_shield_title)
        c_layout.addWidget(lbl_shield_desc)
        layout.addWidget(card_shield)

        layout.addStretch()

        # Botões de Ação
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("Cancelar", self)
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_layout.addStretch()

        btn_save = QPushButton("Salvar Configuração", self)
        btn_save.setObjectName("btnSave")
        btn_save.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def _load_devices(self):
        """Carrega e preenche os combos com os dispositivos disponíveis."""
        self.input_devices = list_available_inputs()
        self.loopback_devices = list_available_outputs_loopback()
        defaults = get_default_devices()

        default_mic = defaults.get("mic")
        default_loop = defaults.get("loopback")

        # Preenche Microfones
        self.combo_mic.clear()
        selected_mic_idx = 0
        for i, dev in enumerate(self.input_devices):
            display_name = f"{dev.name} (ID: {dev.id})"
            self.combo_mic.addItem(display_name, dev.id)
            if self.current_mic_id is not None and dev.id == self.current_mic_id:
                selected_mic_idx = i
            elif self.current_mic_id is None and default_mic and dev.id == default_mic.id:
                selected_mic_idx = i

        if self.combo_mic.count() > 0:
            self.combo_mic.setCurrentIndex(selected_mic_idx)

        # Preenche Saídas Loopback
        self.combo_loopback.clear()
        selected_loop_idx = 0
        for i, dev in enumerate(self.loopback_devices):
            display_name = f"{dev.name} (ID: {dev.id})"
            self.combo_loopback.addItem(display_name, dev.id)
            if self.current_loopback_id is not None and dev.id == self.current_loopback_id:
                selected_loop_idx = i
            elif self.current_loopback_id is None and default_loop and dev.id == default_loop.id:
                selected_loop_idx = i

        if self.combo_loopback.count() > 0:
            self.combo_loopback.setCurrentIndex(selected_loop_idx)

    def _on_save_clicked(self):
        """Salva a escolha do usuário e emite o sinal."""
        mic_id = self.combo_mic.currentData()
        loop_id = self.combo_loopback.currentData()

        if mic_id is not None:
            self.current_mic_id = int(mic_id)
        if loop_id is not None:
            self.current_loopback_id = int(loop_id)

        self.devices_selected.emit(self.current_mic_id or 0, self.current_loopback_id or 0)
        self.accept()
