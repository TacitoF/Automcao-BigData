"""Valores padrão da GUI e geração de config.py sem dependência do Tkinter."""

import json
from controller_directory import DEFAULT_CONTROLLER_QUERY


DEFAULT_CONFIG = {
    "imap_host": "sogo.ati.gov.br",
    "imap_port": "993",
    "imap_use_ssl": True,
    "imap_username": "",
    "imap_password": "",
    "imap_mailbox": "INBOX",
    "smtp_host": "sogo.ati.gov.br",
    "smtp_port": "587",
    "smtp_use_tls": True,
    "smtp_use_ssl": False,
    "smtp_verify_hostname": True,
    "smtp_verify_cert": True,
    "smtp_username": "",
    "smtp_password": "",
    "email_from": "",
    "email_from_name": "Monitor de Logs ATI",
    "email_recipients": "",
    "controller_db_enabled": False,
    "controller_db_url_env": "MONITOR_DATABASE_URL",
    "controller_db_query": DEFAULT_CONTROLLER_QUERY,
    "controller_db_connect_args": "{}",
    "controller_test_conjunto": "",
    "polling_interval": "5",
    "dedup_window_hours": "720",
    "min_occurrences": "2",
    "log_subject_keywords": "job de ingestão, falhou",
    "regex_conjunto": r"Conjunto de dados.*?:\s*[^(]+\(([^)]+)\)",
    "regex_erro": r"Error:.*?(?:\s*\|\s*)([A-Za-zÀ-ÖØ-öø-ÿ ]+)",
}


def build_config_content(c):
    recipients = [
        r.strip() for r in c.get("email_recipients", "").replace(",", "\n").splitlines()
        if r.strip()
    ]
    connect_args = json.loads(c.get("controller_db_connect_args", "{}"))
    if not isinstance(connect_args, dict):
        raise ValueError("As opções de conexão devem ser um objeto JSON.")
    values = {
        "IMAP_HOST": c["imap_host"],
        "IMAP_PORT": int(c["imap_port"]),
        "IMAP_USE_SSL": c["imap_use_ssl"],
        "IMAP_USERNAME": c["imap_username"],
        "IMAP_PASSWORD": c["imap_password"],
        "IMAP_MAILBOX": c["imap_mailbox"],
        "SMTP_HOST": c["smtp_host"],
        "SMTP_PORT": int(c["smtp_port"]),
        "SMTP_USE_TLS": c["smtp_use_tls"],
        "SMTP_USE_SSL": c["smtp_use_ssl"],
        "SMTP_VERIFY_HOSTNAME": c["smtp_verify_hostname"],
        "SMTP_VERIFY_CERT": c["smtp_verify_cert"],
        "SMTP_USERNAME": c["smtp_username"],
        "SMTP_PASSWORD": c["smtp_password"],
        "EMAIL_FROM": c["email_from"],
        "EMAIL_FROM_NAME": c["email_from_name"],
        "EMAIL_RECIPIENTS": recipients,
        "POLLING_INTERVAL_MINUTES": int(c["polling_interval"]),
        "DEDUP_WINDOW_HOURS": int(c["dedup_window_hours"]),
        "MIN_OCCURRENCES_TO_ALERT": int(c["min_occurrences"]),
        "LOG_SUBJECT_KEYWORDS": [
            k.strip() for k in c["log_subject_keywords"].split(",") if k.strip()
        ],
        "REGEX_CONJUNTO": c["regex_conjunto"],
        "REGEX_ERRO": c["regex_erro"],
        "CONTROLLER_DB_ENABLED": c["controller_db_enabled"],
        "CONTROLLER_DB_URL_ENV": c["controller_db_url_env"],
        "CONTROLLER_DB_QUERY": c["controller_db_query"],
        "CONTROLLER_DB_CONNECT_ARGS": connect_args,
        "LOG_FILE": "monitor.log",
        "LOG_LEVEL": "INFO",
    }
    # repr preserva aspas, barras e consultas SQL com várias linhas.
    content = "\n".join(f"{name} = {value!r}" for name, value in values.items()) + "\n"
    return content
