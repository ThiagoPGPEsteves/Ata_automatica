"""
Diálogo Moderno de Configuração e Teste de Dispositivos de Áudio
Permite selecionar o microfone do usuário e o dispositivo de saída/fone (Teams Loopback),
com proteção ativa para cancelamento de crosstalk em fones P3 (3.5mm).
"""

from typing import Optional, List
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QFrame,
    QTextEdit,
    QLineEdit,
    QMessageBox,
)
from PyQt6.QtGui import QFont

from src.config import (
    get_user_settings,
    save_user_settings,
    DEFAULT_CORPORATE_GLOSSARY,
)
from src.audio.devices import (
    list_available_inputs,
    list_available_outputs_loopback,
    get_default_devices,
    AudioDeviceInfo,
)


class AudioSettingsDialog(QDialog):
    """
    Diálogo para seleção e teste de dispositivos de entrada/saída,
    perfil do motor de transcrição Whisper e glossário de termos corporativos.
    """

    devices_selected = pyqtSignal(int, int)  # (mic_device_id, loopback_device_id)

    def __init__(
        self,
        current_mic_id: Optional[int] = None,
        current_loopback_id: Optional[int] = None,
        parent: Optional[QDialog] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Configuração de Áudio & Motor de Transcrição")
        self.setFixedSize(580, 580)

        # Carrega configurações salvas do usuário
        self.saved_settings = get_user_settings()

        self.current_mic_id = current_mic_id if current_mic_id is not None else self.saved_settings.get("mic_device_id")
        self.current_loopback_id = current_loopback_id if current_loopback_id is not None else self.saved_settings.get("loopback_device_id")

        self.input_devices: List[AudioDeviceInfo] = []
        self.loopback_devices: List[AudioDeviceInfo] = []

        self._init_ui()
        self._load_devices()
        self._load_transcription_settings()

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
                font-weight: 600;
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
            QLineEdit {
                background-color: #2D3748;
                color: #FFFFFF;
                border: 1px solid #4A5568;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #2D3748;
                color: #FFFFFF;
                selection-background-color: #2E75B6;
                selection-color: #FFFFFF;
            }
            QTextEdit {
                background-color: #2D3748;
                color: #FFFFFF;
                border: 1px solid #4A5568;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                font-family: 'Segoe UI', Calibri, sans-serif;
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
                padding: 8px 12px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # Cabeçalho
        lbl_title = QLabel("Configuração de Áudio & IA de Transcrição", self)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Personalize a captura de áudio, a qualidade do Whisper e os termos da sua empresa.",
            self,
        )
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: normal;")
        layout.addWidget(lbl_desc)

        # 0. Nome do Usuário na Transcrição
        layout.addWidget(QLabel("SEU NOME (SUBSTITUI '[Você]' NA TRANSCRIÇÃO E NA MATRIZ DE AÇÕES):", self))
        self.txt_user_name = QLineEdit(self)
        self.txt_user_name.setPlaceholderText("Ex: Thiago Esteves (ou seu primeiro nome)")
        layout.addWidget(self.txt_user_name)

        # 1. Microfone do Usuário
        layout.addWidget(QLabel("MICROFONE (SUA VOZ / CANAL 0):", self))
        self.combo_mic = QComboBox(self)
        layout.addWidget(self.combo_mic)

        # 2. Saída / Fone de Ouvido
        layout.addWidget(QLabel("SAÍDA DE ÁUDIO / FONES DE OUVIDO (TEAMS / CANAL 1):", self))
        self.combo_loopback = QComboBox(self)
        layout.addWidget(self.combo_loopback)

        # 3. Perfil de Transcrição Whisper
        layout.addWidget(QLabel("QUALIDADE DA TRANSCRIÇÃO LOCAL (WHISPER):", self))
        self.combo_model = QComboBox(self)
        self.combo_model.addItem("🤖 Automático (Seleciona pelo consumo de RAM livre)", "auto")
        self.combo_model.addItem("✨ Alta Fidelidade (large-v3-turbo - Recomendado)", "large-v3-turbo")
        self.combo_model.addItem("⚡ Equilibrado (small - Rápido)", "small")
        self.combo_model.addItem("🪶 Ultra Leve (base - Mínimo consumo)", "base")
        layout.addWidget(self.combo_model)

        # 4. Glossário Corporativo
        layout.addWidget(QLabel("GLOSSÁRIO & TERMOS FREQUENTES DA EMPRESA (INITIAL PROMPT):", self))
        self.txt_glossary = QTextEdit(self)
        self.txt_glossary.setPlaceholderText(
            "Digite palavras-chave, jargões, siglas da área ou nomes de participantes separados por vírgula..."
        )
        self.txt_glossary.setFixedHeight(65)
        layout.addWidget(self.txt_glossary)

        # 5. Card Informativo de Proteção Anti-Crosstalk
        card_shield = QFrame(self)
        card_shield.setObjectName("cardShield")
        c_layout = QVBoxLayout(card_shield)
        c_layout.setContentsMargins(8, 6, 8, 6)
        c_layout.setSpacing(2)

        lbl_shield_title = QLabel("🛡️ Blindagem de Hardware P3 & Anti-Alucinação Ativa", card_shield)
        lbl_shield_title.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 10.5px;")
        lbl_shield_desc = QLabel(
            "Filtro passa-alta a 80 Hz, normalização e de-duplicação temporal ativas. "
            "Elimina repetições de fala e indução elétrica em fones combo P3.",
            card_shield,
        )
        lbl_shield_desc.setWordWrap(True)
        lbl_shield_desc.setStyleSheet("color: #CBD5E1; font-size: 10px; font-weight: normal;")

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
        """Carrega e preenche os combos com os dispositivos disponíveis, priorizando match por nome."""
        self.input_devices = list_available_inputs()
        self.loopback_devices = list_available_outputs_loopback()
        defaults = get_default_devices()

        default_mic = defaults.get("mic")
        default_loop = defaults.get("loopback")
        saved_mic_name = self.saved_settings.get("mic_device_name")
        saved_loop_name = self.saved_settings.get("loopback_device_name")

        # Preenche Microfones
        self.combo_mic.clear()
        selected_mic_idx = 0
        for i, dev in enumerate(self.input_devices):
            display_name = f"{dev.name} (ID: {dev.id})"
            self.combo_mic.addItem(display_name, dev.id)
            if saved_mic_name and dev.name.strip().lower() == saved_mic_name.strip().lower():
                selected_mic_idx = i
            elif not saved_mic_name and self.current_mic_id is not None and dev.id == self.current_mic_id:
                selected_mic_idx = i
            elif not saved_mic_name and self.current_mic_id is None and default_mic and dev.id == default_mic.id:
                selected_mic_idx = i

        if self.combo_mic.count() > 0:
            self.combo_mic.setCurrentIndex(selected_mic_idx)

        # Preenche Saídas Loopback
        self.combo_loopback.clear()
        selected_loop_idx = 0
        for i, dev in enumerate(self.loopback_devices):
            display_name = f"{dev.name} (ID: {dev.id})"
            self.combo_loopback.addItem(display_name, dev.id)
            if saved_loop_name and dev.name.strip().lower() == saved_loop_name.strip().lower():
                selected_loop_idx = i
            elif not saved_loop_name and self.current_loopback_id is not None and dev.id == self.current_loopback_id:
                selected_loop_idx = i
            elif not saved_loop_name and self.current_loopback_id is None and default_loop and dev.id == default_loop.id:
                selected_loop_idx = i

        if self.combo_loopback.count() > 0:
            self.combo_loopback.setCurrentIndex(selected_loop_idx)

    def _load_transcription_settings(self):
        """Carrega perfil do modelo e glossário nas entradas visuais."""
        current_profile = self.saved_settings.get("model_profile", "auto")
        for i in range(self.combo_model.count()):
            if self.combo_model.itemData(i) == current_profile:
                self.combo_model.setCurrentIndex(i)
                break

        glossary_text = self.saved_settings.get("corporate_glossary", DEFAULT_CORPORATE_GLOSSARY)
        self.txt_glossary.setPlainText(glossary_text)

        user_name = self.saved_settings.get("user_speaker_name", "Você")
        self.txt_user_name.setText(user_name)

    def _on_save_clicked(self):
        """Salva as escolhas do usuário no arquivo config_user.json (ID e nome) e emite o sinal."""
        mic_id = self.combo_mic.currentData()
        loop_id = self.combo_loopback.currentData()
        model_profile = self.combo_model.currentData() or "auto"
        glossary_text = self.txt_glossary.toPlainText().strip() or DEFAULT_CORPORATE_GLOSSARY

        if mic_id is not None:
            self.current_mic_id = int(mic_id)
        if loop_id is not None:
            self.current_loopback_id = int(loop_id)

        mic_name = None
        for dev in self.input_devices:
            if dev.id == self.current_mic_id:
                mic_name = dev.name
                break

        loop_name = None
        for dev in self.loopback_devices:
            if dev.id == self.current_loopback_id:
                loop_name = dev.name
                break

        user_name = self.txt_user_name.text().strip() or "Você"

        # Salva persistentemente
        save_user_settings({
            "mic_device_id": self.current_mic_id,
            "mic_device_name": mic_name,
            "loopback_device_id": self.current_loopback_id,
            "loopback_device_name": loop_name,
            "model_profile": model_profile,
            "corporate_glossary": glossary_text,
            "user_speaker_name": user_name,
        })

        self.devices_selected.emit(self.current_mic_id or 0, self.current_loopback_id or 0)
        self.accept()
