import imaplib
import logging
import email as email_lib
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class IMAPReader:

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        mailbox: str = "INBOX",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.mailbox = mailbox
        self._conn: Optional[imaplib.IMAP4] = None

    def connect(self) -> bool:
        try:
            if self.use_ssl:
                self._conn = imaplib.IMAP4_SSL(self.host, self.port)
            else:
                self._conn = imaplib.IMAP4(self.host, self.port)

            self._conn.login(self.username, self.password)
            logger.info(f"Conectado ao IMAP: {self.host}:{self.port}")
            return True

        except imaplib.IMAP4.error as e:
            logger.error(f"Falha ao conectar/autenticar no IMAP: {e}")
            return False
        except Exception as e:
            logger.error(f"Erro inesperado na conexão IMAP: {e}")
            return False

    def disconnect(self):
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def fetch_unread(self, subject_keywords: List[str] = None) -> List[Tuple[str, bytes]]:
        if not self._conn:
            logger.error("Não está conectado ao IMAP.")
            return []

        try:
            status, _ = self._conn.select(self.mailbox)
            if status != "OK":
                logger.error(f"Não foi possível selecionar a mailbox '{self.mailbox}'")
                return []

            status, data = self._conn.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                logger.debug("Nenhuma mensagem não lida encontrada.")
                return []

            msg_ids = data[0].split()
            logger.info(f"{len(msg_ids)} email(s) não lido(s) encontrado(s).")

            results = []
            for mid in msg_ids:
                try:
                    status, msg_data = self._conn.fetch(mid, "(RFC822)")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        continue

                    raw_bytes = msg_data[0][1]
                    mid_str = mid.decode() if isinstance(mid, bytes) else str(mid)

                    if subject_keywords:
                        msg_obj = email_lib.message_from_bytes(raw_bytes)
                        subject = str(msg_obj.get("Subject", ""))
                        if not any(kw.lower() in subject.lower() for kw in subject_keywords):
                            logger.debug(f"Email {mid_str} ignorado (assunto não corresponde).")
                            continue

                    results.append((mid_str, raw_bytes))

                except Exception as e:
                    logger.warning(f"Erro ao buscar email {mid}: {e}")

            return results

        except imaplib.IMAP4.error as e:
            logger.error(f"Erro IMAP ao buscar emails: {e}")
            return []

    def mark_as_read(self, msg_id: str):
        if not self._conn:
            return
        try:
            self._conn.store(msg_id, "+FLAGS", "\\Seen")
            logger.debug(f"Email {msg_id} marcado como lido.")
        except Exception as e:
            logger.warning(f"Não foi possível marcar email {msg_id} como lido: {e}")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()