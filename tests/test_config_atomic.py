"""
Testes automatizados para a gravação atômica e resiliência de config_user.json.
Valida:
- Gravação atômica com tempfile e os.replace
- Preservação de dados e schema_version
- Ausência de arquivos .tmp órfãos em caso de erro
- Fallback seguro para configurações padrão se o JSON estiver corrompido
"""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from src.config import (
    save_user_settings,
    get_typed_user_settings,
    get_user_settings,
    UserSettings,
)

pytestmark = pytest.mark.unit


def test_save_user_settings_atomic(tmp_path):
    """Valida gravação atômica e leitura consistente."""
    test_config_file = tmp_path / "config_user.json"

    with patch("src.config.USER_CONFIG_PATH", test_config_file):
        # 1. Salva novas configurações
        success = save_user_settings({
            "user_speaker_name": "Thiago Teste",
            "output_format": "theme_summary",
            "mic_device_id": 2,
        })
        assert success is True
        assert test_config_file.exists()

        # 2. Lê de volta e confere campos
        loaded = get_typed_user_settings()
        assert loaded.user_speaker_name == "Thiago Teste"
        assert loaded.output_format == "theme_summary"
        assert loaded.mic_device_id == 2
        assert loaded.schema_version == 1

        # 3. Confere que nenhum arquivo .tmp ficou órfão no diretório
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


def test_save_user_settings_cleans_up_on_failure(tmp_path):
    """Valida que em caso de falha durante a escrita, arquivos .tmp são removidos e retorna False."""
    test_config_file = tmp_path / "config_user.json"

    with patch("src.config.USER_CONFIG_PATH", test_config_file):
        # Simula falha no json.dump
        with patch("json.dump", side_effect=IOError("Erro simulado de disco")):
            success = save_user_settings({"user_speaker_name": "Crash Test"})
            assert success is False

        # Verifica que nenhum .tmp foi deixado para trás
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0
        assert not test_config_file.exists()


def test_get_typed_user_settings_corrupted_file_fallback(tmp_path):
    """Valida que um arquivo JSON truncado/corrompido não quebra a aplicação e recorre aos defaults."""
    corrupted_file = tmp_path / "config_user.json"
    corrupted_file.write_text("{\"corrupted_json\": [incomplete...", encoding="utf-8")

    with patch("src.config.USER_CONFIG_PATH", corrupted_file):
        settings = get_typed_user_settings()
        assert isinstance(settings, UserSettings)
        assert settings.user_speaker_name == "Você"
        assert settings.output_format == "minutes"
