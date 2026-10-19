"""
EchoGate: Supressão Digital de Eco Acústico e Vazamento Elétrico (Crosstalk)
Processa o sinal de áudio do microfone antes do Whisper, utilizando o áudio de
loopback (Teams) como referência limpa para estimar o atraso físico e atenuar vazamentos.
"""

import logging
from typing import Tuple, Dict, Any, Optional
import numpy as np

from src.config import (
    AUDIO_ECHOGATE_ENABLED,
    ECHOGATE_MIN_CORRELATION,
    ECHOGATE_FRAME_MS,
    ECHOGATE_MAX_DELAY_MS,
    ECHOGATE_SUPPRESSION_DB,
    ECHOGATE_DOUBLE_TALK_MARGIN_DB,
    SAMPLE_RATE,
)

logger = logging.getLogger(__name__)


class EchoGate:
    """
    Cancelador de eco de baixa complexidade (Zero-RAM overhead) operando no domínio do sinal.
    1. Estima o atraso temporal exato (tau) entre loopback e mic via correlação cruzada FFT.
    2. Estima o ganho de acoplamento/vazamento (alpha) entre fone/saída e microfone.
    3. Aplica atenuação seletiva nos quadros onde apenas o áudio de terceiros está presente,
       preservando integralmente a fala do usuário durante double-talk (fala simultânea).
    """

    def __init__(
        self,
        frame_ms: float = ECHOGATE_FRAME_MS,
        max_delay_ms: float = ECHOGATE_MAX_DELAY_MS,
        min_correlation_threshold: float = ECHOGATE_MIN_CORRELATION,
        suppression_db: float = ECHOGATE_SUPPRESSION_DB,
        double_talk_margin_db: float = ECHOGATE_DOUBLE_TALK_MARGIN_DB,
    ):
        self.frame_ms = frame_ms
        self.max_delay_ms = max_delay_ms
        self.min_correlation_threshold = min_correlation_threshold
        self.suppression_db = suppression_db
        self.double_talk_margin_db = double_talk_margin_db

    def estimate_delay(
        self,
        mic_signal: np.ndarray,
        loopback_signal: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
    ) -> Tuple[int, float]:
        """
        Estima o atraso em amostras (tau >= 0) e a correlação cruzada pico (0.0 a 1.0).
        Utiliza segmentação em blocos para focar nos trechos em que o Teams estava falando
        e o usuário estava ouvindo (evitando que falas do usuário mascarem o vazamento).
        Retorna (delay_samples, peak_correlation).
        """
        min_len = min(len(mic_signal), len(loopback_signal))
        if min_len < int(sample_rate * 0.5):
            return 0, 0.0

        max_delay_samples = int(sample_rate * (self.max_delay_ms / 1000.0))

        # 1. Procura blocos de 0.5s a 1.0s onde o loopback esteve ativo e o usuário quieto
        seg_size = int(sample_rate * 0.5)
        num_segs = min_len // seg_size

        candidate_blocks = []
        for i in range(min(num_segs, 120)):
            l_seg = loopback_signal[i * seg_size : (i + 1) * seg_size]
            m_seg = mic_signal[i * seg_size : (i + 1) * seg_size]

            l_rms = float(np.sqrt(np.mean(l_seg**2)))
            m_rms = float(np.sqrt(np.mean(m_seg**2)))

            # Se Teams está falando e o mic tem energia compatível com vazamento
            if l_rms > 0.01 and m_rms > 0.001:
                ratio = m_rms / l_rms
                candidate_blocks.append((ratio, m_seg, l_seg))

        # Se encontrou blocos onde o Teams falou, seleciona os que tiveram menor razão (escuta pura)
        if candidate_blocks:
            candidate_blocks.sort(key=lambda item: item[0])
            # Concatena até 3 melhores blocos de escuta
            top_blocks = candidate_blocks[:3]
            m_target = np.concatenate([b[1] for b in top_blocks]).astype(np.float32)
            l_target = np.concatenate([b[2] for b in top_blocks]).astype(np.float32)
        else:
            # Fallback para os primeiros 30 segundos
            analysis_len = min(min_len, sample_rate * 30)
            m_target = mic_signal[:analysis_len].astype(np.float32)
            l_target = loopback_signal[:analysis_len].astype(np.float32)

        # Remove componente DC (média zero)
        x = l_target - np.mean(l_target)
        y = m_target - np.mean(m_target)

        norm_x = np.linalg.norm(x)
        norm_y = np.linalg.norm(y)

        if norm_x < 1e-4 or norm_y < 1e-4:
            return 0, 0.0

        # Correlação cruzada normalizada via FFT
        n_fft = 1 << (len(x) + max_delay_samples - 1).bit_length()
        X = np.fft.rfft(x, n=n_fft)
        Y = np.fft.rfft(y, n=n_fft)
        r = np.fft.irfft(Y * np.conj(X), n=n_fft)

        # Atrasos positivos: de 0 até max_delay_samples
        valid_lags = r[:max_delay_samples]
        if len(valid_lags) == 0:
            return 0, 0.0

        best_lag = int(np.argmax(valid_lags))
        peak_corr = float(valid_lags[best_lag] / (norm_x * norm_y))

        return best_lag, max(0.0, min(1.0, peak_corr))

    def estimate_leakage_ratio(
        self,
        mic_signal: np.ndarray,
        aligned_loopback: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
    ) -> float:
        """
        Estima a razão de amplitude (alpha = RMS_mic / RMS_loop) nos trechos de fala exclusiva do loopback.
        """
        frame_size = int(sample_rate * (self.frame_ms / 1000.0))
        if frame_size <= 0:
            return 0.1

        num_frames = min(len(mic_signal), len(aligned_loopback)) // frame_size
        if num_frames == 0:
            return 0.1

        ratios = []
        for i in range(num_frames):
            idx = i * frame_size
            l_frame = aligned_loopback[idx : idx + frame_size]
            m_frame = mic_signal[idx : idx + frame_size]

            l_rms = float(np.sqrt(np.mean(l_frame**2)))
            m_rms = float(np.sqrt(np.mean(m_frame**2)))

            # Se o Teams estiver ativo e o microfone não estiver saturado de fala própria
            if l_rms > 0.015 and 0.001 < m_rms < (l_rms * 1.5):
                ratios.append(m_rms / l_rms)

        if not ratios:
            return 0.15

        # Usa o percentil 50 (mediana) para robustez a ruídos esporádicos
        median_ratio = float(np.median(ratios))
        return max(0.01, min(0.95, median_ratio))

    def process(
        self,
        mic_signal: np.ndarray,
        loopback_signal: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Executa a supressão de eco e vazamento no sinal do microfone.
        Retorna (cleaned_mic_signal, telemetry_stats).
        """
        total_samples = min(len(mic_signal), len(loopback_signal))
        if total_samples < int(sample_rate * 0.5):
            return mic_signal, {"applied": False, "reason": "audio_too_short"}

        # 1. Estima o atraso temporal físico (tau) e correlação
        delay_samples, peak_corr = self.estimate_delay(
            mic_signal, loopback_signal, sample_rate=sample_rate
        )
        delay_ms = (delay_samples / sample_rate) * 1000.0

        stats: Dict[str, Any] = {
            "applied": False,
            "delay_ms": round(delay_ms, 2),
            "delay_samples": delay_samples,
            "peak_correlation": round(peak_corr, 4),
            "leakage_ratio": 0.0,
            "leakage_db": 0.0,
            "frames_suppressed_pct": 0.0,
        }

        # Se a correlação estiver abaixo do limiar, canais já estão isolados
        if peak_corr < self.min_correlation_threshold:
            logger.info(
                "EchoGate: baixa correlação entre canais (r=%.3f < %.3f). Isolamento acústico satisfatório.",
                peak_corr,
                self.min_correlation_threshold,
            )
            stats["reason"] = "correlation_below_threshold"
            return mic_signal, stats

        # 2. Alinha temporalmente o loopback para coincidir com o ponto em que atinge o mic
        aligned_loopback = np.zeros_like(mic_signal)
        if delay_samples < len(loopback_signal):
            aligned_len = min(len(mic_signal) - delay_samples, len(loopback_signal) - delay_samples)
            if aligned_len > 0:
                aligned_loopback[delay_samples : delay_samples + aligned_len] = loopback_signal[:aligned_len]

        # 3. Estima fator de acoplamento de vazamento
        leakage_ratio = self.estimate_leakage_ratio(mic_signal, aligned_loopback, sample_rate)
        leakage_db = 20.0 * np.log10(max(1e-4, leakage_ratio))
        stats["leakage_ratio"] = round(leakage_ratio, 4)
        stats["leakage_db"] = round(leakage_db, 2)

        # 4. Processamento quadro a quadro com ganho dinâmico e transições suaves
        frame_size = int(sample_rate * (self.frame_ms / 1000.0))
        num_frames = len(mic_signal) // frame_size

        if num_frames == 0:
            return mic_signal, stats

        target_gains = np.ones(num_frames, dtype=np.float32)
        min_gain = float(10.0 ** (self.suppression_db / 20.0))
        double_talk_factor = float(10.0 ** (self.double_talk_margin_db / 20.0))

        suppressed_count = 0

        for i in range(num_frames):
            idx = i * frame_size
            m_chunk = mic_signal[idx : idx + frame_size]
            l_chunk = aligned_loopback[idx : idx + frame_size]

            l_rms = float(np.sqrt(np.mean(l_chunk**2)))
            m_rms = float(np.sqrt(np.mean(m_chunk**2)))

            # Se o Teams estiver ativo
            if l_rms > 0.008:
                expected_leak_rms = leakage_ratio * l_rms
                # Se o microfone contiver apenas o reflexo do vazamento (sem voz forte do usuário)
                if m_rms <= (expected_leak_rms * double_talk_factor):
                    target_gains[i] = min_gain
                    suppressed_count += 1
                else:
                    # Double-talk: Usuário falando ao mesmo tempo, ganho normal
                    target_gains[i] = 1.0
            else:
                target_gains[i] = 1.0

        # Interpolação suave do ganho no nível de quadros (evita cliques sem alocar milhões de amostras)
        if num_frames >= 3:
            # Filtro de suavização ponderado em 3 quadros (~60ms) para transições graduais
            kernel = np.array([0.2, 0.6, 0.2], dtype=np.float32)
            smoothed_gains = np.convolve(target_gains, kernel, mode="same")
        else:
            smoothed_gains = target_gains

        # Aplicação dos ganhos em blocos contínuos (garante Zero-RAM mesmo em reuniões de várias horas)
        cleaned_mic = np.empty_like(mic_signal)
        chunk_frames = 2000  # Processa em blocos de até 2000 quadros (~40s) para manter buffer < 3 MB
        for f_start in range(0, num_frames, chunk_frames):
            f_end = min(num_frames, f_start + chunk_frames)
            s_start = f_start * frame_size
            s_end = f_end * frame_size
            block_gains = np.repeat(smoothed_gains[f_start:f_end], frame_size)
            cleaned_mic[s_start:s_end] = mic_signal[s_start:s_end] * block_gains

        # Preserva amostras residuais além do último quadro completo
        tail_start = num_frames * frame_size
        if tail_start < len(mic_signal):
            cleaned_mic[tail_start:] = mic_signal[tail_start:]

        suppressed_pct = (suppressed_count / num_frames) * 100.0 if num_frames > 0 else 0.0
        stats["applied"] = True
        stats["frames_suppressed_pct"] = round(suppressed_pct, 2)

        logger.info(
            "EchoGate aplicado com sucesso: atraso=%d ms (lag=%d), corr=%.3f, vazamento=%.1fdB (alpha=%.2f), quadros suprimidos=%.1f%%",
            delay_ms,
            delay_samples,
            peak_corr,
            leakage_db,
            leakage_ratio,
            suppressed_pct,
        )

        return cleaned_mic, stats
