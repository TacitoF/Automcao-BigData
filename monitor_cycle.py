"""Ciclo compartilhado pela GUI e pelo serviço, com roteamento por controlador."""

import hashlib

from alert import send_alert
from controller_directory import ControllerDirectory, ControllerLookupError
from imap_reader import IMAPReader
from parser import extract_body, extract_conjunto_and_erro, parse_raw_email


def run_cycle(cfg, tracker, logger, on_alert=None):
    logger.info("Iniciando ciclo de verificação...")
    with ControllerDirectory(cfg) as directory, IMAPReader(
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
        emails = reader.fetch_unread(subject_keywords=cfg.LOG_SUBJECT_KEYWORDS or None)
        if not emails:
            logger.info("Nenhum email novo para processar.")
            return

        for msg_id, raw_bytes in emails:
            try:
                msg = parse_raw_email(raw_bytes)
                subject = str(msg.get("Subject", "(sem assunto)"))
                # IMAP sequence numbers podem mudar. O hash é estável mesmo
                # quando o remetente não incluiu um header Message-ID.
                message_id = str(msg.get("Message-ID", "")).strip()
                message_id = message_id or "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
                conjunto, erro = extract_conjunto_and_erro(
                    subject=subject, body=extract_body(msg),
                    regex_conjunto=cfg.REGEX_CONJUNTO, regex_erro=cfg.REGEX_ERRO,
                )
                deve_alertar, total = tracker.register(
                    conjunto=conjunto, erro=erro, subject=subject, msg_id=message_id,
                )
                if deve_alertar:
                    sucesso = False
                    try:
                        recipients = directory.recipients_for(conjunto)
                        sucesso = send_alert(
                            conjunto=conjunto, erro=erro, ocorrencias=total,
                            detalhes=tracker.get_occurrences(conjunto, erro),
                            recipients=recipients,
                            smtp_host=cfg.SMTP_HOST, smtp_port=cfg.SMTP_PORT,
                            smtp_username=cfg.SMTP_USERNAME, smtp_password=cfg.SMTP_PASSWORD,
                            email_from=cfg.EMAIL_FROM, email_from_name=cfg.EMAIL_FROM_NAME,
                            use_tls=cfg.SMTP_USE_TLS, use_ssl=cfg.SMTP_USE_SSL,
                            window_hours=cfg.DEDUP_WINDOW_HOURS,
                            verify_hostname=getattr(cfg, "SMTP_VERIFY_HOSTNAME", True),
                            verify_cert=getattr(cfg, "SMTP_VERIFY_CERT", True),
                        )
                    except ControllerLookupError as exc:
                        logger.error("Alerta pendente para conjunto='%s': %s", conjunto, exc)

                    if sucesso:
                        tracker.mark_alert_sent(conjunto, erro)
                    status = "enviado com sucesso" if sucesso else "pendente; nova tentativa no próximo ciclo"
                    logger.info("Alerta %s: conjunto='%s' | erro='%s' | ocorrencias=%s",
                                status, conjunto, erro, total)
                    if on_alert:
                        on_alert(conjunto, erro, total, sucesso)
                    if not sucesso:
                        # Mantém a mensagem não lida para retentar sem contar
                        # sua ocorrência novamente, inclusive após reiniciar.
                        continue
                reader.mark_as_read(msg_id)
            except Exception as exc:
                logger.error("Erro ao processar email %s: %s", msg_id, exc, exc_info=True)
    logger.info("Ciclo finalizado.")
