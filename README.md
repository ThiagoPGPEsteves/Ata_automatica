# 🎙️ Ata Automática para Microsoft Teams

[![Python](https://img.shields.io/badge/Python-3.11%2B%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Plataforma](https://img.shields.io/badge/Plataforma-Windows%20WASAPI-0078D6.svg)](https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi)
[![Privacidade](https://img.shields.io/badge/Privacidade-100%25%20Offline%20(Local)-green.svg)](#-privacidade-absoluta-e-conformidade)
[![Memória RAM](https://img.shields.io/badge/Consumo%20de%20RAM-Pico%20%3C%20415%20MB-success.svg)](#-relatório-oficial-de-auditoria-de-memória-ram)
[![Status](https://img.shields.io/badge/Status-100%25%20Concluído%20%26%20Homologado-brightgreen.svg)](#)

Aplicação desktop executiva para Windows projetada para **capturar em tempo real o áudio de reuniões do Microsoft Teams**, transcrever com alta fidelidade (separando automaticamente a sua voz da voz dos demais participantes) e **gerar atas executivas formais prontas em formato Microsoft Word (`.docx`)**.

Tudo roda **100% localmente na máquina do usuário**, sem envio de dados para a nuvem e com respeito estrito a um orçamento máximo de **4.0 GB de memória RAM** (operando com pico auditado em apenas **413 MB** em laptops Intel Core i5).

---

## 🌟 Principais Diferenciais

- 🔒 **Privacidade Absoluta (100% Offline):** Nenhum byte de áudio, transcrição ou ata sai do computador. Não utiliza APIs externas pagas ou serviços em nuvem.
- ⚡ **Orçamento Estrito de Memória (< 4GB RAM):** Arquitetura baseada em **Pipeline Sequencial com Descarregamento Ativo (*Zero-Overlap*)**. Os modelos de IA nunca coexistem na RAM, permitindo rodar suavemente em paralelo com o Teams sem lentidão ou travamentos.
- 🎧 **Captura Dual Nativa via WASAPI:** Captura simultânea do **Microfone do Usuário (Canal 0)** e da **Saída do Teams via Loopback (Canal 1)** sem necessidade de instalar drivers virtuais adicionais (como Virtual Audio Cable ou VB-Cables).
- 🗣️ **Diarização Temporal com Custo Zero:** Separação precisa de quem falou o quê (`[Você]` vs `[Participantes do Teams]`) intercalando as intervenções cronologicamente com base em timestamps.
- 🗔 **Interface Desktop Leve em PyQt6:** Barra flutuante *Always-on-Top* arrastável sobre a reunião do Teams, com cronômetro digital, mini VU meter dual em tempo real e ícone na bandeja do Windows (*System Tray*).
- 📄 **Documentos Word Executivos (.docx):** Geração de documentos corporativos com paleta Azul Marinho (`#1F4E79`), resumo executivo, pautas, caixa de destaque (*callout*) para deliberações e tabela zebrada para a Matriz de Ações (O quê, Responsável, Prazo).

---

## 🏗️ Arquitetura do Pipeline Sequencial (Zero-Overlap)

Para garantir que o consumo de memória RAM permaneça sempre com folga abaixo do teto de 4.0 GB, os componentes pesados são executados de forma estritamente sequencial com liberação imediata de recursos:

```
[ Reunião no Teams ]
         │
         ├───► Canal 0: Microfone Local (Você)
         └───► Canal 1: Saída de Áudio WASAPI Loopback (Teams)
                   │
                   ▼
  1. GRAVAÇÃO EM STREAMING DIRETO NO DISCO (WAV)
     └── Memória RAM Estática: ~38 MB (Zero-RAM Buffer)
                   │
                   ▼
  2. TRANSCRIÇÃO LOCAL: faster-whisper (CPU int8)
     ├── Seleção Adaptativa: 'small' se RAM livre >= 1.5GB; fallback para 'base'
     ├── Remoção de Silêncios: Silero-VAD integrado
     └── Descarregamento Ativo: [del model; gc.collect()] ──► RAM volta para ~45 MB
                   │
                   ▼
  3. DIARIZAÇÃO & SINCRONIZAÇÃO CRONOLÓGICA
     └── Alinhamento de falas: [00:01:23] [Você] vs [Participantes da Reunião]
                   │
                   ▼
  4. GERAÇÃO DA ATA: Ollama Local (Llama 3.2 3B)
     ├── Envio obrigatório de "keep_alive": "0s"
     └── O modelo é purgado da RAM no segundo em que a geração termina!
                   │
                   ▼
  5. REVISÃO INTERATIVA & EXPORTAÇÃO (.docx)
     ├── Visualização e edição de pautas, decisões e matriz de ações
     └── Construtor Word oficial (python-docx corporativo)
```

---

## 📊 Relatório Oficial de Auditoria de Memória RAM

Durante os testes de homologação ponta a ponta (`tests/test_end_to_end.py`), o consumo de memória física (RSS) foi registrado continuamente via `psutil`:

| Etapa do Pipeline | Consumo Medido | Margem para o Teto (4.0 GB) |
|---|:---:|:---:|
| **0. Baseline Inicial do Processo** | 50.46 MB | 4.045 MB livres |
| **1. Gravação Dual em Disco (Streaming)** | 50.65 MB | 4.045 MB livres |
| **2. Separação de Canais WAV** | 51.52 MB | 4.044 MB livres |
| **3. faster-whisper Carregado em RAM (int8, small)** | **413.09 MB** | **3.682 MB livres** |
| **4. faster-whisper Descarregado (gc.collect)** | 135.80 MB | 3.960 MB livres |
| **5. Diarização e Alinhamento Temporal** | 135.80 MB | 3.960 MB livres |
| **6. Geração e Parsing da Ata (Ollama)** | 135.87 MB | 3.960 MB livres |
| **7. Exportação Concluída (.docx)** | 134.99 MB | 3.961 MB livres |

> [!TIP]
> **Pico Máximo Registrado:** **`413.09 MB`** (com mais de **3.68 GB de memória RAM livre** em todo o ciclo).

---

## ⚙️ Pré-Requisitos

1. **Sistema Operacional:** Windows 10 ou Windows 11 (64-bit).
2. **Python:** Versão 3.11 ou superior (homologado em Python 3.14 x64).
3. **Dispositivos de Áudio:** Microfone e saída de som/fone de ouvido em funcionamento.
4. **Ollama:** Instalado localmente com o modelo Llama 3.2 3B:
   - Baixe e instale em: [ollama.com](https://ollama.com/)
   - No terminal, baixe o modelo compacto otimizado:
     ```powershell
     ollama pull llama3.2:3b
     ```

---

## 🚀 Instalação Rápida

### 1. Clonar o Repositório
```powershell
git clone https://github.com/ThiagoPGPEsteves/Ata_automatica.git
cd Ata_automatica
```

### 2. Criar e Ativar o Ambiente Virtual
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Instalar as Dependências
```powershell
pip install -r requirements.txt
```

---

## 💻 Como Utilizar

### 1. Diagnóstico do Sistema (Pre-Flight Checks)
Antes de iniciar uma reunião importante, você pode validar se todos os dispositivos e serviços estão prontos:
```powershell
python run.py --check-only
```
O script verifica automaticamente o microfone WASAPI, o loopback do Teams, as pastas de gravação e a conexão com o Ollama.

### 2. Iniciar a Aplicação Oficial
Você pode iniciar por qualquer um dos métodos abaixo:
```powershell
# Método 1: Comando padrão (o script detecta e utiliza o .venv automaticamente)
python run.py

# Método 2: Script batch de atalho rápido (ou duplo clique no run.bat pelo Windows Explorer)
.\run.bat

# Método 3: Chamada direta do Python da .venv
.\.venv\Scripts\python.exe run.py
```
*(Para iniciar diretamente minimizado na bandeja do sistema, use `python run.py --minimized`)*

### 3. Durante a Reunião
1. A **Barra Flutuante** aparecerá no topo da tela (sempre visível sobre a janela cheia do Teams).
2. Clique no botão **`● Gravar`** assim que a reunião começar:
   - O cronômetro iniciará a contagem.
   - O **mini VU meter dual** mostrará as barras de nível sonoro em tempo real (barra superior = seu microfone; barra inferior = participantes do Teams).
3. Você pode clicar em **`❚❚ Pausar`** e **`▶ Retomar`** a qualquer momento.
4. Ao término da reunião, clique em **`■ Parar`**:
   - A barra flutuante passará para o estado de processamento.
   - A **Janela de Revisão Executiva** se abrirá exibindo o progresso detalhado da transcrição e da IA.
5. Na janela de revisão, confira e edite o título, as decisões tomadas e a tabela de ações.
6. Clique em **`💾 Exportar para Microsoft Word (.docx)`**:
   - O documento oficial formatado será salvo na pasta `output/` e aberto automaticamente no Microsoft Word!

---

## 📂 Estrutura de Diretórios do Projeto

```
Ata_automatica/
├── run.py                   # Ponto de entrada oficial com pre-flight checks e orquestração
├── requirements.txt         # Dependências fixadas otimizadas
├── plano.md                 # Especificação técnica e matriz de execução detalhada
├── README.md                # Documentação oficial do projeto
│
├── src/
│   ├── config.py            # Configurações de áudio, caminhos e limites de RAM
│   │
│   ├── audio/               # Módulo 1: Captura de áudio nativa
│   │   ├── devices.py       # Enumeração de dispositivos WASAPI (Mic e Loopback)
│   │   ├── disk_writer.py   # Streaming direto em disco (Zero-RAM buffer)
│   │   └── recorder.py      # Gravador dual assíncrono via callbacks
│   │
│   ├── transcription/       # Módulo 2: Transcrição e Diarização
│   │   ├── whisper_engine.py# faster-whisper CPU int8 com descarregamento de memória
│   │   └── post_process.py  # Separação de canais e sincronização por timestamps
│   │
│   ├── minutes/             # Módulo 3: Geração da Ata com IA
│   │   ├── ollama_client.py # Cliente REST local com keep_alive: "0s"
│   │   ├── prompts.py       # Templates corporativos formais em português
│   │   └── parser.py        # Parser estruturado da ata e tabela de ações
│   │
│   ├── exporter/            # Módulo 4: Construtor Word Executivo
│   │   ├── styles.py        # Paleta Azul Marinho (#1F4E79), tipografia e XML shading
│   │   └── docx_builder.py  # Construtor do documento .docx
│   │
│   └── ui/                  # Módulo 5: Interface Desktop Nativa (PyQt6)
│       ├── floating_widget.py # Barra flutuante Always-on-Top com cronômetro e VU meter
│       ├── tray_icon.py       # Ícone na bandeja do Windows com menu de contexto
│       ├── review_dialog.py   # Janela executiva de revisão, edição e exportação
│       └── worker_threads.py  # QThread isolando processamento pesado da interface
│
├── tests/                   # Bateria de Testes Automatizados
│   ├── test_audio_recording.py # Testes do gravador WASAPI e streaming em disco
│   ├── test_transcription.py   # Testes do faster-whisper e liberação de RAM
│   ├── test_minutes.py         # Testes de prompts corporativos e parser estruturado
│   ├── test_exporter.py        # Testes de estilos, tabelas zebradas e exportação DOCX
│   ├── test_ui.py              # Testes headless de widgets, máquina de estados e memória
│   └── test_end_to_end.py      # Teste integrado ponta a ponta com auditoria contínua de RAM
│
├── temp/                    # Arquivos temporários de áudio (ignorado no git)
└── output/                  # Documentos Word gerados (.docx)
```

---

## 🧪 Bateria de Testes Automatizados

Cada módulo do sistema possui uma suíte de testes dedicada:

```powershell
# 1. Testar Gravação Dual WASAPI e Zero-RAM Buffer
python tests/test_audio_recording.py

# 2. Testar faster-whisper, Diarização e Descarregamento de RAM
python tests/test_transcription.py

# 3. Testar Prompts Corporativos e Parser de Atas do Ollama
python tests/test_minutes.py

# 4. Testar Construtor de Documentos Word (.docx)
python tests/test_exporter.py

# 5. Testar Interface Gráfica PyQt6 (Modo Headless Offscreen)
python tests/test_ui.py

# 6. Testar Ciclo Completo Ponta a Ponta com Auditoria de Memória
python tests/test_end_to_end.py
```

---

## 📄 Licença e Privacidade

Este projeto é desenvolvido para uso corporativo interno com garantia de **privacidade por design (*Privacy by Design*)**. Todas as operações de captura de áudio, transcrição e inteligência artificial são executadas estritamente de forma local no hardware do usuário.
