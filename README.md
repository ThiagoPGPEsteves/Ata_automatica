# Ata Automática - Reuniões Teams

Sistema inteligente para captura/ingestão de reuniões do Microsoft Teams, transcrição de áudio com identificação de locutores e geração automatizada de atas estruturadas utilizando Inteligência Artificial (LLMs).

## 🚀 Objetivo do Projeto

Automatizar o ciclo completo pós-reunião:
1. **Entrada / Captura:** Recepção da gravação ou transcrição nativa da reunião realizada no Microsoft Teams.
2. **Transcrição & Diarização:** Conversão de voz para texto de alta fidelidade e segmentação por interlocutores (quem falou o quê).
3. **Processamento Inteligente:** Extração de tópicos abordados, decisões tomadas, itens de ação (action items) com responsáveis e prazos.
4. **Geração e Exportação:** Criação de atas formais em múltiplos formatos (DOCX, PDF, Markdown) e envio/integração automática.

## 🛠️ Arquitetura & Tecnologias Previstas

- **Linguagem Principal:** Python 3.11+
- **Transcrição / IA:** OpenAI Whisper / Azure Speech Services / Gemini / Groq / OpenAI GPT
- **Processamento de Áudio:** FFmpeg, PyDub
- **Formatação de Documentos:** python-docx, Weasyprint / ReportLab

---
*Projeto em fase de planejamento e especificação técnica.*
