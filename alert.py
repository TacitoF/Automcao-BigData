"""
alerter.py - Envio de emails de alerta quando duplicatas são detectadas
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import List

from tls_compat import get_legacy_context

logger = logging.getLogger(__name__)


def _build_html(conjunto: str, erro: str, ocorrencias: int, window_hours: int, detalhes: List[dict]) -> str:
    """Monta o corpo HTML do email de alerta."""
    linhas = ""
    for i, oc in enumerate(detalhes, 1):
        ts = oc.get("ts", "")
        try:
            ts_fmt = datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M:%S") + " UTC"
        except Exception:
            ts_fmt = ts
        subj = oc.get("subject", "(sem assunto)")
        linhas += f"""
        <tr style="background:{'#f9f9f9' if i % 2 == 0 else '#ffffff'}">
            <td style="padding:8px;border:1px solid #ddd;">{i}</td>
            <td style="padding:8px;border:1px solid #ddd;">{ts_fmt}</td>
            <td style="padding:8px;border:1px solid #ddd;">{subj}</td>
        </tr>"""

    return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Alerta de Erro - Monitor ATI</title>
</head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:20px;">
  <div style="max-width:700px;margin:auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

    <!-- Cabeçalho -->
    <div style="background:#c0392b;padding:20px 30px;">
      <h1 style="color:#fff;margin:0;font-size:20px;">⚠️ Alerta de Erro Recorrente</h1>
      <p style="color:#f5b7b1;margin:5px 0 0;">Monitor de Logs - ATI</p>
    </div>

    <!-- Corpo -->
    <div style="padding:30px;">
      <p style="color:#555;">O seguinte erro foi detectado <strong>{ocorrencias} vezes</strong> nas últimas <strong>{window_hours} horas</strong>:</p>

      <table style="width:100%;border-collapse:collapse;margin:20px 0;">
        <tr>
          <td style="padding:12px;background:#fdecea;border-left:4px solid #c0392b;width:40%;font-weight:bold;color:#333;">📦 Conjunto</td>
          <td style="padding:12px;background:#fdecea;color:#c0392b;font-size:16px;font-weight:bold;">{conjunto}</td>
        </tr>
        <tr>
          <td style="padding:12px;background:#fff5f5;border-left:4px solid #c0392b;font-weight:bold;color:#333;">❌ Erro</td>
          <td style="padding:12px;background:#fff5f5;color:#c0392b;font-size:16px;font-weight:bold;">{erro}</td>
        </tr>
        <tr>
          <td style="padding:12px;background:#fdecea;border-left:4px solid #c0392b;font-weight:bold;color:#333;">🔁 Ocorrências</td>
          <td style="padding:12px;background:#fdecea;color:#333;">{ocorrencias}x nas últimas {window_hours}h</td>
        </tr>
      </table>

      <!-- Detalhes das ocorrências -->
      <h3 style="color:#333;border-bottom:2px solid #eee;padding-bottom:8px;">📋 Histórico de Ocorrências</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#c0392b;color:#fff;">
            <th style="padding:10px;border:1px solid #ddd;width:40px;">#</th>
            <th style="padding:10px;border:1px solid #ddd;">Data/Hora (UTC)</th>
            <th style="padding:10px;border:1px solid #ddd;">Assunto do Email</th>
          </tr>
        </thead>
        <tbody>{linhas}</tbody>
      </table>

      <p style="color:#888;font-size:12px;margin-top:30px;border-top:1px solid #eee;padding-top:15px;">
        Este alerta foi gerado automaticamente pelo Monitor de Logs da ATI.<br>
        Gerado em: {datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")} UTC
      </p>
    </div>
  </div>
</body>
</html>"""


def _build_plain(conjunto: str, erro: str, ocorrencias: int, window_hours: int) -> str:
    return (
        f"ALERTA DE ERRO RECORRENTE - Monitor de Logs ATI\n"
        f"{'='*50}\n\n"
        f"Conjunto : {conjunto}\n"
        f"Erro     : {erro}\n"
        f"Total    : {ocorrencias}x nas últimas {window_hours}h\n\n"
        f"Este alerta foi gerado automaticamente.\n"
        f"Data/Hora: {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S')} UTC\n"
    )


def send_alert(
    conjunto: str,
    erro: str,
    ocorrencias: int,
    detalhes: List[dict],
    recipients: List[str],
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    email_from: str,
    email_from_name: str = "Monitor de Logs ATI",
    use_tls: bool = True,
    use_ssl: bool = False,
    window_hours: int = 24,
    verify_hostname: bool = True,
    verify_cert: bool = True,
) -> bool:
    subject = f"[ALERTA] Erro recorrente: {conjunto} — {erro[:60]}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{email_from_name} <{email_from}>"
    msg["To"] = ", ".join(recipients)

    plain = _build_plain(conjunto, erro, ocorrencias, window_hours)
    html = _build_html(conjunto, erro, ocorrencias, window_hours, detalhes)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if use_ssl:
            context = get_legacy_context(verify_hostname=verify_hostname, verify_cert=verify_cert)
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)

        server.ehlo()

        if use_tls and not use_ssl:
            context = get_legacy_context(verify_hostname=verify_hostname, verify_cert=verify_cert)
            server.starttls(context=context)
            server.ehlo()

        if smtp_username and smtp_password:
            server.user, server.password = smtp_username, smtp_password
            try:
                # Por padrão, o smtplib envia o usuário já embutido no
                # próprio comando AUTH LOGIN ("initial response"), em uma
                # única linha. Esse atalho não faz parte do mecanismo
                # LOGIN original e muitos servidores SASL (comum em
                # Dovecot) o rejeitam, mesmo com credenciais corretas.
                # initial_response_ok=False força o diálogo clássico em
                # 3 passos: AUTH LOGIN -> usuário -> senha, cada um numa
                # resposta separada — o mesmo fluxo que Outlook e o
                # .NET (Send-MailMessage) usam por padrão.
                server.auth("LOGIN", server.auth_login, initial_response_ok=False)
            except smtplib.SMTPAuthenticationError:
                # Fallback: deixa o smtplib escolher o mecanismo, ainda
                # sem o atalho de initial response.
                server.login(smtp_username, smtp_password, initial_response_ok=False)

        server.sendmail(email_from, recipients, msg.as_string())
        server.quit()

        logger.info(f"Alerta enviado para: {recipients}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        smtp_error = e.smtp_error.decode("utf-8", errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        logger.error(
            f"Falha de autenticação SMTP — verifique usuário e senha. "
            f"Resposta do servidor: [{e.smtp_code}] {smtp_error}"
        )
    except smtplib.SMTPConnectError:
        logger.error(f"Não foi possível conectar ao SMTP {smtp_host}:{smtp_port}")
    except smtplib.SMTPException as e:
        logger.error(f"Erro SMTP ao enviar alerta: {e}")
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar alerta: {e}")

    return False