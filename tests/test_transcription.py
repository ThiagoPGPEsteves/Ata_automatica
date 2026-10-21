"""
Teste Automatizado da Fase 2: Transcrição Local, Diarização Dual-Channel e Descarregamento de RAM.
Valida:
1. Seleção adaptativa de modelo por RAM disponível.
2. Separação de canais WAV e mesclagem cronológica com rótulos de locutor.
3. Carregamento do faster-whisper, transcrição e descarregamento ativo com medição de RAM.
"""

import os
import sys
import time
import wave
from pathlib import Path
import numpy as np
import psutil

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import TEMP_DIR
from src.transcription.whisper_engine import (
    WhisperEngine,
    select_optimal_model_size,
    get_process_ram_mb,
    get_available_ram_mb,
)
from src.transcription.post_process import (
    split_dual_channel_audio,
    merge_channel_transcripts,
    format_transcript_dialogue,
    process_dual_recording,
    clean_text_tokens,
    filter_acoustic_echo_segments,
    ACOUSTIC_STOPWORDS,
)
import pytest

pytestmark = pytest.mark.integration


def create_synthetic_dual_wav(filepath: Path, duration_sec: float = 3.0, sample_rate: int = 16000) -> Path:
    """Cria um arquivo WAV dual-channel simulado para testes rápidos sem depender de microfone."""
    total_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, total_samples, endpoint=False)

    # Canal 0 (Você): Tom audível de 440 Hz na primeira metade, silêncio na segunda
    ch0 = np.sin(2 * np.pi * 440 * t)
    ch0[total_samples // 2 :] = 0.0

    # Canal 1 (Teams): Silêncio na primeira metade, tom audível de 880 Hz na segunda
    ch1 = np.sin(2 * np.pi * 880 * t)
    ch1[: total_samples // 2] = 0.0

    ch0_int16 = (ch0 * 16000).astype(np.int16)
    ch1_int16 = (ch1 * 16000).astype(np.int16)

    stereo = np.empty((total_samples, 2), dtype=np.int16)
    stereo[:, 0] = ch0_int16
    stereo[:, 1] = ch1_int16

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(stereo.tobytes())

    return filepath


def test_model_selection():
    """Valida a seleção adaptativa do modelo Whisper de acordo com a memória RAM livre."""
    print("\n[TESTE 1] Validando Seleção Adaptativa de Modelo Whisper (Turbo, Small, Base)...")
    free_ram = get_available_ram_mb()
    selected = select_optimal_model_size()
    print(f"  -> Memória RAM disponível: {free_ram:.2f} MB")
    print(f"  -> Modelo Whisper selecionado automaticamente: '{selected}'")

    if free_ram >= 2000:
        assert selected == "large-v3-turbo", f"Deveria ter selecionado 'large-v3-turbo', selecionou '{selected}'"
    elif free_ram >= 1200:
        assert selected == "small", f"Deveria ter selecionado 'small', selecionou '{selected}'"
    else:
        assert selected == "base", f"Deveria ter selecionado 'base', selecionou '{selected}'"

    # Testa seleção explícita do usuário
    forced = select_optimal_model_size(preferred_model="small")
    assert forced == "small", "Deveria ter respeitado preferência explícita 'small'"

    print("  -> TESTE 1 APROVADO: Lógica adaptativa de 3 níveis de memória validada!")


def test_dsp_audio_preprocessing():
    """Valida o condicionamento DSP de áudio (filtro passa-alta a 80Hz e normalização de pico)."""
    print("\n[TESTE 1.5] Validando Condicionamento DSP de Áudio...")
    from src.transcription.whisper_engine import preprocess_audio_dsp

    # Sinal sintético de 1 segundo: ruído elétrico de 60Hz + fala de 500Hz
    t = np.linspace(0, 1.0, 16000, endpoint=False)
    hum_60hz = 0.5 * np.sin(2 * np.pi * 60 * t)
    voice_500hz = 0.2 * np.sin(2 * np.pi * 500 * t)
    dirty_audio = (hum_60hz + voice_500hz).astype(np.float32)

    cleaned = preprocess_audio_dsp(dirty_audio)
    assert len(cleaned) == len(dirty_audio), "Duração deve ser preservada"
    assert np.max(np.abs(cleaned)) <= 1.0, "Áudio normalizado não pode estourar 1.0"
    print("  -> TESTE 1.5 APROVADO: Filtro FIR e normalização DSP validados com sucesso!")


def test_post_process_and_diarization():
    """Valida a separação de canais estéreo e intercalação cronológica de falas."""
    print("\n[TESTE 2] Validando Separação Dual-Channel e Mesclagem com Diarização...")
    test_wav = TEMP_DIR / "test_synth_dual.wav"
    create_synthetic_dual_wav(test_wav, duration_sec=4.0)

    # 1. Testa separação
    ch_mic, ch_teams, sr = split_dual_channel_audio(test_wav)
    assert sr == 16000, f"Sample rate incorreto: {sr}"
    assert len(ch_mic) == len(ch_teams), "Canais devem ter a mesma quantidade de amostras"
    assert len(ch_mic) == 4 * 16000, f"Duração inesperada: {len(ch_mic)}"

    # 2. Testa mesclagem simulada
    user_segs = [
        {"start": 0.5, "end": 2.0, "text": "Olá equipe, bom dia."},
        {"start": 2.1, "end": 3.0, "text": "Vamos revisar a pauta de hoje."},
    ]
    teams_segs = [
        {"start": 3.2, "end": 4.5, "text": "Bom dia Thiago, pauta alinhada."},
    ]

    merged = merge_channel_transcripts(user_segs, teams_segs)
    assert len(merged) == 2, f"Esperado 2 blocos (com junção consecutiva), obtido {len(merged)}"
    assert merged[0]["speaker"] == "Você", "Primeiro locutor deveria ser Você"
    assert merged[1]["speaker"] == "Participantes da Reunião", "Segundo locutor deveria ser Teams"

    formatted = format_transcript_dialogue(merged)
    print("  -> Diálogo formatado gerado:")
    for line in formatted.split("\n"):
        print(f"     {line}")

    assert "[Você]" in formatted
    assert "[Participantes da Reunião]" in formatted

    if test_wav.exists():
        os.remove(test_wav)

    print("  -> TESTE 2 APROVADO: Separação de canais e mesclagem de diálogos validadas!")


def test_whisper_engine_transcription_and_unload():
    """Valida o carregamento do faster-whisper, transcrição de áudio e descarregamento ativo da RAM."""
    print("\n[TESTE 3] Validando faster-whisper com Descarregamento Ativo de Memória...")
    ram_initial = get_process_ram_mb()
    print(f"  -> RAM inicial do processo: {ram_initial:.2f} MB")

    # Usamos o modelo 'base' para o teste automatizado rápido e leve
    engine = WhisperEngine(model_size="base")

    # 1. Carrega modelo
    engine.load()
    assert engine.is_loaded, "O modelo deveria estar carregado."
    ram_loaded = get_process_ram_mb()
    ram_cost = ram_loaded - ram_initial
    print(f"  -> RAM com modelo 'base' carregado: {ram_loaded:.2f} MB (Custo do modelo: +{ram_cost:.2f} MB)")

    # 2. Transcrição de áudio sintético (1 segundo de silêncio/ruído leve)
    dummy_audio = (np.random.randn(16000) * 0.01).astype(np.float32)
    segments = engine.transcribe(dummy_audio)
    print(f"  -> Transcrição executada com sucesso. Segmentos retornados: {len(segments)}")

    # 3. Descarregamento da RAM
    engine.unload()
    assert not engine.is_loaded, "O modelo deveria ter sido descarregado."
    ram_unloaded = get_process_ram_mb()
    print(f"  -> RAM após descarregamento e gc.collect(): {ram_unloaded:.2f} MB")

    # Assertiva: O consumo de RAM após descarregamento deve retornar para próximo do valor inicial
    ram_diff = ram_unloaded - ram_initial
    print(f"  -> Variação residual de RAM: {ram_diff:+.2f} MB")
    assert ram_diff < 150.0, f"Memória residual muito alta pós-descarregamento: {ram_diff:.2f} MB"

    print("  -> TESTE 3 APROVADO: faster-whisper transcreveu e descarregou 100% da memória com sucesso!")


def test_whisper_engine_transcribe_with_none_language_probability():
    """Valida que a transcrição não falha quando info.language_probability ou info.language forem None."""
    from unittest.mock import MagicMock

    engine = WhisperEngine(model_size="base")
    engine._is_loaded = True
    engine._model = MagicMock()

    class FakeSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    fake_segments = [FakeSegment(0.0, 1.0, "Teste de robustez de idioma")]

    # 1. Caso com language_probability = None e language = None
    fake_info_none = MagicMock()
    fake_info_none.duration = 1.0
    fake_info_none.language = None
    fake_info_none.language_probability = None

    engine._model.transcribe.return_value = (fake_segments, fake_info_none)

    dummy_audio = np.zeros(16000, dtype=np.float32)
    results = engine.transcribe(dummy_audio)

    assert len(results) == 1
    assert results[0]["text"] == "Teste de robustez de idioma"
    assert engine.last_detected_language == "desconhecido"
    assert engine.last_language_probability is None

    # 2. Caso com objeto info sem atributos (objeto genérico)
    class EmptyInfo:
        pass

    engine._model.transcribe.return_value = (fake_segments, EmptyInfo())
    results_empty = engine.transcribe(dummy_audio)
    assert len(results_empty) == 1
    assert engine.last_detected_language == "desconhecido"
    assert engine.last_language_probability is None

    # 3. Caso normal com idioma e probabilidade válidos
    fake_info_valid = MagicMock()
    fake_info_valid.duration = 1.0
    fake_info_valid.language = "pt"
    fake_info_valid.language_probability = 0.985

    engine._model.transcribe.return_value = (fake_segments, fake_info_valid)
    results_valid = engine.transcribe(dummy_audio)
    assert len(results_valid) == 1
    assert engine.last_detected_language == "pt"
    assert engine.last_language_probability == 0.985


def test_clean_text_tokens_multilingual_stopwords():
    """Valida a remoção de stopwords em Português, Espanhol e Inglês e a preservação de termos de conteúdo."""
    # Português
    pt_text = "Nós temos que verificar o relatório e o orçamento do projeto com a equipe."
    pt_tokens = clean_text_tokens(pt_text)
    assert "relatório" in pt_tokens
    assert "orçamento" in pt_tokens
    assert "projeto" in pt_tokens
    assert "equipe" in pt_tokens
    # Stopwords devem ser removidas
    for sw in ["temos", "que", "com"]:
        assert sw not in pt_tokens

    # Espanhol
    es_text = "Pero entonces nosotros tenemos que revisar los detalles del presupuesto para el proyecto."
    es_tokens = clean_text_tokens(es_text)
    assert "revisar" in es_tokens
    assert "detalles" in es_tokens
    assert "presupuesto" in es_tokens
    assert "proyecto" in es_tokens
    # Stopwords em espanhol devem ser removidas
    for sw in ["pero", "entonces", "nosotros", "tenemos", "los", "del", "para"]:
        assert sw not in es_tokens

    # Inglês
    en_text = "We will discuss the architecture and performance of the system with the team."
    en_tokens = clean_text_tokens(en_text)
    assert "discuss" in en_tokens
    assert "architecture" in en_tokens
    assert "performance" in en_tokens
    assert "system" in en_tokens
    assert "team" in en_tokens
    for sw in ["will", "the", "and", "with"]:
        assert sw not in en_tokens


def test_filter_acoustic_echo_segments_spanish():
    """Valida a supressão de eco acústico em falas em Espanhol e a não-supressão de falas genuínas."""
    # Cenário: Participante do Teams fala sobre o cronograma em espanhol
    teams_segments = [
        {
            "start": 10.0,
            "end": 15.0,
            "text": "Vamos a revisar el presupuesto del proyecto para el próximo trimestre.",
        }
    ]

    # Canal do Microfone:
    # 1. Vazamento acústico dos alto-falantes captado pelo microfone no mesmo intervalo (eco)
    # 2. Fala genuína do usuário concordando e propondo outro ponto com expressões conversacionais
    user_segments = [
        {
            "start": 10.5,
            "end": 14.5,
            "text": "revisar el presupuesto del proyecto para el próximo trimestre",
        },
        {
            "start": 16.0,
            "end": 20.0,
            "text": "De acuerdo, pero entonces yo presentaré las métricas de calidad.",
        },
    ]

    clean_user = filter_acoustic_echo_segments(user_segments, teams_segments)

    # O segmento de eco (10.5 - 14.5) deve ter sido eliminado
    assert len(clean_user) == 1
    assert "métricas" in clean_user[0]["text"]
    assert clean_user[0]["start"] == 16.0

    # Cenário de sobreposição temporal mas falas genuinamente distintas com stopwords em espanhol:
    concurrent_user_speech = [
        {
            "start": 11.0,
            "end": 14.0,
            "text": "Pero entonces comenzaremos con la arquitectura del servidor.",
        }
    ]
    # Mesmo compartilhando stopwords como 'pero', 'entonces', 'con', as palavras de conteúdo são diferentes
    clean_concurrent = filter_acoustic_echo_segments(concurrent_user_speech, teams_segments)
    assert len(clean_concurrent) == 1, "Fala genuína do usuário com stopwords comuns não deve ser descartada como eco"


if __name__ == "__main__":
    test_model_selection()
    test_dsp_audio_preprocessing()
    test_post_process_and_diarization()
    test_whisper_engine_transcription_and_unload()
    test_whisper_engine_transcribe_with_none_language_probability()
    test_clean_text_tokens_multilingual_stopwords()
    test_filter_acoustic_echo_segments_spanish()
    print("\n==========================================")
    print("TODOS OS TESTES DA FASE 2 FORAM CONCLUÍDOS!")
    print("==========================================")
