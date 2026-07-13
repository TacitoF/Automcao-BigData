import imaplib
import json
import logging
import os
import time
import email as email_lib
from email import policy as email_policy
from typing import List, Tuple, Optional, Set

from tls_compat import get_legacy_context

logger = logging.getLogger(__name__)

SKIPPED_STATE_FILE = "skipped_subjects_state.json"


class IMAPReader:

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        mailbox: str = "INBOX",
        skipped_state_file: str = SKIPPED_STATE_FILE,
        connect_max_retries: int = 3,
        connect_retry_delay_seconds: int = 10,
        exclude_from: Optional[List[str]] = None,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.mailbox = mailbox
        self._conn: Optional[imaplib.IMAP4] = None

        # Remetentes a ignorar mesmo que o assunto bata com
        # LOG_SUBJECT_KEYWORDS. Existe porque a própria automação envia
        # alertas com "ALERTA" no assunto - se a caixa monitorada é a
        # mesma que recebe os alertas (ex.: caixa pessoal do responsável
        # também está em EMAIL_RECIPIENTS), o e-mail de alerta acaba
        # batendo com a keyword "alerta" e sendo processado/marcado como
        # lido como se fosse um log de erro original, escondendo-o na
        # caixa antes que a pessoa perceba que o alerta chegou.
        self.exclude_from = [addr.lower() for addr in (exclude_from or [])]

        # Quantas vezes tentar reconectar (dentro do MESMO ciclo) antes de
        # desistir, e quantos segundos esperar entre uma tentativa e outra.
        # Existe porque bloqueios intermitentes de antivírus/EDR (ex.:
        # WinError 10013 no Windows) costumam liberar a conexão sozinhos
        # após poucos segundos - sem isso, uma falha assim faz perder o
        # ciclo inteiro e esperar os próximos minutos (POLLING_INTERVAL)
        # até tentar de novo.
        self.connect_max_retries = connect_max_retries
        self.connect_retry_delay_seconds = connect_retry_delay_seconds

        # Guarda quais emails (por Message-ID) já tiveram o assunto logado
        # ao serem ignorados por não corresponder ao LOG_SUBJECT_KEYWORDS.
        # Isso evita repetir a mesma linha de log a cada ciclo (5 em 5 min)
        # para o mesmo email que continua não lido na caixa pessoal do
        # usuário - sem nunca marcá-lo como lido.
        self.skipped_state_file = skipped_state_file
        self._skipped_logged: Set[str] = self._load_skipped()

    def _load_skipped(self) -> Set[str]:
        if os.path.exists(self.skipped_state_file):
            try:
                with open(self.skipped_state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data.get("skipped_message_ids", []))
            except Exception as e:
                logger.warning(f"Não foi possível carregar estado de emails ignorados: {e}")
        return set()

    def _save_skipped(self):
        try:
            with open(self.skipped_state_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"skipped_message_ids": sorted(self._skipped_logged)},
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logger.error(f"Erro ao salvar estado de emails ignorados: {e}")

    def connect(self) -> bool:
        try:
            if self.use_ssl:
                context = get_legacy_context()
                self._conn = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=context)
            else:
                self._conn = imaplib.IMAP4(self.host, self.port)

            self._conn.login(self.username, self.password)
            logger.info(f"Conectado ao IMAP: {self.host}:{self.port}")
            return True

        except imaplib.IMAP4.error as e:
            logger.error(f"Falha ao conectar/autenticar no IMAP: {e}")
            self._conn = None
            return False
        except Exception as e:
            logger.error(f"Erro inesperado na conexão IMAP: {e}")
            self._conn = None
            return False

    def connect_with_retry(
        self,
        max_retries: Optional[int] = None,
        retry_delay_seconds: Optional[int] = None,
    ) -> bool:
        """Tenta conectar múltiplas vezes com uma pequena pausa entre
        tentativas, dentro do MESMO ciclo de verificação.

        Motivo: bloqueios intermitentes de antivírus/EDR na camada de
        socket (ex.: WinError 10013 no Windows) costumam se resolver
        sozinhos após alguns segundos. Sem o retry, uma falha assim faz
        perder o ciclo inteiro e só tentar de novo no próximo
        POLLING_INTERVAL_MINUTES (minutos depois). Com o retry, aumenta
        bastante a chance de "furar" esse bloqueio momentâneo ainda
        dentro do ciclo atual.
        """
        max_retries = max_retries if max_retries is not None else self.connect_max_retries
        retry_delay_seconds = (
            retry_delay_seconds if retry_delay_seconds is not None else self.connect_retry_delay_seconds
        )

        for tentativa in range(1, max_retries + 1):
            if self.connect():
                if tentativa > 1:
                    logger.info(f"Conectado ao IMAP na tentativa {tentativa}/{max_retries}.")
                return True

            if tentativa < max_retries:
                logger.warning(
                    f"Falha ao conectar ao IMAP (tentativa {tentativa}/{max_retries}). "
                    f"Tentando novamente em {retry_delay_seconds}s..."
                )
                time.sleep(retry_delay_seconds)

        logger.error(f"Falha ao conectar ao IMAP após {max_retries} tentativa(s) neste ciclo.")
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
                # Caixa sem não-lidos: nada a "lembrar" de um ciclo para o outro.
                if self._skipped_logged:
                    self._skipped_logged.clear()
                    self._save_skipped()
                return []

            msg_ids = data[0].split()
            logger.info(f"{len(msg_ids)} email(s) não lido(s) encontrado(s).")

            results = []
            # Chaves (Message-ID) de tudo que ainda está não lido nesta
            # passada - usado para "podar" do estado qualquer email que já
            # foi lido manualmente (pelo webmail) e não aparece mais aqui.
            still_unread_keys: Set[str] = set()

            for mid in msg_ids:
                try:
                    status, msg_data = self._conn.fetch(mid, "(BODY.PEEK[])")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        continue

                    raw_bytes = msg_data[0][1]
                    mid_str = mid.decode() if isinstance(mid, bytes) else str(mid)

                    if subject_keywords or self.exclude_from:
                        msg_obj = email_lib.message_from_bytes(raw_bytes, policy=email_policy.default)
                        subject = str(msg_obj.get("Subject", ""))
                        from_header = str(msg_obj.get("From", "")).lower()
                        message_id = str(msg_obj.get("Message-ID", "")) or f"seq:{mid_str}"
                        still_unread_keys.add(message_id)

                        # Verificação PRIMÁRIA e mais confiável: o header
                        # customizado X-Monitor-ATI-Alert, gravado pelo
                        # próprio alert.py em todo email de alerta que ele
                        # envia. Diferente do "From", esse header nunca é
                        # reescrito por servidores SMTP corporativos que
                        # forçam o From a bater com o usuário autenticado
                        # no envio - o que antes fazia o próprio alerta
                        # escapar da exclusão baseada só em IMAP_EXCLUDE_FROM
                        # e ser lido de volta como se fosse um novo erro.
                        is_self_alert = bool(msg_obj.get("X-Monitor-ATI-Alert"))

                        # Verificação SECUNDÁRIA (compatibilidade / defesa
                        # em profundidade): mantém a checagem por From, útil
                        # caso o header customizado seja removido por algum
                        # gateway de email no meio do caminho.
                        if not is_self_alert:
                            is_self_alert = any(addr in from_header for addr in self.exclude_from)

                        subject_matches = (
                            any(kw.lower() in subject.lower() for kw in subject_keywords)
                            if subject_keywords else True
                        )

                        if is_self_alert or not subject_matches:
                            if message_id not in self._skipped_logged:
                                if msg_obj.get("X-Monitor-ATI-Alert"):
                                    motivo = "auto-alerta da própria automação (header X-Monitor-ATI-Alert)"
                                elif is_self_alert:
                                    motivo = f"remetente ignorado ('{from_header}')"
                                else:
                                    motivo = "assunto não corresponde"
                                logger.debug(
                                    f"Email {mid_str} ignorado ({motivo}): '{subject}'"
                                )
                                self._skipped_logged.add(message_id)
                            # Se já logado antes, fica em silêncio - continua
                            # não lido, sem repetir a mesma linha no log.
                            continue

                    results.append((mid_str, raw_bytes))

                except Exception as e:
                    logger.warning(f"Erro ao buscar email {mid}: {e}")

            # Poda: remove do estado qualquer Message-ID que não está mais
            # entre os não lidos atuais (ex.: usuário leu manualmente).
            if subject_keywords or self.exclude_from:
                before = len(self._skipped_logged)
                self._skipped_logged &= still_unread_keys
                if len(self._skipped_logged) != before:
                    logger.debug(
                        f"{before - len(self._skipped_logged)} email(s) removido(s) do estado de "
                        f"ignorados (não estão mais não lidos)."
                    )
                self._save_skipped()

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
        self.connect_with_retry()
        return self

    def __exit__(self, *args):
        self.disconnect()