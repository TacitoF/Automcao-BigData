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


_PATTERNS_CONJUNTO = [
    r"[Cc]onjunto[:\s]+([^\n\r,;]+)",
    r"[Ss]et[:\s]+([^\n\r,;]+)",
    r"[Gg]roup[:\s]+([^\n\r,;]+)",
    r"[Jj]ob[:\s]+([^\n\r,;]+)",
    r"[Pp]acote[:\s]+([^\n\r,;]+)",
    r"[Bb]atch[:\s]+([^\n\r,;]+)",
    r"\[([A-Z0-9_\-]{3,})\]",         
]

# Sinais de causa raiz ESTÁVEIS (sem números/IDs/timestamps que mudam a cada
# execução) — checados ANTES dos padrões genéricos abaixo, para que a mesma
# causa real produza sempre o mesmo texto e seja corretamente reconhecida
# como recorrente, mesmo dentro de logs gigantes do Pentaho/Kettle onde
# quase tudo mais (job ID, hora, nomes de arquivo) varia a cada falha.
_PATTERNS_ERRO_ESTAVEIS = [
    r"Diret[oó]rio vazio",
    r"No such file or directory",
    r"Deadlock found when trying to get lock",
    r"couldn't convert String to (?:number|date|an? \w+)",
    r"Unexpected conversion error while converting value",
    r"Unable to write log record to log table\s*\[\w+\]",
    r"Connection (?:refused|timed out|reset)",
    r"\b([A-Za-z][A-Za-z0-9]*(?:Exception|Error))\b",
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
    charset = part.get_content_charset() or "utf-8"
    try:
        return part.get_payload(decode=True).decode(charset, errors="replace")
    except Exception:
        try:
            return part.get_payload(decode=True).decode("latin-1", errors="replace")
        except Exception:
            return ""


def extract_body(msg) -> str:
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

    if not body_plain and body_html:
        body_plain = re.sub(r"<[^>]+>", " ", body_html)
        body_plain = re.sub(r"\s+", " ", body_plain).strip()

    return body_plain


def _apply_pattern(text: str, patterns: list) -> Optional[str]:
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
    full_text = f"{subject}\n{body}"

    conjunto = None
    if regex_conjunto:
        m = re.search(regex_conjunto, full_text)
        if m:
            conjunto = m.group(1).strip() if m.groups() else m.group(0).strip()
    if not conjunto:
        conjunto = _apply_pattern(full_text, _PATTERNS_CONJUNTO)
    if not conjunto:
        conjunto = subject.strip() or "Desconhecido"

    erro = None
    erro = _apply_pattern(full_text, _PATTERNS_ERRO_ESTAVEIS)
    if not erro and regex_erro:
        m = re.search(regex_erro, full_text)
        if m:
            erro = m.group(1).strip() if m.groups() else m.group(0).strip()
    if not erro:
        erro = _apply_pattern(full_text, _PATTERNS_ERRO)
    if not erro:
        erro = "Erro não identificado"

    conjunto = " ".join(conjunto.split()) if conjunto else conjunto
    erro = " ".join(erro.split()) if erro else erro

    logger.debug(f"Parsed → conjunto='{conjunto}' | erro='{erro}'")
    return conjunto, erro


def parse_raw_email(raw_bytes: bytes):
    return BytesParser(policy=policy.default).parsebytes(raw_bytes)