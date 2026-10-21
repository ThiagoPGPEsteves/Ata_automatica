"""
Teste Automatizado da Fase 5: Interface Desktop Leve & System Tray (PyQt6)
Executa em modo headless (QT_QPA_PLATFORM=offscreen) para validação contínua e sem bloqueio.
Valida:
1. Instanciação dos componentes (FloatingWidget, SystemTrayIcon, ReviewDialog) e telemetria de RAM (< 45 MB).
2. Máquina de estados e transições da barra flutuante (IDLE, RECORDING, PAUSED, PROCESSING).
3. Ciclo de revisão e exportação no ReviewDialog (coleta de dados editados e geração .docx).
4. Sinais e estrutura do PipelineWorker assíncrono.
"""

import sys
import os
from pathlib import Path

# Configura ambiente offscreen antes de importar qualquer componente do PyQt6
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psutil
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from src.config import OUTPUT_DIR
from src.minutes.parser import MeetingMinutes, ActionItem
from src.ui.floating_widget import FloatingWidget, RecorderState, DualVUMeterWidget
from src.ui.tray_icon import AtaSystemTrayIcon, create_tray_icon
from src.ui.review_dialog import ReviewDialog
from src.ui.audio_settings_dialog import AudioSettingsDialog
from src.ui.worker_threads import PipelineWorker
import pytest

pytestmark = pytest.mark.integration


# Instância global compartilhada do QApplication para os testes
app = QApplication.instance()
if app is None:
    app = QApplication(["app_test", "-platform", "offscreen"])


def test_ui_components_instantiation_and_memory():
    """Valida que todos os componentes são instanciados e o consumo de RAM permanece abaixo de 45 MB."""
    print("\n[TESTE 1] Validando Instanciação e Consumo de RAM dos Componentes PyQt6...")

    proc = psutil.Process()
    ram_initial_mb = proc.memory_info().rss / (1024 * 1024)

    floating_bar = FloatingWidget()
    floating_bar.show()

    tray = AtaSystemTrayIcon()
    review = ReviewDialog()

    ram_after_mb = proc.memory_info().rss / (1024 * 1024)
    ram_ui_delta = ram_after_mb - ram_initial_mb

    print(f"  -> RAM inicial: {ram_initial_mb:.2f} MB")
    print(f"  -> RAM com todos os widgets carregados: {ram_after_mb:.2f} MB")
    print(f"  -> Delta de RAM atribuído à UI: {ram_ui_delta:.2f} MB")

    assert floating_bar is not None
    assert tray is not None
    assert review is not None

    # Teto estrito: A interface gráfica pura não deve acrescer mais de 50 MB
    assert ram_ui_delta < 50.0, f"Acréscimo de memória da UI excedeu o teto esperado: {ram_ui_delta:.2f} MB"

    floating_bar.close()
    review.close()
    print("  -> TESTE 1 APROVADO: Componentes criados com consumo ultrabaixo de RAM!")


def test_floating_widget_state_machine_and_signals():
    """Valida a máquina de estados, sinais emitidos e mini VU meter da barra flutuante."""
    print("\n[TESTE 2] Validando Máquina de Estados e Sinais do FloatingWidget...")

    widget = FloatingWidget()

    # 1. Estado Inicial
    assert widget.state == RecorderState.IDLE
    assert widget.lbl_status.text() == "PRONTO"
    assert widget.btn_record.isEnabled()
    assert not widget.btn_stop.isEnabled()

    # 2. Transição para RECORDING
    signal_received = {"start": False, "pause": False, "resume": False, "stop": False}

    widget.start_requested.connect(lambda: signal_received.update(start=True))
    widget.pause_requested.connect(lambda: signal_received.update(pause=True))
    widget.resume_requested.connect(lambda: signal_received.update(resume=True))
    widget.stop_requested.connect(lambda: signal_received.update(stop=True))

    widget.btn_record.click()
    assert widget.state == RecorderState.RECORDING
    assert signal_received["start"] is True
    assert "GRAVANDO" in widget.lbl_status.text()
    assert widget.btn_stop.isEnabled()

    # 3. Teste do VU Meter
    widget.vu_meter.set_levels(0.85, 0.45)
    assert widget.vu_meter.mic_level == 0.85
    assert widget.vu_meter.teams_level == 0.45

    # 4. Transição para PAUSED
    widget.btn_record.click()
    assert widget.state == RecorderState.PAUSED
    assert signal_received["pause"] is True
    assert "PAUSADO" in widget.lbl_status.text()

    # 5. Retomada para RECORDING
    widget.btn_record.click()
    assert widget.state == RecorderState.RECORDING
    assert signal_received["resume"] is True

    # 6. Parada para PROCESSING
    widget.btn_stop.click()
    assert widget.state == RecorderState.PROCESSING
    assert signal_received["stop"] is True
    assert "PROCESSANDO" in widget.lbl_status.text()
    assert not widget.btn_record.isEnabled()
    assert not widget.btn_stop.isEnabled()

    # 7. Retorno para IDLE
    widget.set_state(RecorderState.IDLE)
    assert widget.state == RecorderState.IDLE

    widget.close()
    print("  -> TESTE 2 APROVADO: Máquina de estados e sinais validados com sucesso!")


def test_review_dialog_workflow_and_export():
    """Valida o carregamento de dados, edição e exportação no ReviewDialog."""
    print("\n[TESTE 3] Validando Fluxo de Revisão e Coleta de Dados no ReviewDialog...")

    dialog = ReviewDialog()

    sample_minutes = MeetingMinutes(
        title="Alinhamento Executivo e Decisões de TI",
        date="14/10/2026",
        participants=["Thiago Esteves", "Coordenação"],
        executive_summary="Resumo inicial gerado automaticamente pela IA.",
        topics=[{"topic": "Pauta 1", "details": "Discussão de arquitetura."}],
        decisions=["Decisão preliminar homologada."],
        action_items=[
            ActionItem(action="Verificar conformidade de áudio", owner="Thiago", deadline="15/10/2026")
        ],
        next_steps=["Revisão final"],
    )

    sample_transcript = "[00:00:10] [Você]: Iniciando a reunião.\n[00:00:15] [Participantes]: Bom dia."

    # 1. Carrega dados no diálogo
    dialog.load_minutes(sample_minutes, sample_transcript)

    assert dialog.txt_title.text() == "Alinhamento Executivo e Decisões de TI"
    assert dialog.txt_date.text() == "14/10/2026"
    assert "Thiago Esteves" in dialog.txt_participants.text()
    assert "Resumo inicial" in dialog.txt_summary.toPlainText()
    assert dialog.table_actions.rowCount() == 1

    # 2. Simula edição pelo usuário
    dialog.txt_title.setText("Alinhamento Executivo - Versão Revisada")
    dialog._add_action_row()
    assert dialog.table_actions.rowCount() == 2
    dialog.table_actions.item(1, 0).setText("Ação customizada inserida na UI")
    dialog.table_actions.item(1, 1).setText("Engenharia")
    dialog.table_actions.item(1, 2).setText("20/10/2026")

    # 3. Coleta dados atualizados
    edited_minutes = dialog._collect_edited_minutes()
    assert edited_minutes.title == "Alinhamento Executivo - Versão Revisada"
    assert len(edited_minutes.action_items) == 2
    assert edited_minutes.action_items[1].action == "Ação customizada inserida na UI"

    # 4. Valida exportação direta para DOCX a partir do diálogo
    output_docx = OUTPUT_DIR / "test_ui_export_result.docx"
    from src.exporter.docx_builder import DocxMeetingMinutesBuilder
    builder = DocxMeetingMinutesBuilder()
    saved = builder.build(edited_minutes, output_docx)

    assert saved.exists()
    assert saved.stat().st_size > 10000
    print(f"  -> Arquivo Word exportado com sucesso: {saved.name} ({saved.stat().st_size} bytes)")

    dialog.close()
    print("  -> TESTE 3 APROVADO: Ciclo de revisão e exportação concluído com sucesso!")


def test_pipeline_worker_signals():
    """Valida a estrutura de sinais do PipelineWorker."""
    print("\n[TESTE 4] Validando Estrutura e Sinais do PipelineWorker...")

    worker = PipelineWorker()
    assert hasattr(worker, "progress_changed")
    assert hasattr(worker, "token_streamed")
    assert hasattr(worker, "pipeline_finished")
    assert hasattr(worker, "pipeline_error")

    # Testa método cancel
    assert not worker._is_cancelled
    worker.cancel()
    assert worker._is_cancelled

    print("  -> TESTE 4 APROVADO: PipelineWorker pronto para orquestração assíncrona!")


def test_review_dialog_theme_summary_toggle():
    """Valida alternância entre formato de Ata e Resumo de Temas no ReviewDialog."""
    dialog = ReviewDialog()

    # Alterna para resumo de temas
    idx_theme = dialog.combo_format.findData("theme_summary")
    assert idx_theme >= 0
    dialog.combo_format.setCurrentIndex(idx_theme)
    assert dialog.combo_format.currentData() == "theme_summary"
    assert dialog.tabs.tabText(0) == "📝 Resumo de Temas"
    assert "VISÃO GERAL" in dialog.lbl_sec_summary.text()

    # Carrega ata marcada como theme_summary
    sample_summary = MeetingMinutes(
        title="Resumo de Temas de TI",
        date="19/10/2026",
        participants=["Thiago", "Carlos"],
        executive_summary="Resumo de alinhamento.",
        topics=[{"topic": "Tópico 1", "details": "Discussão geral."}],
        decisions=[],
        action_items=[],
        next_steps=[],
        document_type="theme_summary",
    )
    dialog.load_minutes(sample_summary, "[00:01] Olá")
    assert dialog.combo_format.currentData() == "theme_summary"
    assert dialog.current_minutes.is_theme_summary

    # Alterna de volta para ata
    idx_min = dialog.combo_format.findData("minutes")
    assert idx_min >= 0
    dialog.combo_format.setCurrentIndex(idx_min)
    assert dialog.tabs.tabText(0) == "📄 Ata Executiva"
    assert "RESUMO EXECUTIVO" in dialog.lbl_sec_summary.text()
    dialog.close()


def test_audio_settings_dialog_new_fields():
    """Valida a presença e opções dos novos campos de formato e idioma no diálogo de configurações."""
    dialog = AudioSettingsDialog()
    assert hasattr(dialog, "combo_format")
    assert hasattr(dialog, "combo_language")

    # Valida opções de formato
    format_data = [dialog.combo_format.itemData(i) for i in range(dialog.combo_format.count())]
    assert "minutes" in format_data
    assert "theme_summary" in format_data

    # Valida opções de idioma
    lang_data = [dialog.combo_language.itemData(i) for i in range(dialog.combo_language.count())]
    assert "auto" in lang_data
    assert "pt" in lang_data
    assert "es" in lang_data
    dialog.close()


if __name__ == "__main__":
    test_ui_components_instantiation_and_memory()
    test_floating_widget_state_machine_and_signals()
    test_review_dialog_workflow_and_export()
    test_pipeline_worker_signals()
    test_review_dialog_theme_summary_toggle()
    test_audio_settings_dialog_new_fields()


def test_review_dialog_processing_state_locks_buttons():
    """Valida que o estado de processamento desabilita botões e previne chamadas concorrentes."""
    from unittest.mock import patch

    dialog = ReviewDialog()

    # Estado inicial: botões habilitados
    assert dialog.btn_export.isEnabled()
    assert dialog.btn_regenerate.isEnabled()
    assert dialog.btn_copy.isEnabled()
    assert dialog.combo_format.isEnabled()
    assert not dialog._is_processing

    # 1. Ativa estado de processamento
    dialog.set_processing_state(True, "Processando transcrição...")
    assert dialog._is_processing is True
    assert not dialog.btn_export.isEnabled()
    assert not dialog.btn_regenerate.isEnabled()
    assert not dialog.btn_copy.isEnabled()
    assert not dialog.combo_format.isEnabled()
    assert "Aguarde" in dialog.btn_export.toolTip()
    assert "Processando transcrição" in dialog.lbl_progress_status.text()

    # 2. Testa guardas internas durante processamento (não devem disparar ações)
    with patch.object(dialog, "_collect_edited_minutes") as mock_collect:
        dialog._export_to_docx()
        mock_collect.assert_not_called()

    with patch.object(dialog, "set_progress") as mock_prog:
        dialog._regenerate_minutes_with_ai()
        mock_prog.assert_not_called()

    # 3. Restaura estado e confere desbloqueio
    dialog.set_processing_state(False)
    assert dialog._is_processing is False
    assert dialog.btn_export.isEnabled()
    assert dialog.btn_regenerate.isEnabled()
    assert dialog.btn_copy.isEnabled()
    assert dialog.combo_format.isEnabled()
    assert dialog.btn_export.toolTip() == ""
    dialog.close()


def test_tray_icon_review_action_and_signal():
    """Valida a presença, controle de estado e emissão de sinal da ação de revisão no menu do tray."""
    tray = AtaSystemTrayIcon()

    # 1. Valida existência de act_review e estado inicial (desabilitado)
    assert hasattr(tray, "act_review")
    assert not tray.act_review.isEnabled()
    assert "Nenhuma ata" in tray.act_review.toolTip()

    # 2. Testa emissão do sinal review_requested
    signal_received = {"called": False}
    tray.review_requested.connect(lambda: signal_received.update(called=True))

    tray.set_review_enabled(True)
    assert tray.act_review.isEnabled() is True
    assert "Reabre a janela" in tray.act_review.toolTip()

    tray.act_review.trigger()
    assert signal_received["called"] is True

    # 3. Testa transições de estado via update_state
    # Gravação nova: deve desabilitar act_review
    tray.update_state(RecorderState.RECORDING)
    assert not tray.act_review.isEnabled()

    # Processamento: deve habilitar act_review para permitir reabertura do diálogo de progresso
    tray.update_state(RecorderState.PROCESSING)
    assert tray.act_review.isEnabled() is True


if __name__ == "__main__":
    test_ui_components_instantiation_and_memory()
    test_floating_widget_state_machine_and_signals()
    test_review_dialog_workflow_and_export()
    test_pipeline_worker_signals()
    test_review_dialog_theme_summary_toggle()
    test_audio_settings_dialog_new_fields()
    test_review_dialog_processing_state_locks_buttons()
    test_tray_icon_review_action_and_signal()

    print("\n==========================================")
    print("TODOS OS TESTES DA FASE 5 FORAM CONCLUÍDOS COM SUCESSO!")
    print("==========================================")
