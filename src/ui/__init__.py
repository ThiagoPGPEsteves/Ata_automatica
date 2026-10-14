"""
Módulo de Interface Gráfica de Usuário (PyQt6)
Componentes de controle Always-On-Top, System Tray, Worker Threads e Janela de Revisão.
"""

from src.ui.floating_widget import FloatingWidget, RecorderState, DualVUMeterWidget
from src.ui.tray_icon import AtaSystemTrayIcon, create_tray_icon
from src.ui.review_dialog import ReviewDialog
from src.ui.worker_threads import PipelineWorker

__all__ = [
    "FloatingWidget",
    "RecorderState",
    "DualVUMeterWidget",
    "AtaSystemTrayIcon",
    "create_tray_icon",
    "ReviewDialog",
    "PipelineWorker",
]
