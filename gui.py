import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import queue
import json
import os
import sys
import logging
import logging.handlers
from datetime import datetime


CONFIG_FILE = "config_ui.json"

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
    "polling_interval": "5",
    "dedup_window_hours": "720",
    "min_occurrences": "2",
    "log_subject_keywords": "job de ingestão, falhou",
    "regex_conjunto": r"Conjunto de dados.*?:\s*[^(]+\(([^)]+)\)",
    "regex_erro": r"Error:.*?(?:\s*\|\s*)([A-Za-zÀ-ÖØ-öø-ÿ ]+)",
}

DARK = {
    "bg":        "#0f1117",
    "panel":     "#1a1d27",
    "card":      "#21253a",
    "border":    "#2e3354",
    "accent":    "#4f6ef7",
    "accent2":   "#7c5cfc",
    "success":   "#22c55e",
    "danger":    "#ef4444",
    "warning":   "#f59e0b",
    "text":      "#e2e8f0",
    "text_muted":"#64748b",
    "input_bg":  "#131722",
}


class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


class MonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor de Logs ATI")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.configure(bg=DARK["bg"])

        self._monitor_thread = None
        self._running = False
        self._stop_event = threading.Event()
        self._log_queue = queue.Queue()
        self._alert_history = []

        self._config = DEFAULT_CONFIG.copy()
        self._load_config()
        self._setup_logging()
        self._build_ui()
        self._poll_log_queue()

    def _setup_logging(self):
        self._logger = logging.getLogger("monitor_gui")
        self._logger.setLevel(logging.DEBUG)
        handler = QueueHandler(self._log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        if not self._logger.handlers:
            self._logger.addHandler(handler)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        if not any(isinstance(h, QueueHandler) for h in root_logger.handlers):
            root_logger.addHandler(handler)

        # Também grava em arquivo (monitor.log, com rotação), igual ao modo serviço,
        # para que o histórico não se perca quando a janela é fechada.
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root_logger.handlers):
            try:
                file_handler = logging.handlers.RotatingFileHandler(
                    "monitor.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
                )
                file_handler.setFormatter(
                    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
                )
                root_logger.addHandler(file_handler)
            except Exception:
                pass  # se não houver permissão de escrita, segue só com o log em tela

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._config.update(saved)
            except Exception:
                pass

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível salvar config:\n{e}")

    def _build_ui(self):
        self._style = ttk.Style(self)
        self._style.theme_use("clam")
        self._style.configure("TNotebook", background=DARK["bg"], borderwidth=0)
        self._style.configure("TNotebook.Tab",
            background=DARK["card"], foreground=DARK["text_muted"],
            padding=[18, 8], font=("Consolas", 10, "bold"), borderwidth=0)
        self._style.map("TNotebook.Tab",
            background=[("selected", DARK["accent"])],
            foreground=[("selected", "#ffffff")])
        self._style.configure("TFrame", background=DARK["bg"])
        self._style.configure("Card.TFrame", background=DARK["card"])
        self._style.configure("Vertical.TScrollbar",
            background=DARK["border"], troughcolor=DARK["panel"],
            arrowcolor=DARK["text_muted"], borderwidth=0)

        header = tk.Frame(self, bg=DARK["panel"], height=56)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(header, text="◈ Monitor de Logs ATI",
            font=("Consolas", 16, "bold"), bg=DARK["panel"],
            fg=DARK["accent"]).pack(side="left", padx=20, pady=10)

        self._status_dot = tk.Label(header, text="●", font=("Consolas", 18),
            bg=DARK["panel"], fg=DARK["text_muted"])
        self._status_dot.pack(side="right", padx=8, pady=10)

        self._status_label = tk.Label(header, text="PARADO",
            font=("Consolas", 10, "bold"), bg=DARK["panel"], fg=DARK["text_muted"])
        self._status_label.pack(side="right", padx=0, pady=10)

        self._btn_toggle = tk.Button(header,
            text="▶  INICIAR", font=("Consolas", 10, "bold"),
            bg=DARK["success"], fg="#000000", relief="flat",
            padx=16, pady=6, cursor="hand2",
            command=self._toggle_monitor)
        self._btn_toggle.pack(side="right", padx=16, pady=10)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=0, pady=0)

        self._tab_config = ttk.Frame(notebook)
        self._tab_log = ttk.Frame(notebook)
        self._tab_history = ttk.Frame(notebook)

        notebook.add(self._tab_config,  text="  ⚙  Configurações  ")
        notebook.add(self._tab_log,     text="  📋  Log em Tempo Real  ")
        notebook.add(self._tab_history, text="  🔔  Histórico de Alertas  ")

        self._build_config_tab()
        self._build_log_tab()
        self._build_history_tab()

    def _section_label(self, parent, text):
        f = tk.Frame(parent, bg=DARK["card"])
        tk.Label(f, text=text, font=("Consolas", 10, "bold"),
            bg=DARK["card"], fg=DARK["accent"]).pack(side="left")
        tk.Frame(f, bg=DARK["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(10, 0), pady=6)
        f.pack(fill="x", pady=(16, 4))

    def _field(self, parent, label, key, show=None, width=32):
        row = tk.Frame(parent, bg=DARK["card"])
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, width=28, anchor="w",
            font=("Consolas", 9), bg=DARK["card"],
            fg=DARK["text_muted"]).pack(side="left")
        var = tk.StringVar(value=str(self._config.get(key, "")))
        entry = tk.Entry(row, textvariable=var, width=width,
            font=("Consolas", 9), bg=DARK["input_bg"],
            fg=DARK["text"], insertbackground=DARK["text"],
            relief="flat", bd=4,
            show=show if show else "")
        entry.pack(side="left", padx=(0, 8))
        var.trace_add("write", lambda *a: self._config.update({key: var.get()}))
        return var

    def _checkbox(self, parent, label, key):
        var = tk.BooleanVar(value=bool(self._config.get(key, False)))
        cb = tk.Checkbutton(parent, text=label, variable=var,
            font=("Consolas", 9), bg=DARK["card"],
            fg=DARK["text"], selectcolor=DARK["input_bg"],
            activebackground=DARK["card"], activeforeground=DARK["text"],
            relief="flat", cursor="hand2")
        cb.pack(anchor="w", pady=2)
        var.trace_add("write", lambda *a: self._config.update({key: var.get()}))
        return var

    def _build_config_tab(self):
        canvas = tk.Canvas(self._tab_config, bg=DARK["bg"], highlightthickness=0)
        scroll = ttk.Scrollbar(self._tab_config, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=DARK["bg"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def on_canvas_resize(e):
            canvas.itemconfig(win_id, width=e.width)

        inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_canvas_resize)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        cols = tk.Frame(inner, bg=DARK["bg"])
        cols.pack(fill="both", expand=True, padx=16, pady=16)

        left  = tk.Frame(cols, bg=DARK["card"], bd=0, relief="flat")
        right = tk.Frame(cols, bg=DARK["card"], bd=0, relief="flat")

        for f in (left, right):
            f.pack(side="left", fill="both", expand=True, padx=6, pady=4, ipadx=16, ipady=8)

        self._section_label(left, "📥  IMAP — Leitura de Emails")
        self._field(left, "Servidor IMAP",    "imap_host")
        self._field(left, "Porta",            "imap_port", width=8)
        self._field(left, "Usuário",          "imap_username")
        self._field(left, "Senha",            "imap_password", show="•")
        self._field(left, "Caixa (Mailbox)",  "imap_mailbox", width=16)
        self._checkbox(left, "Usar SSL",      "imap_use_ssl")

        self._section_label(left, "📤  SMTP — Envio de Alertas")
        self._field(left, "Servidor SMTP",    "smtp_host")
        self._field(left, "Porta",            "smtp_port", width=8)
        self._field(left, "Usuário",          "smtp_username")
        self._field(left, "Senha",            "smtp_password", show="•")
        self._field(left, "Email remetente",  "email_from")
        self._field(left, "Nome remetente",   "email_from_name")
        self._checkbox(left, "Usar TLS (STARTTLS)", "smtp_use_tls")
        self._checkbox(left, "Usar SSL direto",     "smtp_use_ssl")
        self._checkbox(left, "Verificar hostname do certificado SMTP\n(desligue só se conectar por IP)", "smtp_verify_hostname")
        self._checkbox(left, "Verificar validade do certificado SMTP\n(desligue só temporariamente, se o certificado do\nservidor estiver expirado/inválido)", "smtp_verify_cert")

        btn_row = tk.Frame(left, bg=DARK["card"])
        btn_row.pack(fill="x", pady=(12, 4))
        tk.Button(btn_row, text="🔌  Testar IMAP",
            font=("Consolas", 9, "bold"), bg=DARK["accent"], fg="#fff",
            relief="flat", padx=10, pady=5, cursor="hand2",
            command=self._test_imap).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="📡  Testar SMTP",
            font=("Consolas", 9, "bold"), bg=DARK["accent2"], fg="#fff",
            relief="flat", padx=10, pady=5, cursor="hand2",
            command=self._test_smtp).pack(side="left")

        self._section_label(right, "📬  Destinatários dos Alertas")
        tk.Label(right, text="Emails (um por linha):",
            font=("Consolas", 9), bg=DARK["card"], fg=DARK["text_muted"],
            anchor="w").pack(fill="x")
        self._recipients_box = tk.Text(right, height=5, width=36,
            font=("Consolas", 9), bg=DARK["input_bg"], fg=DARK["text"],
            insertbackground=DARK["text"], relief="flat", bd=4)
        self._recipients_box.insert("1.0", self._config.get("email_recipients", ""))
        self._recipients_box.pack(fill="x", pady=(2, 0))
        self._recipients_box.bind("<FocusOut>",
            lambda e: self._config.update({"email_recipients": self._recipients_box.get("1.0", "end-1c")}))

        self._section_label(right, "⏱  Parâmetros de Detecção")
        self._field(right, "Intervalo polling (min)",    "polling_interval",   width=8)
        self._field(right, "Janela de detecção (horas)", "dedup_window_hours", width=8)
        self._field(right, "Mín. ocorrências p/ alerta", "min_occurrences",    width=8)

        self._section_label(right, "🔍  Filtros Avançados (opcional)")
        self._field(right, "Palavras-chave assunto",  "log_subject_keywords", width=36)
        self._field(right, "Regex Conjunto",          "regex_conjunto",       width=36)
        self._field(right, "Regex Erro",              "regex_erro",           width=36)

        save_bar = tk.Frame(inner, bg=DARK["bg"])
        save_bar.pack(fill="x", padx=16, pady=(8, 16))
        tk.Button(save_bar, text="💾  Salvar Configurações",
            font=("Consolas", 10, "bold"), bg=DARK["success"], fg="#000",
            relief="flat", padx=20, pady=8, cursor="hand2",
            command=self._on_save).pack(side="left")

    def _build_log_tab(self):
        bar = tk.Frame(self._tab_log, bg=DARK["bg"])
        bar.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(bar, text="Log em Tempo Real", font=("Consolas", 11, "bold"),
            bg=DARK["bg"], fg=DARK["text"]).pack(side="left")
        tk.Button(bar, text="🗑  Limpar", font=("Consolas", 9),
            bg=DARK["card"], fg=DARK["text_muted"], relief="flat",
            padx=10, pady=4, cursor="hand2",
            command=lambda: self._log_box.delete("1.0", "end")).pack(side="right")

        self._log_box = scrolledtext.ScrolledText(
            self._tab_log, font=("Consolas", 9),
            bg=DARK["input_bg"], fg=DARK["text"],
            insertbackground=DARK["text"], relief="flat",
            state="disabled", wrap="word")
        self._log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._log_box.tag_config("ERROR",   foreground=DARK["danger"])
        self._log_box.tag_config("WARNING", foreground=DARK["warning"])
        self._log_box.tag_config("INFO",    foreground=DARK["success"])
        self._log_box.tag_config("DEBUG",   foreground=DARK["text_muted"])

    def _build_history_tab(self):
        bar = tk.Frame(self._tab_history, bg=DARK["bg"])
        bar.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(bar, text="Alertas Enviados", font=("Consolas", 11, "bold"),
            bg=DARK["bg"], fg=DARK["text"]).pack(side="left")
        tk.Button(bar, text="🗑  Limpar", font=("Consolas", 9),
            bg=DARK["card"], fg=DARK["text_muted"], relief="flat",
            padx=10, pady=4, cursor="hand2",
            command=self._clear_history).pack(side="right")

        cols = ("data", "conjunto", "erro", "ocorrencias", "status")
        self._tree = ttk.Treeview(self._tab_history, columns=cols,
            show="headings", selectmode="browse")

        self._style.configure("Treeview",
            background=DARK["input_bg"], foreground=DARK["text"],
            rowheight=28, fieldbackground=DARK["input_bg"],
            font=("Consolas", 9))
        self._style.configure("Treeview.Heading",
            background=DARK["card"], foreground=DARK["accent"],
            font=("Consolas", 9, "bold"), relief="flat")
        self._style.map("Treeview", background=[("selected", DARK["accent"])])

        headers = {"data": ("Data/Hora", 140), "conjunto": ("Conjunto", 200),
            "erro": ("Erro", 280), "ocorrencias": ("Ocorr.", 70), "status": ("Status", 100)}
        for col, (head, w) in headers.items():
            self._tree.heading(col, text=head)
            self._tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(self._tab_history, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y", pady=(0, 12))
        self._tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _on_save(self):
        self._config["email_recipients"] = self._recipients_box.get("1.0", "end-1c")
        self._save_config()
        self._write_config_py()
        messagebox.showinfo("Salvo", "Configurações salvas com sucesso!")

    def _write_config_py(self):
        c = self._config
        recipients_raw = c.get("email_recipients", "")
        recipients_list = [r.strip() for r in recipients_raw.replace(",", "\n").splitlines() if r.strip()]
        recipients_str = "\n".join(f'    "{r}",' for r in recipients_list)

        content = f'''IMAP_HOST = "{c["imap_host"]}"
IMAP_PORT = {c["imap_port"]}
IMAP_USE_SSL = {c["imap_use_ssl"]}
IMAP_USERNAME = "{c["imap_username"]}"
IMAP_PASSWORD = "{c["imap_password"]}"
IMAP_MAILBOX = "{c["imap_mailbox"]}"

SMTP_HOST = "{c["smtp_host"]}"
SMTP_PORT = {c["smtp_port"]}
SMTP_USE_TLS = {c["smtp_use_tls"]}
SMTP_USE_SSL = {c["smtp_use_ssl"]}
SMTP_VERIFY_HOSTNAME = {c["smtp_verify_hostname"]}
SMTP_VERIFY_CERT = {c["smtp_verify_cert"]}
SMTP_USERNAME = "{c["smtp_username"]}"
SMTP_PASSWORD = "{c["smtp_password"]}"
EMAIL_FROM = "{c["email_from"]}"
EMAIL_FROM_NAME = "{c["email_from_name"]}"

EMAIL_RECIPIENTS = [
{recipients_str}
]

POLLING_INTERVAL_MINUTES = {c["polling_interval"]}
DEDUP_WINDOW_HOURS = {c["dedup_window_hours"]}
MIN_OCCURRENCES_TO_ALERT = {c["min_occurrences"]}

LOG_SUBJECT_KEYWORDS = {json.dumps([k.strip() for k in c["log_subject_keywords"].split(",") if k.strip()], ensure_ascii=False)}
REGEX_CONJUNTO = r"{c["regex_conjunto"]}"
REGEX_ERRO = r"{c["regex_erro"]}"

LOG_FILE = "monitor.log"
LOG_LEVEL = "INFO"
'''
        try:
            with open("config.py", "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            self._logger.error(f"Erro ao gerar config.py: {e}")

    def _toggle_monitor(self):
        if self._running:
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self):
        self._config["email_recipients"] = self._recipients_box.get("1.0", "end-1c")
        self._save_config()
        self._write_config_py()

        self._running = True
        self._stop_event.clear()
        self._btn_toggle.config(text="⏹  PARAR", bg=DARK["danger"], fg="#fff")
        self._status_dot.config(fg=DARK["success"])
        self._status_label.config(text="RODANDO", fg=DARK["success"])
        self._logger.info("Monitor iniciado.")

        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_monitor(self):
        self._running = False
        self._stop_event.set()
        self._btn_toggle.config(text="▶  INICIAR", bg=DARK["success"], fg="#000")
        self._status_dot.config(fg=DARK["text_muted"])
        self._status_label.config(text="PARADO", fg=DARK["text_muted"])
        self._logger.info("Monitor parado pelo usuário.")

    def _monitor_loop(self):
        try:
            import config as cfg
            importlib_reload = False
            try:
                import importlib
                importlib.reload(cfg)
                importlib_reload = True
            except Exception:
                pass

            from tracker import OccurrenceTracker
            tracker = OccurrenceTracker(
                window_hours=int(cfg.DEDUP_WINDOW_HOURS),
                min_occurrences=int(cfg.MIN_OCCURRENCES_TO_ALERT),
            )

            while not self._stop_event.is_set():
                try:
                    self._run_cycle(cfg, tracker)
                except Exception as e:
                    self._logger.error(f"Erro no ciclo: {e}", exc_info=True)

                interval = int(cfg.POLLING_INTERVAL_MINUTES) * 60
                self._logger.info(f"Próxima verificação em {cfg.POLLING_INTERVAL_MINUTES} minuto(s)...")
                self._stop_event.wait(timeout=interval)

        except Exception as e:
            self._logger.error(f"Erro fatal no monitor: {e}", exc_info=True)
            self.after(0, self._stop_monitor)

    def _run_cycle(self, cfg, tracker):
        from imap_reader import IMAPReader
        from parser import extract_conjunto_and_erro, extract_body, parse_raw_email
        from alert import send_alert

        self._logger.info("Iniciando ciclo de verificação...")

        with IMAPReader(
            host=cfg.IMAP_HOST, port=cfg.IMAP_PORT,
            username=cfg.IMAP_USERNAME, password=cfg.IMAP_PASSWORD,
            use_ssl=cfg.IMAP_USE_SSL, mailbox=cfg.IMAP_MAILBOX,
            exclude_from=getattr(cfg, "IMAP_EXCLUDE_FROM", None),
            exclude_subject_keywords=getattr(cfg, "IMAP_EXCLUDE_SUBJECT_KEYWORDS", None),
        ) as reader:
            if not reader._conn:
                self._logger.error("Falha na conexão IMAP. Pulando ciclo.")
                return

            keywords = cfg.LOG_SUBJECT_KEYWORDS if cfg.LOG_SUBJECT_KEYWORDS else None
            emails = reader.fetch_unread(subject_keywords=keywords)

            if not emails:
                self._logger.info("Nenhum email novo para processar.")
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
                        status = "✅ Enviado" if sucesso else "❌ Falha"
                        self._logger.info(f"Alerta [{status}]: conjunto='{conjunto}' | erro='{erro}'")
                        self.after(0, self._add_history_row,
                            conjunto, erro, total, status)

                    reader.mark_as_read(msg_id)
                except Exception as e:
                    self._logger.error(f"Erro ao processar email {msg_id}: {e}", exc_info=True)

        self._logger.info("Ciclo finalizado.")

    def _add_history_row(self, conjunto, erro, ocorrencias, status):
        ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self._alert_history.append((ts, conjunto, erro, ocorrencias, status))
        self._tree.insert("", 0, values=(ts, conjunto, erro, ocorrencias, status))

    def _clear_history(self):
        self._alert_history.clear()
        for row in self._tree.get_children():
            self._tree.delete(row)

    def _test_imap(self):
        def _run():
            try:
                import imaplib
                host = self._config["imap_host"]
                port = int(self._config["imap_port"])
                ssl = self._config["imap_use_ssl"]
                user = self._config["imap_username"]
                pwd = self._config["imap_password"]
                self._logger.info(f"Testando IMAP {host}:{port}...")
                if ssl:
                    conn = imaplib.IMAP4_SSL(host, port)
                else:
                    conn = imaplib.IMAP4(host, port)
                conn.login(user, pwd)
                conn.logout()
                self._logger.info("✅ Conexão IMAP bem-sucedida!")
                self.after(0, messagebox.showinfo, "IMAP OK", "Conexão IMAP bem-sucedida!")
            except Exception as e:
                self._logger.error(f"❌ Falha no teste IMAP: {e}")
                self.after(0, messagebox.showerror, "IMAP Falhou", str(e))
        threading.Thread(target=_run, daemon=True).start()

    def _test_smtp(self):
        def _run():
            try:
                import smtplib
                host = self._config["smtp_host"]
                port = int(self._config["smtp_port"])
                ssl = self._config["smtp_use_ssl"]
                tls = self._config["smtp_use_tls"]
                user = self._config["smtp_username"]
                pwd = self._config["smtp_password"]
                self._logger.info(f"Testando SMTP {host}:{port}...")
                if ssl:
                    server = smtplib.SMTP_SSL(host, port, timeout=10)
                else:
                    server = smtplib.SMTP(host, port, timeout=10)
                server.ehlo()
                if tls and not ssl:
                    server.starttls()
                    server.ehlo()
                if user and pwd:
                    server.login(user, pwd)
                server.quit()
                self._logger.info("✅ Conexão SMTP bem-sucedida!")
                self.after(0, messagebox.showinfo, "SMTP OK", "Conexão SMTP bem-sucedida!")
            except Exception as e:
                self._logger.error(f"❌ Falha no teste SMTP: {e}")
                self.after(0, messagebox.showerror, "SMTP Falhou", str(e))
        threading.Thread(target=_run, daemon=True).start()

    def _poll_log_queue(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._log_box.config(state="normal")
                tag = "INFO"
                for level in ("ERROR", "WARNING", "DEBUG", "INFO"):
                    if f"[{level}]" in msg:
                        tag = level
                        break
                self._log_box.insert("end", msg + "\n", tag)
                self._log_box.see("end")
                self._log_box.config(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._poll_log_queue)


if __name__ == "__main__":
    app = MonitorApp()
    app.mainloop()