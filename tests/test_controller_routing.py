import contextlib
import io
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alert import send_alert
from controller_directory import (
    ControllerDirectory, ControllerLookupError, DEFAULT_CONTROLLER_QUERY,
    validate_recipients,
)
from monitor_cycle import run_cycle
from tracker import OccurrenceTracker


def config(**overrides):
    values = dict(
        CONTROLLER_DB_ENABLED=True,
        CONTROLLER_DB_URL_ENV="TEST_MONITOR_DATABASE_URL",
        CONTROLLER_DB_QUERY=DEFAULT_CONTROLLER_QUERY,
        EMAIL_RECIPIENTS=["equipe@example.invalid"],
        IMAP_HOST="imap.example.invalid", IMAP_PORT=993, IMAP_USE_SSL=True,
        IMAP_USERNAME="", IMAP_PASSWORD="", IMAP_MAILBOX="INBOX",
        SMTP_HOST="smtp.example.invalid", SMTP_PORT=587,
        SMTP_USERNAME="", SMTP_PASSWORD="", SMTP_USE_TLS=False, SMTP_USE_SSL=False,
        EMAIL_FROM="monitor@example.invalid", EMAIL_FROM_NAME="Monitor",
        LOG_SUBJECT_KEYWORDS=[], REGEX_CONJUNTO="", REGEX_ERRO="",
        DEDUP_WINDOW_HOURS=24,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def raw_message(message_id, conjunto="BASE_A"):
    header = "Message-ID: <%s>\r\n" % message_id if message_id else ""
    return (header + "Subject: Falha de ingestao\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            "Conjunto: %s\r\nErro: socket hang up\r\n" % conjunto).encode("utf-8")


class DatabaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "controladores.db"
        self.state = str(Path(self.temp.name) / "state.json")
        self.env = patch.dict(os.environ, {
            "TEST_MONITOR_DATABASE_URL": "sqlite:///" + str(self.database),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.insert_mapping("base_a", "controlador.a@example.invalid")
        self.insert_mapping("base_b", "controlador.b@example.invalid")

    def insert_mapping(self, name, email):
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS conjunto_controlador "
                       "(nome_conjunto TEXT, email_controlador TEXT)")
            db.execute("INSERT INTO conjunto_controlador VALUES (?, ?)", (name, email))

    def tracker(self):
        return OccurrenceTracker(state_file=self.state, min_occurrences=2)


class DirectoryTests(DatabaseFixture):
    def test_correct_controller_and_normalization(self):
        with ControllerDirectory(config()) as directory:
            self.assertEqual(directory.recipients_for("  BASE_A  "),
                             ["controlador.a@example.invalid"])
            self.assertEqual(directory.recipients_for("BASE_B"),
                             ["controlador.b@example.invalid"])

    def test_multiple_controllers_and_duplicate_emails(self):
        self.insert_mapping("BASE_A", "CONTROLADOR.A@example.invalid")
        self.insert_mapping("base_a", "segundo@example.invalid")
        with ControllerDirectory(config()) as directory:
            self.assertEqual(directory.recipients_for("base_a"),
                             ["controlador.a@example.invalid", "segundo@example.invalid"])

    def test_unknown_dataset_has_no_fixed_recipient_fallback(self):
        with ControllerDirectory(config()) as directory:
            with self.assertRaises(ControllerLookupError):
                directory.recipients_for("base_inexistente")

    def test_injection_is_treated_as_a_dataset_name(self):
        conjunto = "base_a' OR 1=1 --"
        with ControllerDirectory(config()) as directory:
            with self.assertRaises(ControllerLookupError):
                directory.recipients_for(conjunto)
        self.insert_mapping(conjunto, "literal@example.invalid")
        with ControllerDirectory(config()) as directory:
            self.assertEqual(directory.recipients_for(conjunto), ["literal@example.invalid"])

    def test_database_changes_are_used_by_next_lookup(self):
        with ControllerDirectory(config()) as directory:
            directory.recipients_for("base_a")
            with sqlite3.connect(self.database) as db:
                db.execute("UPDATE conjunto_controlador SET email_controlador=? "
                           "WHERE nome_conjunto=?", ("novo@example.invalid", "base_a"))
            self.assertEqual(directory.recipients_for("base_a"), ["novo@example.invalid"])

    def test_custom_join_query(self):
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE conjuntos (nome TEXT, controlador_id INTEGER)")
            db.execute("CREATE TABLE controladores (id INTEGER, email TEXT)")
            db.execute("INSERT INTO conjuntos VALUES ('base_c', 1)")
            db.execute("INSERT INTO controladores VALUES (1, 'c@example.invalid')")
        query = ("SELECT c.email FROM conjuntos d JOIN controladores c "
                 "ON c.id=d.controlador_id WHERE LOWER(TRIM(d.nome))=:conjunto")
        with ControllerDirectory(config(CONTROLLER_DB_QUERY=query)) as directory:
            self.assertEqual(directory.recipients_for("BASE_C"), ["c@example.invalid"])

    def test_missing_env_and_query_parameter_fail_safely(self):
        with patch.dict(os.environ, {"TEST_MONITOR_DATABASE_URL": ""}):
            with ControllerDirectory(config()) as directory:
                with self.assertRaises(ControllerLookupError):
                    directory.recipients_for("base_a")
        with ControllerDirectory(config(CONTROLLER_DB_QUERY="SELECT email_controlador FROM conjunto_controlador")) as directory:
            with self.assertRaises(ControllerLookupError):
                directory.recipients_for("base_a")

    def test_invalid_schema_and_connection_do_not_expose_secrets(self):
        with ControllerDirectory(config(CONTROLLER_DB_QUERY="SELECT email FROM missing WHERE nome=:conjunto")) as directory:
            with self.assertRaises(ControllerLookupError):
                directory.recipients_for("base_a")
        with patch("sqlalchemy.create_engine", side_effect=RuntimeError("password=SEGREDO")):
            with ControllerDirectory(config()) as directory:
                with self.assertRaises(ControllerLookupError) as caught:
                    directory.recipients_for("base_a")
                self.assertNotIn("SEGREDO", str(caught.exception))

    def test_null_or_invalid_email_blocks_dispatch(self):
        for name, address in (("null", None), ("invalid", "sem-email"),
                              ("headers", "a@example.invalid\r\nBcc: b@example.invalid")):
            self.insert_mapping(name, address)
            with ControllerDirectory(config()) as directory:
                with self.assertRaises(ControllerLookupError):
                    directory.recipients_for(name)

    def test_disabled_database_retains_fixed_recipients(self):
        with ControllerDirectory(config(CONTROLLER_DB_ENABLED=False)) as directory:
            self.assertEqual(directory.recipients_for("base_a"), ["equipe@example.invalid"])
            self.assertIsNone(directory._engine)
        with self.assertRaises(ControllerLookupError):
            validate_recipients([])

    def test_dry_run_cli_resolves_controller_without_smtp(self):
        from check_controller import main
        output = io.StringIO()
        with patch.dict(sys.modules, {"config": config()}), \
                patch("sys.argv", ["check_controller.py", "BASE_A"]), \
                patch("alert.smtplib.SMTP") as smtp, contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertIn("controlador.a@example.invalid", output.getvalue())
        smtp.assert_not_called()


class CycleTests(DatabaseFixture):
    def cycle(self, tracker, messages, smtp_success=True, cfg=None):
        reader = Mock()
        reader._conn = True
        reader.fetch_unread.return_value = messages
        reader.__enter__ = Mock(return_value=reader)
        reader.__exit__ = Mock(return_value=False)
        callback = Mock()
        with patch("monitor_cycle.IMAPReader", return_value=reader), \
                patch("monitor_cycle.send_alert", return_value=smtp_success) as sender:
            run_cycle(cfg or config(), tracker, logging.getLogger("test_cycle"), callback)
        return reader, sender, callback

    def test_full_cycle_routes_each_dataset_to_its_own_controller(self):
        tracker = self.tracker()
        messages = [(str(i), raw_message(str(i), dataset))
                    for i, dataset in enumerate(("BASE_A", "BASE_B", "BASE_A", "BASE_B"), 1)]
        reader, sender, callback = self.cycle(tracker, messages)
        self.assertEqual(sender.call_count, 2)
        self.assertEqual([c.kwargs["recipients"] for c in sender.call_args_list],
                         [["controlador.a@example.invalid"], ["controlador.b@example.invalid"]])
        self.assertEqual(reader.mark_as_read.call_count, 4)
        self.assertTrue(all(row["alerta_enviado"] for row in tracker.summary()))
        self.assertEqual(callback.call_count, 2)

    def test_missing_controller_retries_after_restart_without_recounting(self):
        first = raw_message("first", "NOVO_CONJUNTO")
        second = raw_message("second", "NOVO_CONJUNTO")
        tracker = self.tracker()
        reader, sender, callback = self.cycle(tracker, [("1", first), ("2", second)])
        sender.assert_not_called()
        reader.mark_as_read.assert_called_once_with("1")
        self.assertFalse(tracker.summary()[0]["alerta_enviado"])
        self.assertFalse(callback.call_args.args[-1])
        self.insert_mapping("novo_conjunto", "novo@example.invalid")
        tracker = self.tracker()  # Estado persistido entre processos.
        reader, sender, _ = self.cycle(tracker, [("7", second)])
        sender.assert_called_once()
        self.assertEqual(sender.call_args.kwargs["ocorrencias"], 2)
        self.assertEqual(sender.call_args.kwargs["recipients"], ["novo@example.invalid"])
        reader.mark_as_read.assert_called_once_with("7")
        self.assertTrue(tracker.summary()[0]["alerta_enviado"])

    def test_smtp_failure_keeps_message_pending_until_success(self):
        tracker = self.tracker()
        second = raw_message("second")
        reader, sender, _ = self.cycle(tracker, [("1", raw_message("first")), ("2", second)], False)
        reader.mark_as_read.assert_called_once_with("1")
        self.assertFalse(tracker.summary()[0]["alerta_enviado"])
        tracker = self.tracker()
        reader, sender, _ = self.cycle(tracker, [("2", second)])
        self.assertEqual(sender.call_args.kwargs["ocorrencias"], 2)
        reader.mark_as_read.assert_called_once_with("2")
        _, sender, _ = self.cycle(tracker, [("2", second)])
        sender.assert_not_called()

    def test_message_without_message_id_does_not_recount_if_imap_number_changes(self):
        tracker = self.tracker()
        raw = raw_message(None)
        self.cycle(tracker, [("1", raw)])
        _, sender, _ = self.cycle(tracker, [("8", raw)])
        sender.assert_not_called()
        self.assertEqual(tracker.summary()[0]["ocorrencias"], 1)

    def test_new_recurrences_can_alert_after_previous_success(self):
        tracker = self.tracker()
        self.cycle(tracker, [("1", raw_message("1")), ("2", raw_message("2"))])
        _, sender, _ = self.cycle(tracker, [("3", raw_message("3"))])
        sender.assert_not_called()
        _, sender, _ = self.cycle(tracker, [("4", raw_message("4"))])
        sender.assert_called_once()

    def test_database_error_retries_when_schema_is_fixed(self):
        tracker = self.tracker()
        second = raw_message("second")
        bad_cfg = config(CONTROLLER_DB_QUERY="SELECT email FROM missing WHERE nome=:conjunto")
        reader, sender, _ = self.cycle(tracker, [("1", raw_message("first")), ("2", second)], cfg=bad_cfg)
        sender.assert_not_called()
        reader.mark_as_read.assert_called_once_with("1")
        _, sender, _ = self.cycle(tracker, [("2", second)])
        sender.assert_called_once()

    def test_fixed_recipient_mode_uses_same_cycle(self):
        _, sender, _ = self.cycle(self.tracker(), [("1", raw_message("1")), ("2", raw_message("2"))],
                                   cfg=config(CONTROLLER_DB_ENABLED=False))
        self.assertEqual(sender.call_args.kwargs["recipients"], ["equipe@example.invalid"])


class ConfigurationAndSMTPTests(unittest.TestCase):
    def test_configuration_preserves_sql_escaping_without_writing_database_url(self):
        from configuration import DEFAULT_CONFIG, build_config_content
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(controller_db_enabled=True,
                   controller_db_query="SELECT email FROM cadastro\nWHERE nome=:conjunto AND status='ativo'",
                   controller_db_connect_args='{"connect_timeout": 10}',
                   smtp_password='aspas" e barra\\')
        with patch.dict(os.environ, {"MONITOR_DATABASE_URL": "SEGREDO"}):
            content = build_config_content(cfg)
        result = {}
        exec(compile(content, "generated_config.py", "exec"), result)
        self.assertEqual(result["CONTROLLER_DB_QUERY"], cfg["controller_db_query"])
        self.assertEqual(result["CONTROLLER_DB_CONNECT_ARGS"], {"connect_timeout": 10})
        self.assertEqual(result["SMTP_PASSWORD"], cfg["smtp_password"])
        self.assertNotIn("SEGREDO", content)

    def test_partial_smtp_refusal_is_not_reported_as_success(self):
        server = Mock()
        server.sendmail.return_value = {"b@example.invalid": (550, b"rejected")}
        with patch("alert.smtplib.SMTP", return_value=server):
            result = send_alert("base", "erro", 2, [],
                                ["a@example.invalid", "b@example.invalid"],
                                "smtp.example.invalid", 587, "", "", "monitor@example.invalid",
                                use_tls=False)
        self.assertFalse(result)
        server.quit.assert_called_once()

    def test_quit_failure_does_not_undo_smtp_acceptance(self):
        server = Mock()
        server.sendmail.return_value = {}
        server.quit.side_effect = OSError("connection closed")
        with patch("alert.smtplib.SMTP", return_value=server):
            result = send_alert("base", "erro", 2, [], ["a@example.invalid"],
                                "smtp.example.invalid", 587, "", "", "monitor@example.invalid",
                                use_tls=False)
        self.assertTrue(result)
        server.close.assert_called_once()

    def test_empty_recipient_list_never_opens_smtp(self):
        with patch("alert.smtplib.SMTP") as server:
            self.assertFalse(send_alert("base", "erro", 2, [], [],
                                       "smtp.example.invalid", 587, "", "", "monitor@example.invalid"))
        server.assert_not_called()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
