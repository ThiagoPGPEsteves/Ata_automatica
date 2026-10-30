# 🎙️ Ata Automática para Microsoft Teams

[![Python](https://img.shields.io/badge/Python-3.11%2B%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Plataforma](https://img.shields.io/badge/Plataforma-Windows%20WASAPI-0078D6.svg)](https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi)
[![Privacidade](https://img.shields.io/badge/Privacidade-100%25%20Offline%20(Local)-green.svg)](#-privacidade-absoluta-e-conformidade)
[![Memória RAM](https://img.shields.io/badge/Consumo%20de%20RAM-Pico%20%3C%20415%20MB-success.svg)](#-relatório-oficial-de-auditoria-de-memória-ram)
[![Testes Automatizados](https://img.shields.io/badge/Testes-98%20Passando%20(100%25)-brightgreen.svg)](#-bateria-de-testes-automatizados)
[![Status](https://img.shields.io/badge/Status-100%25%20Concluído%20%26%20Homologado-brightgreen.svg)](#)

Aplicação desktop executiva para Windows projetada para **capturar em tempo real o áudio de reuniões do Microsoft Teams**, transcrever com alta fidelidade (separando automaticamente a sua voz da voz dos demais participantes), **gerar atas executivas formais prontas em formato Microsoft Word (`.docx`)**, **rascunhos estruturados no Microsoft Outlook** e **consultar qualquer reunião passada em linguagem natural ("Pergunte às suas atas")**.

Tudo roda **100% localmente na máquina do usuário**, sem envio de dados para a nuvem e com respeito estrito a um orçamento máximo de **4.0 GB de memória RAM** (operando com pico auditado em apenas **413 MB** em laptops Intel Core i5).

---

## 🌟 Principais Diferenciais

- 🔒 **Privacidade Absoluta (100% Offline):** Nenhum byte de áudio, transcrição ou ata sai do computador. Não utiliza APIs externas pagas ou serviços em nuvem.
- ⚡ **Orçamento Estrito de Memória (< 4GB RAM):** Arquitetura baseada em **Pipeline Sequencial com Descarregamento Ativo (*Zero-Overlap*)**. Os modelos de IA nunca coexistem na RAM, permitindo rodar suavemente em paralelo com o Teams sem lentidão ou travamentos.
- 🔎 **"Pergunte às suas atas" (RAG Local):** Motor semântico com SQLite + nomic-embed-text e síntese Llama 3.2 3B com citações rastreáveis `[F1, F2...]` (falantes e minuto exato), 100% de acurácia de citação auditada e rejeição total de alucinações.
- 🎧 **Captura Dual Nativa via WASAPI:** Captura simultânea do **Microfone do Usuário (Canal 0)** e da **Saída do Teams via Loopback (Canal 1)** sem necessidade de instalar drivers virtuais adicionais (como Virtual Audio Cable ou VB-Cables).
- 🗣️ **Diarização Temporal com Custo Zero:** Separação precisa de quem falou o quê (`[Você]` vs `[Participantes do Teams]`) intercalando as intervenções cronologicamente com base em timestamps.
- 🌐 **Filtro Acústico de Eco Multilíngue:** Algoritmo pós-transcrição de supressão de eco com conjunto estendido de stopwords em **Português, Espanhol e Inglês**, protegendo a fala genuína do usuário em reuniões bilaterais ou multinacionais.
- 📧 **Envio Direto por E-mail no Outlook (1-Click Draft):** Despachador nativo via automação COM (`OutlookDispatcher`) que gera automaticamente uma nova mensagem no Outlook com layout corporativo em HTML e o arquivo oficial `.docx` anexado.
- 📝 **Modos de Documento Flexíveis:** Alternância na interface entre **Ata Executiva Formal** (com deliberações e tabela zebrada de matriz de ações) e **Resumo de Temas** (sem blocos vazios, focado em discussões e pautas gerais).
- 🗔 **Interface Desktop Leve em PyQt6:** Barra flutuante *Always-on-Top* arrastável sobre a reunião do Teams, com cronômetro digital, mini VU meter dual em tempo real e menu de contexto completo na bandeja do Windows (*System Tray*) com opção de reabrir a revisão a qualquer momento.
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
     ├── Filtro Acústico Multilíngue de Eco (PT / ES / EN)
     └── Descarregamento Ativo: [del model; gc.collect()] ──► RAM volta para ~45 MB
                   │
                   ▼
  3. DIARIZAÇÃO & SINCRONIZAÇÃO CRONOLÓGICA
     └── Alinhamento de falas: [00:01:23] [Você] vs [Participantes da Reunião]
                   │
                   ▼
  4. GERAÇÃO DA ATA: Ollama Local (Llama 3.2 3B)
     ├── Envio obrigatório de "keep_alive": "0s"
     ├── Streaming contínuo de tokens na interface
     └── O modelo é purgado da RAM no segundo em que a geração termina!
                   │
                   ▼
  5. REVISÃO INTERATIVA & EXPORTAÇÃO
     ├── Visualização e edição de pautas, decisões e matriz de ações
     ├── Construtor Word oficial (python-docx corporativo)
     └── Despachador nativo para Microsoft Outlook (HTML executivo + .docx)
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
4. **Ollama:** Instalado localmente com os modelos oficiais (Llama 3.2 3B para atas e nomic-embed-text para RAG):
   - Baixe e instale em: [ollama.com](https://ollama.com/)
   - No terminal, baixe os modelos otimizados:
     ```powershell
     ollama pull llama3.2:3b
     ollama pull nomic-embed-text
     ```
5. *(Opcional)* **Microsoft Outlook:** Para utilização do botão de envio direto de e-mail com anexo. Caso não esteja instalado, a aplicação conta com fallback automático para o cliente de e-mail padrão do Windows ou abertura direta da pasta do documento.

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
1. A **Barra Flutuante** aparecerá no topo da tela (sempre visível sobre a janela do Teams).
2. Clique no botão **`● Gravar`** assim que a reunião começar:
   - Uma sessão isolada e persistente é alocada em `sessions/AAAA-MM-DD_HHMMSS/`.
   - O áudio é gravado diretamente na pasta da sessão (*Zero-Copy streaming*).
   - O cronômetro iniciará a contagem.
   - O **mini VU meter dual** mostrará as barras de nível sonoro em tempo real (barra superior = seu microfone; barra inferior = participantes do Teams).
3. Você pode clicar em **`❚❚ Pausar`** e **`▶ Retomar`** a qualquer momento.
4. Ao término da reunião, clique em **`■ Parar`**:
   - A barra flutuante passará para o estado de processamento.
   - A **Janela de Revisão Executiva** se abrirá exibindo o progresso detalhado da transcrição e da IA.
5. Na janela de revisão:
   - Escolha o formato desejado no seletor: **"Ata de Reunião Executiva"** ou **"Resumo de Temas"**.
   - Revise e edite livremente o título, data, participantes, resumo, decisões e tabela de ações.
6. Ações de Exportação e Distribuição:
   - **`💾 Exportar para Microsoft Word (.docx)`**: Salva o documento oficial formatado na pasta `output/` e abre diretamente no Word.
   - **`📧 Enviar por Outlook`**: Cria instantaneamente uma mensagem no Outlook pronta para envio, com assunto, corpo executivo em HTML e o arquivo `.docx` já anexado.
7. Se você fechar a janela sem querer, basta clicar com o botão direito no ícone da bandeja do Windows e selecionar **"📄 Visualizar / Exportar Ata Atual..."** para reabri-la imediatamente.

---

## 🛠️ Comandos de Linha de Comando (CLI Headless)

A aplicação conta com uma CLI completa para automação, reprocessamento e governança de dados:

```powershell
# 1. Listar todas as reuniões gravadas e seus artefatos (áudio, transcrição, ata, docx)
python run.py --list-sessions

# 2. Reprocessar uma reunião a partir de uma etapa específica sem reabrir a interface
python run.py --reprocess 2026-10-16_114213 --from-stage export
python run.py --reprocess 2026-10-16_114213 --from-stage generate

# 3. Executar o expurgo automático de áudios antigos (LGPD - padrão: 7 dias)
python run.py --cleanup-audio
python run.py --cleanup-audio --retention-days 14

# 4. Diagnóstico Clínico de Áudio e Crosstalk (Fase P3)
python tools/diagnose_audio.py
python tools/diagnose_audio.py --file sessions/2026-10-16_114213/audio.wav

# 5. Benchmark Científico de Desempenho e Recursos (Fase P4)
python tools/benchmark_performance.py
python tools/benchmark_performance.py --file sessions/2026-10-16_114213/audio.wav --models small

# 7. Perguntar às reuniões gravadas em linguagem natural (RAG Local)
python run.py --ask "O que ficou decidido sobre o prazo do projeto QCCP?"
python run.py --ask "Qual o orçamento dos servidores?" --session 2026-10-15_100000 --top-k 3

# 8. Indexação vetorial e estatísticas do RAG
python run.py --rag-index
python run.py --rag-index --session 2026-10-15_100000
python run.py --rag-stats

# 9. Expurgo LGPD de uma reunião no índice vetorial (Direito ao Esquecimento)
python run.py --rag-forget 2026-10-15_100000

# 10. Benchmark Científico e Auditoria de RAG (Ground Truth)
python tools/benchmark_rag.py
python tools/benchmark_rag.py --retrieval-only
```

---

## 🔎 Pergunte às suas atas (RAG Local)

O Ata Automática conta com um motor completo de **Geração Aumentada por Recuperação (RAG)** operando **100% offline**, permitindo ao usuário fazer perguntas em linguagem natural sobre o histórico de atas e transcrições de reuniões gravadas.

### Arquitetura Sequencial Zero-Overlap

Para garantir que o consumo de memória RAM permaneça estritamente dentro do orçamento regulatório de **4.0 GB de RAM**, a recuperação e a síntese executam de forma estritamente sequencial com liberação imediata de memória (*Zero-Overlap*):

```
                       [ Pergunta do Usuário ]
                                  │
                                  ▼
      1. EMBEDDER EM RAM: Ollama ('nomic-embed-text', 768 dims)
         ├── Vetorização densa da pergunta em float32
         ├── Normalização euclidiana L2 (dot product == cosine similarity)
         └── Descarregamento Ativo: keep_alive: "0s" ──► Libera RAM imediatamente!
                                  │
                                  ▼
      2. BUSCA VETORIAL EXATA: SQLite Embarcado (sessions/rag_index.sqlite)
         ├── Varredura com NumPy Matrix Multiplication em milissegundos
         ├── Filtragem opcional por reunião (--session) e corte por limiar (>= 0.35)
         └── Recupera Chunks: Janelas de transcrição com timestamps e falantes
             + Resumo, Deliberações e Matriz de Ações da Ata Oficial
                                  │
                                  ▼
      3. SÍNTESE COM IA: Ollama ('llama3.2:3b')
         ├── Prompt ancorado com identificadores explícitos de fontes [F1, F2...]
         ├── Parsing JSON Schema garantido (answer, citations, found)
         ├── Validação anti-alucinação: se fora de escopo, retorna found=false
         └── Descarregamento Ativo: keep_alive: "0s" ──► Libera RAM imediatamente!
                                  │
                                  ▼
      [ Resposta Executiva com Citações Rastreáveis [F1] de Falante e Horário ]
```

### Resultados Científicos Oficiais de Benchmark (Ground Truth)

Medido através da ferramenta oficial `tools/benchmark_rag.py` com o dataset anotado `tests/fixtures/rag_eval.json` (3 sessões completas, 19 perguntas de teste com ground truth):

| Métrica de Avaliação | Valor Medido | Referência Técnica |
|---|:---:|---|
| **Recall@1** | **80.0 %** | Top-1 recuperado contém a evidência ground truth |
| **Recall@3** | **100.0 %** | Top-3 recuperado contém a evidência ground truth |
| **Recall@6** | **100.0 %** | Top-6 recuperado contém a evidência ground truth |
| **MRR (Mean Reciprocal Rank)** | **0.8778** | Alta qualidade no ordenamento de relevância semântica |
| **Acurácia de Citação Válida** | **100.0 %** | Respostas fundamentadas com fontes [F1, F2] auditadas |
| **Rejeição de Alucinação (`found=false`)** | **100.0 %** | Rejeição correta para 4 de 4 perguntas fora do escopo |
| **Latência Média de Embedding** | **2.69 s** | `nomic-embed-text` via Ollama local |
| **Latência Média de Busca SQLite** | **2.70 ms** | Similaridade de cosseno via NumPy no banco local |
| **Pico de Memória RAM (App Python)** | **59.6 MB** | Processo Python |
| **Pico de Memória RAM (Pipeline Consolidado)** | **102.8 MB** | App + Daemon Ollama (Teto: 4.096 MB) |
| **Status do Orçamento de RAM** | **APROVADO** | Folga de mais de 3.99 GB de RAM durante todo o RAG |

### Governança e Privacidade (LGPD by Design)

- **Armazenamento 100% Local:** O banco vetorial fica em `sessions/rag_index.sqlite` no próprio computador.
- **Indexação Incremental Atômica:** Cada reunião tem um hash SHA-256 de seu conteúdo (`transcript.json` + `minutes.json`). Apenas sessões novas ou modificadas são reindexadas, economizando CPU.
- **Expurgo Rápido (Direito ao Esquecimento):** O comando `python run.py --rag-forget <session_id>` remove imediatamente todos os chunks e vetores da sessão do banco de dados SQLite.

---

## 📂 Estrutura de Diretórios do Projeto

```
Ata_automatica/
├── run.py                   # Ponto de entrada oficial (GUI PyQt6 e CLI Headless)
├── tools/
│   ├── diagnose_audio.py    # Ferramenta clínica de diagnóstico de eco e crosstalk
│   ├── benchmark_performance.py # Benchmark de desempenho, RTF e auditoria de RAM
│   ├── benchmark_transcription.py # Benchmark de precisão, WER, CER e hotwords
│   └── benchmark_rag.py     # Benchmark científico de RAG (Recall@k, MRR, Citações e RAM)
├── requirements.txt         # Dependências fixadas de produção
├── requirements-dev.txt     # Dependências de desenvolvimento e testes
├── pytest.ini               # Configuração formal do Pytest com marcadores unit/integration
├── plano.md                 # Especificação técnica e matriz de execução detalhada
├── README.md                # Documentação oficial do projeto
│
├── src/
│   ├── config.py            # Configurações de áudio, caminhos, UserSettings atômicas e limites de RAM
│   │
│   ├── pipeline/            # Módulo de Orquestração Agnóstica
│   │   ├── session.py       # SessionStore e MeetingSession com manifests e expurgo LGPD
│   │   └── meeting_pipeline.py # Orquestrador desacoplado com integração do EchoGate, telemetria e RAG
│   │
│   ├── audio/               # Módulo 1: Captura de áudio nativa
│   │   ├── devices.py       # Enumeração WASAPI com priorização de Microfone Array
│   │   ├── disk_writer.py   # Streaming direto em disco (Zero-RAM buffer)
│   │   ├── recorder.py      # Gravador dual assíncrono blindado contra race conditions
│   │   └── echo_gate.py     # EchoGate: cancelamento digital de eco e crosstalk com convolução leve
│   │
│   ├── transcription/       # Módulo 2: Transcrição e Diarização
│   │   ├── whisper_engine.py# faster-whisper CPU int8 com guarda contra None em language_probability
│   │   └── post_process.py  # Separação de canais e filtro acústico de eco multilíngue (PT/ES/EN)
│   │
│   ├── minutes/             # Módulo 3: Geração da Ata com IA
│   │   ├── ollama_client.py # Cliente REST local com streaming resiliente e timeouts adaptativos
│   │   ├── prompts.py       # Templates corporativos formais para Atas e Resumos de Temas
│   │   ├── parser.py        # Parser estruturado da ata, validação de JSON e tabela de ações
│   │   └── generator.py     # MinutesGenerator adaptativo (Single-pass e Map-Reduce com fallback)
│   │
│   ├── exporter/            # Módulo 4: Construtor Word e Despacho de E-mail
│   │   ├── styles.py        # Paleta Azul Marinho (#1F4E79), tipografia e XML shading
│   │   ├── docx_builder.py  # Construtor do documento oficial Word (.docx)
│   │   └── outlook_dispatcher.py # Despacho nativo de e-mail no Outlook via COM com anexo .docx
│   │
│   ├── rag/                 # Módulo 5: Pergunte às suas atas (RAG Local Zero-Overlap)
│   │   ├── embedder.py      # Embedder nomic-embed-text com normalização L2 e keep_alive: "0s"
│   │   ├── chunker.py       # Janelamento com overlap e extração estruturada de atas
│   │   ├── store.py         # VectorStore SQLite nativo com hash SHA256 e exclusão LGPD
│   │   ├── retriever.py     # Recuperador semântico com ordenamento e corte por limiar
│   │   ├── answerer.py      # Síntese fundamentada com citações [F1] e JSON Schema
│   │   └── service.py       # Orquestrador Zero-Overlap (Embedder -> SQLite -> LLM)
│   │
│   ├── utils/               # Módulo de Utilitários e Telemetria
│   │   ├── telemetry.py     # SystemMemoryAuditor (App+Ollama), RTFEstimator e VAD
│   │   └── text_metrics.py  # Cálculo nativo de Word Error Rate (WER), CER e Levenshtein
│   │
│   └── ui/                  # Módulo 6: Interface Desktop Nativa (PyQt6)
│       ├── floating_widget.py # Barra flutuante Always-on-Top com cronômetro e VU meter
│       ├── tray_icon.py       # Ícone na bandeja do Windows com ação de reabertura da ata
│       ├── review_dialog.py   # Janela executiva com botões de exportação Word e envio Outlook
│       ├── audio_settings_dialog.py # Diálogo de configuração de áudio e parâmetros do usuário
│       └── worker_threads.py  # QThread fino adaptando MeetingPipeline para a UI
│
├── tests/                   # Bateria de testes automatizados
│   ├── fixtures/            # Áudios, transcrições e dataset rag_eval.json (Ground Truth)
│   ├── conftest.py          # Fixtures reutilizáveis de áudio e mocks
│   └── test_*.py            # Suíte completa com 98 testes automatizados (100% aprovados)
├── sessions/                # Histórico de reuniões e rag_index.sqlite (ignorado no git)
├── logs/                    # Logs rotativos da aplicação (app.log)
├── temp/                    # Arquivos temporários de áudio (ignorado no git)
└── output/                  # Documentos Word gerados (.docx)
```

---

## 🧪 Bateria de Testes Automatizados

O projeto utiliza **pytest** para validação contínua e engenharia de qualidade com **79 testes automatizados**:

```powershell
# 1. Executar apenas os testes unitários rápidos (< 5 segundos, sem hardware nem rede)
.venv\Scripts\pytest -m unit -v

# 2. Executar os testes de integração
.venv\Scripts\pytest -m integration -v

# 3. Executar toda a suíte de 79 testes automatizados (100% de sucesso)
.venv\Scripts\pytest tests/ -v

# 4. Execução rápida e silenciosa
.venv\Scripts\pytest -q
```

---

## 📄 Licença e Privacidade (LGPD by Design)

Este projeto foi construído para uso corporativo com garantia de **privacidade por design (*Privacy by Design*)**:
1. **100% Offline e Local**: Todas as operações de captura de áudio, transcrição Whisper e inferência do Ollama são executadas na máquina do usuário, sem transmissão de pacotes para a nuvem.
2. **Isolamento por Sessão**: Cada reunião possui seus dados salvos em uma pasta exclusiva e identificada.
3. **Política de Retenção de Áudio**: Arquivos de áudio brutos (`audio.wav`) podem ser expurgados automaticamente após 7 dias via `python run.py --cleanup-audio`, preservando a transcrição e o documento oficial de ata.

