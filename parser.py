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
    # Template dos emails "[Produção] [Alerta] Problema no job de ingestão"
    # (equipe bigdata): "Conjunto de dados que precisaria ser processado:
    # <hash_do_mongo>(<nome_real_do_conjunto>)". Checado ANTES do padrão
    # genérico "Conjunto:" abaixo, pois esse é bem mais específico — sem
    # essa prioridade, o padrão genérico captura tudo até a primeira
    # vírgula, incluindo o hash, o "Error:" e o timestamp que vêm na
    # sequência (que mudam a cada execução e quebrariam a deduplicação).
    r"processad[oa]s?:?\s*[0-9a-fA-F]{8,}\s*\(([^)]+)\)",
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
    r"[Ss]ocket hang up",
    r"\b([A-Za-z][A-Za-z0-9]*(?:Exception|Error))\b",
]

# Template dos emails "job de ingestão" (equipe bigdata): depois de
# "[object Object] |" vem o motivo real da falha, seguido de
# "| undefined | undefined". Esse trecho tem dois formatos:
#   - curto:  "... | Diretório vazio | undefined | undefined"
#   - longo:  "... | 2026/07/07 02:06:01 - <dump gigante do Pentaho/Kettle,
#              com milhares de linhas de log> | undefined | undefined"
# Isso é checado ANTES de tudo (inclusive antes de _PATTERNS_ERRO_ESTAVEIS
# isoladas), pois é o formato mais específico e confiável quando o email
# é desse sistema. Quando o trecho capturado é curto, ele já é o próprio
# erro. Quando é o dump gigante, procura-se a causa raiz estável dentro
# dele usando os mesmos padrões de _PATTERNS_ERRO_ESTAVEIS.
_PATTERN_INGESTAO_BLOCO_ERRO = r"\[object Object\]\s*\|\s*(.*?)\s*\|\s*undefined\s*\|\s*undefined"
_INGESTAO_BLOCO_MAX_LEN = 150  # acima disso, tratamos como dump de log e não como erro em si

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
    conjunto_fonte = None
    if regex_conjunto:
        m = re.search(regex_conjunto, full_text)
        if m:
            conjunto = m.group(1).strip() if m.groups() else m.group(0).strip()
            conjunto_fonte = "regex_conjunto (config.py)"
    if not conjunto:
        conjunto = _apply_pattern(full_text, _PATTERNS_CONJUNTO)
        if conjunto:
            conjunto_fonte = "padrão conhecido"
    if not conjunto:
        conjunto = subject.strip() or "Desconhecido"
        conjunto_fonte = "fallback (assunto do email)"

    erro = None
    erro_fonte = None

    # 1) Template "job de ingestão": extrai o bloco entre "[object Object] |"
    # e "| undefined | undefined".
    m = re.search(_PATTERN_INGESTAO_BLOCO_ERRO, full_text, re.DOTALL)
    if m:
        bloco = m.group(1).strip()
        bloco = re.sub(r"^[Ee]rro:?\s*", "", bloco)   # remove "Error:"/"Erro:" redundante no início
        bloco = re.sub(r"^[Ee]rror:?\s*", "", bloco)
        if bloco and len(bloco) <= _INGESTAO_BLOCO_MAX_LEN:
            # Bloco curto: já é o próprio erro (ex.: "Diretório vazio", "socket hang up")
            erro = bloco
            erro_fonte = "template job de ingestão (bloco curto)"
        else:
            # Bloco longo (dump do Pentaho/Kettle): procura a causa raiz estável lá dentro
            erro = _apply_pattern(bloco, _PATTERNS_ERRO_ESTAVEIS)
            if erro:
                erro_fonte = "template job de ingestão (causa raiz no dump)"

    # 2) Padrões estáveis genéricos (para emails que não seguem o template acima)
    if not erro:
        erro = _apply_pattern(full_text, _PATTERNS_ERRO_ESTAVEIS)
        if erro:
            erro_fonte = "padrão estável genérico"

    # 3) Regex customizada do config.py
    if not erro and regex_erro:
        m = re.search(regex_erro, full_text)
        if m:
            erro = m.group(1).strip() if m.groups() else m.group(0).strip()
            erro_fonte = "regex_erro (config.py)"

    # 4) Padrões genéricos antigos — menos confiáveis (podem capturar texto
    # longo demais em formatos de email não vistos antes); vale logar.
    if not erro:
        erro = _apply_pattern(full_text, _PATTERNS_ERRO)
        if erro:
            erro_fonte = "padrão genérico (baixa confiança)"

    if not erro:
        erro = "Erro não identificado"
        erro_fonte = "fallback (não identificado)"

    conjunto = " ".join(conjunto.split()) if conjunto else conjunto
    erro = " ".join(erro.split()) if erro else erro

    # Trava de segurança: mesmo com todos os padrões acima, um formato de
    # email totalmente novo e desconhecido poderia fazer um padrão genérico
    # (_PATTERNS_ERRO) capturar texto até o fim do corpo. Corta bem acima do
    # necessário para qualquer erro real, só para nunca deixar a chave de
    # deduplicação (conjunto+erro) virar um texto absurdamente longo.
    if erro and len(erro) > 300:
        erro = erro[:300].rstrip() + "..."

    # Alerta no log (monitor.log) sempre que a extração não teve confiança
    # alta - ou seja, caiu no padrão genérico antigo ou não identificou nada.
    # Isso permite localizar depois, no log, quais emails tiveram um formato
    # que os padrões atuais não reconhecem bem, para ajustar o parser.py.
    if erro_fonte in ("padrão genérico (baixa confiança)", "fallback (não identificado)"):
        snippet = body.strip()[:200].replace("\n", " ")
        logger.warning(
            f"Erro extraído com baixa confiança ({erro_fonte}) — revisar parser.py. "
            f"Assunto: '{subject.strip()}' | erro extraído: '{erro}' | início do corpo: '{snippet}...'"
        )
    if conjunto_fonte == "fallback (assunto do email)":
        snippet = body.strip()[:200].replace("\n", " ")
        logger.warning(
            f"Conjunto não identificado por nenhum padrão — usando assunto como fallback. "
            f"Revisar parser.py. Assunto: '{subject.strip()}' | início do corpo: '{snippet}...'"
        )

    logger.debug(f"Parsed → conjunto='{conjunto}' ({conjunto_fonte}) | erro='{erro}' ({erro_fonte})")
    return conjunto, erro


def parse_raw_email(raw_bytes: bytes):
    return BytesParser(policy=policy.default).parsebytes(raw_bytes)