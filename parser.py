"""
parser.py - Extração de conjunto e erro dos emails de log recebidos
"""

import re
import logging
import email
from email import policy
from email.parser import BytesParser
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# Padrões comuns para extração automática inteligente
_PATTERNS_CONJUNTO = [
    r"[Cc]onjunto[:\s]+([^\n\r,;]+)",
    r"[Ss]et[:\s]+([^\n\r,;]+)",
    r"[Gg]roup[:\s]+([^\n\r,;]+)",
    r"[Jj]ob[:\s]+([^\n\r,;]+)",
    r"[Pp]acote[:\s]+([^\n\r,;]+)",
    r"[Bb]atch[:\s]+([^\n\r,;]+)",
    r"\[([A-Z0-9_\-]{3,})\]",          # [NOME_CONJUNTO] em caixa alta
]

_PATTERNS_ERRO = [
    r"[Ee]rro[:\s]+([^\n\r]+)",
    r"[Ee]rror[:\s]+([^\n\r]+)",
    r"[Ee]xce[çc][aã]o[:\s]+([^\n\r]+)",
    r"[Ee]xception[:\s]+([^\n\r]+)",
    r"[Ff]alha[:\s]+([^\n\r]+)",
    r"[Ff]ailure[:\s]+([^\n\r]+)",
    r"[Ss]tatus[:\s]+(?:[Ee]rro|[Ff]alha|[Ff]ail)[^\n\r]*",
    r"(?:CRITICAL|ERROR|FATAL)[:\s]+([^\n\r]+)",
]


def decode_email_part(part) -> str:
    """Decodifica uma parte do email para texto legível."""
    charset = part.get_content_charset() or "utf-8"
    try:
        return part.get_payload(decode=True).decode(charset, errors="replace")
    except Exception:
        try:
            return part.get_payload(decode=True).decode("latin-1", errors="replace")
        except Exception:
            return ""


def extract_body(msg) -> str:
    """Extrai o corpo do email (text/plain preferencial, fallback html)."""
    body_plain = ""
    body_html = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            if content_type == "text/plain":
                body_plain += decode_email_part(part)
            elif content_type == "text/html" and not body_plain:
                body_html += decode_email_part(part)
    else:
        body_plain = decode_email_part(msg)

    # Remove tags HTML básicas se usar o fallback
    if not body_plain and body_html:
        body_plain = re.sub(r"<[^>]+>", " ", body_html)
        body_plain = re.sub(r"\s+", " ", body_plain).strip()

    return body_plain


def _apply_pattern(text: str, patterns: list) -> Optional[str]:
    """Tenta cada padrão e retorna o primeiro match."""
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            groups = m.groups()
            result = groups[0] if groups else m.group(0)
            return result.strip()
    return None


def extract_conjunto_and_erro(
    subject: str,
    body: str,
    regex_conjunto: str = "",
    regex_erro: str = "",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrai nome do conjunto e tipo de erro de um email de log.

    Retorna (conjunto, erro) — pode retornar None em qualquer campo
    se não conseguir extrair.
    """
    full_text = f"{subject}\n{body}"

    # --- Conjunto ---
    conjunto = None
    if regex_conjunto:
        m = re.search(regex_conjunto, full_text)
        if m:
            conjunto = m.group(1).strip() if m.groups() else m.group(0).strip()
    if not conjunto:
        conjunto = _apply_pattern(full_text, _PATTERNS_CONJUNTO)
    if not conjunto:
        # Último recurso: usa o assunto inteiro como "conjunto"
        conjunto = subject.strip() or "Desconhecido"

    # --- Erro ---
    erro = None
    if regex_erro:
        m = re.search(regex_erro, full_text)
        if m:
            erro = m.group(1).strip() if m.groups() else m.group(0).strip()
    if not erro:
        erro = _apply_pattern(full_text, _PATTERNS_ERRO)
    if not erro:
        erro = "Erro não identificado"

    # Limpa espaços extras
    conjunto = " ".join(conjunto.split()) if conjunto else conjunto
    erro = " ".join(erro.split()) if erro else erro

    logger.debug(f"Parsed → conjunto='{conjunto}' | erro='{erro}'")
    return conjunto, erro


def parse_raw_email(raw_bytes: bytes):
    """Faz o parse de bytes brutos de email e retorna o objeto msg."""
    return BytesParser(policy=policy.default).parsebytes(raw_bytes)