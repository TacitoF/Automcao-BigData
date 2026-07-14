"""
service.py - Execução headless (sem interface gráfica) do Monitor de Logs ATI.

Pensado para rodar continuamente em uma VM de servidor, gerenciado como:
  - Serviço do Windows (via NSSM) -> recomendado
  - Tarefa Agendada do Windows (Task Scheduler) -> alternativa sem instalar nada
  - Serviço systemd, se a VM for Linux

Diferenças em relação a rodar pela GUI:
  - Não depende do Tkinter (não precisa de área de trabalho/sessão interativa).
  - Loga em arquivo com rotação (monitor.log), além do console.
  - Inicia o monitoramento sozinho, sem precisar clicar em "Iniciar".
  - Responde a sinais de parada (Ctrl+C, parada de serviço) terminando
    o ciclo atual de forma limpa antes de sair.

Requer que exista um config.py na mesma pasta (gerado pela GUI ao clicar em
"Salvar Configurações", ou escrito manualmente seguindo o config.py.example).
"""

import sys
import os
import time
import signal
import logging
from logging.handlers import RotatingFileHandler

# Garante que estamos rodando a partir da pasta do executável/script,
# para encontrar config.py, occurrences_state.json e monitor.log corretamente.
if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(sys.executable)
else:
    _exe_dir = os.path.dirname(os.path.abspath(__file__))

os.chdir(_exe_dir)

# Importante: o chdir() acima só afeta leitura/escrita de arquivos (open()).
# Para o "import config" funcionar, o Python também precisa dessa pasta no
# sys.path - sem isso, no .exe compilado o import falha mesmo com o
# config.py presente na mesma pasta do executável.
if _exe_dir not in sys.path:
    sys.path.insert(0, _exe_dir)

_stop_requested = False


def _handle_signal(signum, frame):
    global _stop_requested
    logging.getLogger("monitor_service").warning(
        f"Sinal de parada recebido ({signum}). Finalizando após o ciclo atual..."
    )
    _stop_requested = True


def setup_logging(log_file: str, log_level: str) -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, str(log_level).upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    # Arquivo com rotação: 5 MB por arquivo, mantém 5 arquivos antigos.
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # Console/stdout - útil se rodar com --console no NSSM ou manualmente.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


def run_cycle(cfg, tracker, logger):
    from imap_reader import IMAPReader
    from parser import extract_conjunto_and_erro, extract_body, parse_raw_email
    from alert import send_alert

    logger.info("Iniciando ciclo de verificação...")

    with IMAPReader(
        host=cfg.IMAP_HOST, port=cfg.IMAP_PORT,
        username=cfg.IMAP_USERNAME, password=cfg.IMAP_PASSWORD,
        use_ssl=cfg.IMAP_USE_SSL, mailbox=cfg.IMAP_MAILBOX,
        connect_max_retries=int(getattr(cfg, "IMAP_CONNECT_MAX_RETRIES", 3)),
        connect_retry_delay_seconds=int(getattr(cfg, "IMAP_CONNECT_RETRY_DELAY_SECONDS", 10)),
        exclude_from=getattr(cfg, "IMAP_EXCLUDE_FROM", None),
        exclude_subject_keywords=getattr(cfg, "IMAP_EXCLUDE_SUBJECT_KEYWORDS", None),
    ) as reader:
        if not reader._conn:
            logger.error("Falha na conexão IMAP. Pulando ciclo.")
            return

        keywords = cfg.LOG_SUBJECT_KEYWORDS if cfg.LOG_SUBJECT_KEYWORDS else None
        emails = reader.fetch_unread(subject_keywords=keywords)

        if not emails:
            logger.info("Nenhum email novo para processar.")
            return

        for msg_id, raw_bytes in emails:
            try:
                msg = parse_raw_email(raw_bytes)
                subject = str(msg.get("Subject", "(sem assunto)"))
                body = extract_body(msg)
                email_message_id = str(msg.get("Message-ID", msg_id))

                conjunto, erro = extract_conjunto_and_erro(
                    subject=subject, body=body,
                    regex_conjunto=cfg.REGEX_CONJUNTO,
                    regex_erro=cfg.REGEX_ERRO,
                )

                deve_alertar, total = tracker.register(
                    conjunto=conjunto, erro=erro,
                    subject=subject, msg_id=email_message_id,
                )

                if deve_alertar:
                    detalhes = tracker.get_occurrences(conjunto, erro)
                    sucesso = send_alert(
                        conjunto=conjunto, erro=erro,
                        ocorrencias=total, detalhes=detalhes,
                        recipients=cfg.EMAIL_RECIPIENTS,
                        smtp_host=cfg.SMTP_HOST, smtp_port=cfg.SMTP_PORT,
                        smtp_username=cfg.SMTP_USERNAME,
                        smtp_password=cfg.SMTP_PASSWORD,
                        email_from=cfg.EMAIL_FROM,
                        email_from_name=cfg.EMAIL_FROM_NAME,
                        use_tls=cfg.SMTP_USE_TLS, use_ssl=cfg.SMTP_USE_SSL,
                        window_hours=cfg.DEDUP_WINDOW_HOURS,
                        verify_hostname=getattr(cfg, "SMTP_VERIFY_HOSTNAME", True),
                        verify_cert=getattr(cfg, "SMTP_VERIFY_CERT", True),
                    )
                    status = "enviado com sucesso" if sucesso else "FALHOU ao enviar"
                    logger.info(
                        f"Alerta {status}: conjunto='{conjunto}' | erro='{erro}' | ocorrencias={total}"
                    )

                reader.mark_as_read(msg_id)

            except Exception as e:
                logger.error(f"Erro ao processar email {msg_id}: {e}", exc_info=True)

    logger.info("Ciclo finalizado.")


def _interruptible_sleep(seconds: int):
    """Dorme em pequenos pedaços para conseguir reagir rápido a um sinal de parada."""
    waited = 0
    while waited < seconds and not _stop_requested:
        chunk = min(5, seconds - waited)
        time.sleep(chunk)
        waited += chunk


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (AttributeError, ValueError):
        pass  # SIGTERM pode não existir/ser interceptável em alguns ambientes Windows

    try:
        import config as cfg
    except ImportError:
        print(
            "ERRO FATAL: config.py não encontrado na pasta do executável.\n"
            "Gere o config.py pela GUI (botão 'Salvar Configurações') e copie-o "
            "para a mesma pasta deste serviço antes de iniciar."
        )
        sys.exit(1)

    logger = setup_logging(
        getattr(cfg, "LOG_FILE", "monitor.log"),
        getattr(cfg, "LOG_LEVEL", "INFO"),
    )
    logger.info("=== Monitor de Logs ATI (modo serviço) iniciado ===")
    logger.info(f"IMAP: {cfg.IMAP_HOST}:{cfg.IMAP_PORT} | Intervalo: {cfg.POLLING_INTERVAL_MINUTES} min")

    from tracker import OccurrenceTracker
    tracker = OccurrenceTracker(
        window_hours=int(cfg.DEDUP_WINDOW_HOURS),
        min_occurrences=int(cfg.MIN_OCCURRENCES_TO_ALERT),
        cleanup_interval_days=int(getattr(cfg, "STATE_CLEANUP_INTERVAL_DAYS", 30)),
    )

    falhas_consecutivas = 0

    while not _stop_requested:
        try:
            tracker.run_maintenance()
            run_cycle(cfg, tracker, logger)
            falhas_consecutivas = 0
        except Exception as e:
            falhas_consecutivas += 1
            logger.error(
                f"Erro no ciclo ({falhas_consecutivas}x consecutiva(s)): {e}",
                exc_info=True,
            )

        if _stop_requested:
            break

        interval = int(cfg.POLLING_INTERVAL_MINUTES) * 60
        logger.info(f"Próxima verificação em {cfg.POLLING_INTERVAL_MINUTES} minuto(s)...")
        _interruptible_sleep(interval)

    logger.info("=== Monitor de Logs ATI finalizado de forma limpa ===")


if __name__ == "__main__":
    main()