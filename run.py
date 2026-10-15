"""
Ponto de Entrada Principal da Aplicação: Ata Automática para Microsoft Teams
Inicializa a interface gráfica (PyQt6), realiza verificações prévias do sistema (pre-flight checks),
orquestra a gravação dual WASAPI, a transcrição local com faster-whisper e a geração de atas executivas.
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from typing import Optional

# Configuração de logging corporativo
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AtaAutomatica")

# Garante que o diretório raiz esteja no sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Auto-reexecução com o interpretador do ambiente virtual (.venv):
# Se o usuário executar 'python run.py' pelo Python global do Windows sem ativar o venv,
# detecta e transfere a execução de forma transparente para o Python do .venv onde o PyQt6 está instalado.
venv_python = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
if venv_python.exists():
    try:
        current_exe = Path(sys.executable).resolve()
        target_exe = venv_python.resolve()
        if current_exe != target_exe:
            import subprocess
            sys.exit(subprocess.call([str(target_exe)] + sys.argv))
    except Exception as _e:
        logger.debug("Não foi possível auto-elevar para .venv: %s", _e)

# Configura ID do processo para correta exibição e fixação na barra de tarefas do Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("thiago.ata_automatica.v1")
    except Exception as e:
        logger.debug("Não foi possível definir AppUserModelID: %s", e)

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

from src.config import OUTPUT_DIR, TEMP_DIR, OLLAMA_MODEL, OLLAMA_URL
from src.audio.devices import get_default_devices
from src.audio.recorder import DualAudioRecorder
from src.minutes.ollama_client import OllamaClient
from src.ui.floating_widget import FloatingWidget, RecorderState
from src.ui.tray_icon import AtaSystemTrayIcon
from src.ui.review_dialog import ReviewDialog
from src.ui.worker_threads import PipelineWorker


class AtaApplicationController:
    """
    Controlador central que orquestra o ciclo de vida da aplicação,
    conectando os eventos da UI ao gravador e aos workers de processamento.
    """

    def __init__(self, start_minimized: bool = False):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setApplicationName("Ata Automática - Microsoft Teams")
        self.app.setQuitOnLastWindowClosed(False)

        # 1. Componentes do Backend
        self.recorder = DualAudioRecorder()
        self.current_worker: Optional[PipelineWorker] = None
        self.selected_mic_id: Optional[int] = None
        self.selected_loopback_id: Optional[int] = None

        # 2. Componentes da Interface Gráfica
        self.floating_widget = FloatingWidget(recorder=self.recorder)
        self.tray_icon = AtaSystemTrayIcon()
        self.review_dialog = ReviewDialog()

        # 3. Roteamento de Sinais e Eventos
        self._connect_signals()

        # 4. Exibição Inicial
        self.tray_icon.show()
        if not start_minimized:
            self._position_floating_widget()
            self.floating_widget.show()

        # Garante finalização limpa ao sair
        self.app.aboutToQuit.connect(self._on_cleanup)

    def _position_floating_widget(self):
        """Posiciona a barra flutuante no topo central da tela principal."""
        screen = self.app.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            w_width = self.floating_widget.width()
            x = geom.x() + (geom.width() - w_width) // 2
            y = geom.y() + 20  # 20 pixels abaixo do topo
            self.floating_widget.move(x, y)

    def _connect_signals(self):
        """Conecta todos os sinais entre o widget flutuante, a bandeja e o diálogo de revisão."""
        # Ações originadas na Barra Flutuante
        self.floating_widget.start_requested.connect(self.start_recording)
        self.floating_widget.pause_requested.connect(self.pause_recording)
        self.floating_widget.resume_requested.connect(self.resume_recording)
        self.floating_widget.stop_requested.connect(self.stop_and_process)
        self.floating_widget.settings_requested.connect(self.open_audio_settings)
        self.floating_widget.minimize_tray_requested.connect(self.hide_to_tray)

        # Ações originadas no Menu da Bandeja (System Tray)
        self.tray_icon.start_requested.connect(self.start_recording)
        self.tray_icon.pause_requested.connect(self.pause_recording)
        self.tray_icon.resume_requested.connect(self.resume_recording)
        self.tray_icon.stop_requested.connect(self.stop_and_process)
        self.tray_icon.settings_requested.connect(self.open_audio_settings)
        self.tray_icon.show_widget_requested.connect(self.show_floating_widget)
        self.tray_icon.exit_requested.connect(self.exit_app)

    def open_audio_settings(self):
        """Abre a janela de configuração de dispositivos de áudio e fones de ouvido."""
        from src.ui.audio_settings_dialog import AudioSettingsDialog
        dialog = AudioSettingsDialog(
            current_mic_id=self.selected_mic_id,
            current_loopback_id=self.selected_loopback_id,
            parent=self.floating_widget,
        )

        def on_devices_saved(mic_id, loop_id):
            self.selected_mic_id = mic_id
            self.selected_loopback_id = loop_id
            logger.info("Dispositivos de áudio selecionados pelo usuário: Mic=%d, Loopback=%d", mic_id, loop_id)

        dialog.devices_selected.connect(on_devices_saved)
        dialog.exec()

    def start_recording(self):
        """Inicia a captura de áudio nos canais de Microfone e Teams com os dispositivos configurados."""
        try:
            logger.info(
                "Iniciando gravação de áudio (Mic=%s, Loopback=%s)...",
                self.selected_mic_id,
                self.selected_loopback_id,
            )
            self.recorder.start(
                mic_device_id=self.selected_mic_id,
                loopback_device_id=self.selected_loopback_id,
            )
            self.floating_widget.set_state(RecorderState.RECORDING)
            self.tray_icon.update_state(RecorderState.RECORDING)
            self.tray_icon.notify(
                "Gravação Iniciada",
                "Capturando microfone e participantes da reunião Teams.",
            )
        except Exception as e:
            logger.exception("Falha ao iniciar gravação: %s", e)
            self.floating_widget.set_state(RecorderState.IDLE)
            self.tray_icon.update_state(RecorderState.IDLE)
            QMessageBox.critical(
                self.floating_widget,
                "Erro na Gravação",
                f"Não foi possível iniciar a gravação de áudio:\n\n{e}",
            )

    def pause_recording(self):
        """Pausa a captura de áudio."""
        logger.info("Pausando gravação...")
        self.recorder.pause()
        self.floating_widget.set_state(RecorderState.PAUSED)
        self.tray_icon.update_state(RecorderState.PAUSED)

    def resume_recording(self):
        """Retoma a captura de áudio pausada."""
        logger.info("Retomando gravação...")
        self.recorder.resume()
        self.floating_widget.set_state(RecorderState.RECORDING)
        self.tray_icon.update_state(RecorderState.RECORDING)

    def stop_and_process(self):
        """Finaliza a reunião e dispara o pipeline assíncrono em segundo plano."""
        logger.info("Finalizando reunião e iniciando processamento do pipeline...")
        self.floating_widget.set_state(RecorderState.PROCESSING)
        self.tray_icon.update_state(RecorderState.PROCESSING)

        # Abre a tela de revisão exibindo a barra de progresso
        self.review_dialog.set_progress("Finalizando gravação no disco...", 5)
        self.review_dialog.show()
        self.review_dialog.raise_()
        self.review_dialog.activateWindow()

        # Cria e inicia o worker em thread secundária (QThread)
        self.current_worker = PipelineWorker(recorder=self.recorder)
        self.current_worker.progress_changed.connect(self.review_dialog.set_progress)
        self.current_worker.token_streamed.connect(self.review_dialog.append_stream_token)
        self.current_worker.pipeline_finished.connect(self._on_pipeline_finished)
        self.current_worker.pipeline_error.connect(self._on_pipeline_error)
        self.current_worker.start()

    def _on_pipeline_finished(self, minutes_obj, transcript_text, recording_path):
        """Callback acionado quando a transcrição e a ata foram concluídas com sucesso."""
        logger.info("Pipeline concluído com sucesso!")
        self.floating_widget.set_state(RecorderState.IDLE)
        self.tray_icon.update_state(RecorderState.IDLE)

        # Carrega os dados no editor da ata
        self.review_dialog.load_minutes(minutes_obj, transcript_text)

        self.tray_icon.notify(
            "Ata Gerada com Sucesso!",
            "A ata executiva da reunião está pronta para revisão e exportação em Word.",
        )

    def _on_pipeline_error(self, error_msg: str):
        """Callback acionado se houver erro durante o processamento de áudio ou IA."""
        logger.error("Erro no pipeline: %s", error_msg)
        self.floating_widget.set_state(RecorderState.IDLE)
        self.tray_icon.update_state(RecorderState.IDLE)

        self.tray_icon.notify(
            "Falha no Processamento",
            f"Ocorreu um erro: {error_msg[:100]}...",
            icon_type=AtaSystemTrayIcon.MessageIcon.Critical,
        )

        QMessageBox.warning(
            self.review_dialog,
            "Aviso no Processamento",
            f"Não foi possível concluir a geração automática da ata:\n\n{error_msg}\n\n"
            "Dica: Se o erro for de conexão com o Ollama, certifique-se de que o daemon local está ativo "
            "com 'ollama serve' e tente novamente.",
        )

    def show_floating_widget(self):
        """Exibe a barra flutuante Always-On-Top."""
        self.floating_widget.show()
        self.floating_widget.raise_()
        self.floating_widget.activateWindow()

    def hide_to_tray(self):
        """Minimiza a barra flutuante para a bandeja do Windows."""
        self.floating_widget.hide()
        self.tray_icon.notify(
            "Ata Automática em Segundo Plano",
            "A aplicação continua ativa na bandeja do sistema perto do relógio.",
        )

    def exit_app(self):
        """Fecha a aplicação e descarrega todos os recursos."""
        logger.info("Encerrando aplicação...")
        self._on_cleanup()
        self.app.quit()

    def _on_cleanup(self):
        """Rotina de encerramento seguro."""
        if self.recorder and self.recorder.is_recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.cancel()
            self.current_worker.wait(2000)

    def run(self) -> int:
        """Inicia o loop de eventos do Qt."""
        return self.app.exec()


# Garante saída compatível com qualquer terminal Windows (cp1252 / utf-8)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_preflight_checks() -> bool:
    """
    Executa checagens prévias de saúde dos dispositivos de áudio e do servidor Ollama.
    Retorna True se os requisitos mínimos forem atendidos.
    """
    print("\n" + "=" * 60)
    print("  VERIFICACAO DE PRE-REQUISITOS DO SISTEMA (PRE-FLIGHT)")
    print("=" * 60)

    # 1. Checagem de Dispositivos de Áudio WASAPI
    print("\n[1/3] Verificando Dispositivos de Audio (WASAPI)...")
    devices = get_default_devices()
    mic = devices.get("mic")
    loopback = devices.get("loopback")

    if mic:
        print(f"  [OK] Microfone Padrao: {mic.name} ({mic.sample_rate}Hz, {mic.channels}ch)")
    else:
        print("  [ERRO] Microfone Padrao nao detectado.")

    if loopback:
        print(f"  [OK] Saida de Som (Teams/Loopback): {loopback.name} ({loopback.sample_rate}Hz, {loopback.channels}ch)")
    else:
        print("  [AVISO] Loopback do Teams nao detectado automaticamente. Verifique se o fone esta conectado.")

    # 2. Checagem de Diretórios Base
    print("\n[2/3] Verificando Diretorios de Trabalho...")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  [OK] Diretorio Temporario (Audio): {TEMP_DIR.resolve()}")
    print(f"  [OK] Diretorio de Saida (Atas Word): {OUTPUT_DIR.resolve()}")

    # 3. Checagem do Daemon do Ollama
    print("\n[3/3] Verificando Conexao com Ollama Local...")
    ollama_client = OllamaClient()
    ollama_ok = ollama_client.is_available()

    if ollama_ok:
        print(f"  [OK] Ollama online em {OLLAMA_URL}!")
        try:
            models = ollama_client.list_installed_models()
            print(f"  [OK] Modelos disponiveis: {', '.join(models) if models else 'Nenhum'}")
            has_llama = any(OLLAMA_MODEL in m for m in models)
            if has_llama:
                print(f"  [OK] Modelo alvo '{OLLAMA_MODEL}' localizado e pronto.")
            else:
                print(f"  [AVISO] Modelo '{OLLAMA_MODEL}' nao encontrado na lista. Execute: 'ollama pull {OLLAMA_MODEL}'")
        except Exception:
            pass
    else:
        print(f"  [AVISO] Ollama nao detectado em {OLLAMA_URL}.")
        print("    A gravacao de audio funcionara normalmente, mas para gerar a ata pela IA,")
        print(f"    inicie o Ollama no terminal com: 'ollama run {OLLAMA_MODEL}'")

    print("\n" + "=" * 60)
    print("  VERIFICACAO CONCLUIDA")
    print("=" * 60 + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Ata Automática para Microsoft Teams")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Executa apenas a verificação de pré-requisitos e finaliza.",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Inicia a aplicação minimizada diretamente na bandeja do sistema.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Ativa mensagens detalhadas de depuração no console.",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run_preflight_checks()

    if args.check_only:
        sys.exit(0)

    controller = AtaApplicationController(start_minimized=args.minimized)
    sys.exit(controller.run())


if __name__ == "__main__":
    main()
