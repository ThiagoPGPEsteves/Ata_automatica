"""
Módulo de Integração e Despacho de E-mail via Microsoft Outlook.
Utiliza automação COM nativa do Windows (via PowerShell) sem exigir
novas dependências externas, gerando rascunhos com corpo em HTML executivo
e anexo do documento Word (.docx) oficial.
"""

import os
import json
import html
import logging
import tempfile
import subprocess
import webbrowser
import urllib.parse
from pathlib import Path
from typing import Tuple, Optional, List, Union

from src.minutes.parser import MeetingMinutes

logger = logging.getLogger(__name__)


class OutlookDispatcher:
    """
    Despachador corporativo para criação de e-mails no Microsoft Outlook.
    Gera rascunhos pré-formatados com anexo .docx oficial.
    """

    def __init__(self, timeout_sec: float = 20.0):
        self.timeout_sec = timeout_sec

    def is_outlook_available(self) -> bool:
        """Verifica se o Microsoft Outlook está instalado e acessível via COM."""
        ps_cmd = """
        try {
            $outlook = New-Object -ComObject Outlook.Application
            if ($outlook.Version) {
                Write-Output "OK"
            }
        } catch {
            Write-Output "FAIL"
        }
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            return "OK" in res.stdout
        except Exception as e:
            logger.debug("Outlook COM indisponível: %s", e)
            return False

    def build_email_subject(self, minutes: MeetingMinutes) -> str:
        """Gera o assunto padrão do e-mail com base no tipo e data do documento."""
        prefix = "Resumo de Temas" if minutes.is_theme_summary else "Ata de Reunião Executiva"
        date_str = minutes.date.strip() if minutes.date else "Data Recente"
        title_str = minutes.title.strip() if minutes.title else "Microsoft Teams"
        return f"{prefix}: {title_str} - {date_str}"

    def build_email_html(self, minutes: MeetingMinutes, docx_filename: str = "") -> str:
        """
        Gera um template HTML executivo elegante para o corpo do e-mail,
        alinhado à paleta corporativa (#1F4E79 Azul Marinho, #2E75B6 Azul Aço).
        Compatível com todas as versões do Outlook Desktop, New Outlook e Web.
        """
        title = html.escape(minutes.title or "Ata de Reunião Executiva")
        date_str = html.escape(minutes.date or "N/A")
        participants_str = (
            html.escape(", ".join(minutes.participants))
            if minutes.participants
            else "Participantes da Reunião"
        )
        doc_type_label = (
            "Resumo dos Temas Discutidos"
            if minutes.is_theme_summary
            else "Ata de Reunião Executiva"
        )

        # 1. Resumo Executivo
        summary_html = ""
        if minutes.executive_summary.strip():
            esc_summary = html.escape(minutes.executive_summary.strip()).replace("\n", "<br>")
            summary_html = f"""
            <div style="margin-bottom: 20px;">
                <h3 style="color: #1F4E79; font-size: 15px; margin-bottom: 6px; border-bottom: 2px solid #2E75B6; padding-bottom: 4px;">
                    1. RESUMO EXECUTIVO
                </h3>
                <div style="background-color: #F8FAFC; border-left: 4px solid #2E75B6; padding: 12px 16px; font-size: 13px; line-height: 1.6; color: #262626;">
                    {esc_summary}
                </div>
            </div>
            """

        # 2. Deliberações e Decisões
        decisions_html = ""
        if minutes.decisions:
            items_li = "".join(
                f"<li style='margin-bottom: 6px;'>{html.escape(d)}</li>"
                for d in minutes.decisions
            )
            decisions_html = f"""
            <div style="margin-bottom: 20px;">
                <h3 style="color: #1F4E79; font-size: 15px; margin-bottom: 6px; border-bottom: 2px solid #2E75B6; padding-bottom: 4px;">
                    2. DELIBERAÇÕES E DECISÕES
                </h3>
                <div style="background-color: #EBF3FA; border: 1px solid #CBD5E1; border-radius: 4px; padding: 12px 16px;">
                    <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: #1F4E79; line-height: 1.5;">
                        {items_li}
                    </ul>
                </div>
            </div>
            """

        # 3. Tópicos Discutidos (se houver tópicos e não for apenas resumo)
        topics_html = ""
        if minutes.topics:
            topic_cards = []
            for t in minutes.topics:
                t_title = html.escape(t.get("title", "Tópico"))
                t_desc = html.escape(t.get("description", "")).replace("\n", "<br>")
                topic_cards.append(
                    f"<div style='margin-bottom: 10px; font-size: 13px;'>"
                    f"<strong style='color: #1F4E79;'>• {t_title}:</strong> "
                    f"<span style='color: #333333;'>{t_desc}</span>"
                    f"</div>"
                )
            topics_html = f"""
            <div style="margin-bottom: 20px;">
                <h3 style="color: #1F4E79; font-size: 15px; margin-bottom: 6px; border-bottom: 2px solid #2E75B6; padding-bottom: 4px;">
                    TÓPICOS PRINCIPAIS
                </h3>
                <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; padding: 12px 16px; border-radius: 4px;">
                    {"".join(topic_cards)}
                </div>
            </div>
            """

        # 4. Plano de Ação e Responsabilidades
        actions_html = ""
        if minutes.action_items:
            rows = []
            for i, item in enumerate(minutes.action_items):
                bg = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"
                rows.append(
                    f"""
                    <tr style="background-color: {bg};">
                        <td style="padding: 8px 12px; border: 1px solid #CBD5E1; font-size: 12px; color: #262626;">{html.escape(item.action)}</td>
                        <td style="padding: 8px 12px; border: 1px solid #CBD5E1; font-size: 12px; color: #1F4E79; font-weight: bold;">{html.escape(item.owner)}</td>
                        <td style="padding: 8px 12px; border: 1px solid #CBD5E1; font-size: 12px; color: #D9534F; font-weight: bold;">{html.escape(item.deadline)}</td>
                    </tr>
                    """
                )
            actions_html = f"""
            <div style="margin-bottom: 20px;">
                <h3 style="color: #1F4E79; font-size: 15px; margin-bottom: 8px; border-bottom: 2px solid #2E75B6; padding-bottom: 4px;">
                    3. PLANO DE AÇÃO E RESPONSABILIDADES
                </h3>
                <table style="width: 100%; border-collapse: collapse; text-align: left; font-family: Segoe UI, Calibri, sans-serif;">
                    <thead>
                        <tr style="background-color: #1F4E79; color: #FFFFFF;">
                            <th style="padding: 9px 12px; border: 1px solid #1F4E79; font-size: 12px;">Ação / Tarefa</th>
                            <th style="padding: 9px 12px; border: 1px solid #1F4E79; font-size: 12px; width: 140px;">Responsável</th>
                            <th style="padding: 9px 12px; border: 1px solid #1F4E79; font-size: 12px; width: 110px;">Prazo</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(rows)}
                    </tbody>
                </table>
            </div>
            """

        # 5. Caixa Informativa de Anexo
        anexo_info = html.escape(docx_filename) if docx_filename else "documento Word anexado"
        attachment_notice = f"""
        <div style="background-color: #F1F5F9; border: 1px dashed #2E75B6; border-radius: 4px; padding: 12px 16px; margin-top: 25px; margin-bottom: 20px;">
            <p style="margin: 0; font-size: 12px; color: #1E293B;">
                📎 <strong>Documento Oficial Anexado:</strong> <code>{anexo_info}</code><br>
                <span style="color: #64748B;">Para detalhes integrais, histórico contextual e visualização em formato executivo pronto para impressão, consulte o arquivo Microsoft Word (.docx) em anexo.</span>
            </p>
        </div>
        """

        # Estrutura completa do e-mail
        email_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{
                    font-family: 'Segoe UI', Calibri, Arial, sans-serif;
                    color: #262626;
                    background-color: #FFFFFF;
                    margin: 0;
                    padding: 10px;
                }}
            </style>
        </head>
        <body>
            <div style="max-width: 720px; margin: 0 auto; border: 1px solid #E2E8F0; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08);">
                <!-- Banner Superior -->
                <div style="background-color: #1F4E79; padding: 18px 24px; color: #FFFFFF;">
                    <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #93C5FD; font-weight: bold;">
                        {doc_type_label}
                    </span>
                    <h2 style="margin: 4px 0 0 0; font-size: 20px; font-weight: 600; color: #FFFFFF;">
                        {title}
                    </h2>
                </div>

                <!-- Barra de Metadados -->
                <div style="background-color: #F1F5F9; padding: 10px 24px; font-size: 12px; color: #475569; border-bottom: 1px solid #E2E8F0;">
                    <strong>Data:</strong> {date_str} &nbsp;|&nbsp; 
                    <strong>Participantes:</strong> {participants_str}
                </div>

                <!-- Conteúdo -->
                <div style="padding: 24px; font-family: 'Segoe UI', Calibri, Arial, sans-serif;">
                    {summary_html}
                    {decisions_html}
                    {topics_html}
                    {actions_html}
                    {attachment_notice}
                </div>

                <!-- Rodapé -->
                <div style="background-color: #F8FAFC; padding: 12px 24px; font-size: 11px; color: #94A3B8; border-top: 1px solid #E2E8F0; text-align: center;">
                    Documento gerado automaticamente pelo sistema <strong>Ata Automática Teams</strong> (IA Local e Offline).
                </div>
            </div>
        </body>
        </html>
        """
        return email_body.strip()

    def create_outlook_draft(
        self,
        minutes: MeetingMinutes,
        docx_path: Union[str, Path],
        display: bool = True,
        to_recipients: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Cria uma mensagem no Microsoft Outlook com assunto, corpo HTML e anexo .docx.
        Se display=True, exibe a janela de composição para o usuário revisar e enviar.
        Retorna (sucesso: bool, mensagem: str).
        """
        target_path = Path(docx_path).resolve()
        if not target_path.exists():
            return False, f"Arquivo de anexo não encontrado: {target_path}"

        subject = self.build_email_subject(minutes)
        html_body = self.build_email_html(minutes, docx_filename=target_path.name)

        # Salva o payload em JSON temporário para comunicação 100% segura com PowerShell
        payload = {
            "subject": subject,
            "html_body": html_body,
            "attachment": str(target_path),
            "display": display,
            "to_recipients": to_recipients or [],
        }

        temp_json = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                encoding="utf-8",
                delete=False,
            ) as jf:
                json.dump(payload, jf, ensure_ascii=False, indent=2)
                temp_json = Path(jf.name).resolve()

            ps_script = f"""
            $ErrorActionPreference = 'Stop'
            try {{
                $raw = [System.IO.File]::ReadAllText('{str(temp_json)}', [System.Text.Encoding]::UTF8)
                $data = $raw | ConvertFrom-Json
                $outlook = New-Object -ComObject Outlook.Application
                $mail = $outlook.CreateItem(0)
                $mail.Subject = $data.subject
                $mail.HTMLBody = $data.html_body
                
                if ($data.to_recipients -and $data.to_recipients.Count -gt 0) {{
                    $mail.To = ($data.to_recipients -join '; ')
                }}
                
                if ($data.attachment -and (Test-Path -LiteralPath $data.attachment)) {{
                    $mail.Attachments.Add($data.attachment)
                }}
                
                if ($data.display) {{
                    $mail.Display($false)
                    Write-Output "SUCCESS:Draft displayed"
                }} else {{
                    $mail.Save()
                    Write-Output "SUCCESS:Draft saved"
                }}
            }} catch {{
                Write-Output "ERROR:$($_.Exception.Message)"
            }}
            """

            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )

            out = res.stdout.strip()
            if "SUCCESS" in out:
                logger.info("Rascunho de e-mail criado com sucesso no Outlook com anexo: %s", target_path.name)
                return True, "Rascunho criado com sucesso no Microsoft Outlook."
            elif "ERROR:" in out:
                err_part = out.split("ERROR:", 1)[1].strip()
                logger.warning("Erro ao criar rascunho no Outlook via COM: %s", err_part)
                return False, f"Falha no Outlook: {err_part}"
            else:
                err_msg = res.stderr.strip() or out or "Retorno inesperado do PowerShell."
                logger.warning("Falha desconhecida no PowerShell COM: %s", err_msg)
                return False, err_msg

        except subprocess.TimeoutExpired:
            logger.error("Tempo limite excedido (%0.1fs) ao comunicar com o Outlook.", self.timeout_sec)
            return False, f"Tempo limite excedido ({self.timeout_sec}s) ao comunicar com o Outlook."
        except Exception as ex:
            logger.exception("Exceção ao criar rascunho no Outlook: %s", ex)
            return False, str(ex)
        finally:
            if temp_json and temp_json.exists():
                try:
                    temp_json.unlink()
                except Exception:
                    pass

    def open_mailto_fallback(
        self,
        minutes: MeetingMinutes,
        docx_path: Union[str, Path],
    ) -> bool:
        """
        Abre o cliente de e-mail padrão do Windows via protocolo mailto:
        e abre a pasta onde o documento Word está salvo para facilitar o anexo manual.
        """
        try:
            subject = self.build_email_subject(minutes)
            body = (
                f"{minutes.title}\n"
                f"Data: {minutes.date}\n\n"
                f"Resumo:\n{minutes.executive_summary}\n\n"
                f"O documento oficial está anexo nesta pasta: {Path(docx_path).name}"
            )
            mailto_url = f"mailto:?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
            webbrowser.open(mailto_url)

            # Abre a pasta do arquivo Word para o usuário anexar facilmente
            path = Path(docx_path).resolve()
            if path.exists():
                os.startfile(str(path.parent))
            return True
        except Exception as ex:
            logger.warning("Falha ao abrir mailto fallback: %s", ex)
            return False
