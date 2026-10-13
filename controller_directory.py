"""Relaciona o nome do conjunto aos emails dos controladores no banco."""

import os
from email.headerregistry import Address
from typing import Iterable, List


DEFAULT_CONTROLLER_QUERY = (
    "SELECT email_controlador FROM conjunto_controlador "
    "WHERE LOWER(TRIM(nome_conjunto)) = :conjunto"
)


class ControllerLookupError(RuntimeError):
    """Falha de configuração, consulta ou cadastro de controlador."""


def validate_recipients(values: Iterable[str]) -> List[str]:
    """Exige um endereço por linha e elimina emails repetidos."""
    if isinstance(values, (str, bytes)):
        raise ControllerLookupError("Os destinatários devem ser uma lista de emails.")
    recipients = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            raise ControllerLookupError("Há um email vazio ou inválido no cadastro.")
        value = value.strip()
        try:
            parsed = Address(addr_spec=value)
            if (not parsed.username or not parsed.domain
                    or any(ch.isspace() for ch in value)
                    or any(ch in value for ch in "<>,;")):
                raise ValueError("Endereço inválido")
        except (ValueError, TypeError, IndexError):
            raise ControllerLookupError("Há um email vazio ou inválido no cadastro.") from None
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            recipients.append(value)
    if not recipients:
        raise ControllerLookupError("Nenhum controlador encontrado para este conjunto.")
    return recipients


class ControllerDirectory:
    """Consulta parametrizada; a URL com credenciais fica no ambiente da VM."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = bool(getattr(cfg, "CONTROLLER_DB_ENABLED", False))
        self._engine = None
        self._statement = None

    def _prepare(self):
        env_name = getattr(self.cfg, "CONTROLLER_DB_URL_ENV", "MONITOR_DATABASE_URL")
        if not isinstance(env_name, str) or not env_name:
            raise ControllerLookupError("CONTROLLER_DB_URL_ENV deve conter o nome da variável de ambiente.")
        url = os.environ.get(env_name, "")
        if not url:
            raise ControllerLookupError(
                "Defina a variável de ambiente do banco indicada em CONTROLLER_DB_URL_ENV."
            )
        query = getattr(self.cfg, "CONTROLLER_DB_QUERY", DEFAULT_CONTROLLER_QUERY)
        connect_args = getattr(self.cfg, "CONTROLLER_DB_CONNECT_ARGS", {})
        if not isinstance(query, str) or not isinstance(connect_args, dict):
            raise ControllerLookupError("Configuração de consulta/conexão ao banco inválida.")
        try:
            from sqlalchemy import bindparam, create_engine, text
            # bindparams também verifica que :conjunto existe na consulta.
            self._statement = text(query).bindparams(bindparam("conjunto"))
            self._engine = create_engine(
                url, connect_args=connect_args, pool_pre_ping=True,
                echo=False, hide_parameters=True,
            )
        except ImportError:
            raise ControllerLookupError(
                "Instale SQLAlchemy e o driver do seu banco antes de ativar a consulta."
            ) from None
        except Exception as exc:
            # Não propaga URLs, senhas ou argumentos de conexão para o log.
            raise ControllerLookupError(
                "Não foi possível preparar a consulta ao banco (%s). "
                "Confira a URL, o driver e o parâmetro :conjunto." % type(exc).__name__
            ) from None

    def recipients_for(self, conjunto: str) -> List[str]:
        """Recebe um nome; :conjunto é passado sem espaços externos e em minúsculas."""
        if not self.enabled:
            return validate_recipients(getattr(self.cfg, "EMAIL_RECIPIENTS", []))
        if not conjunto or not conjunto.strip():
            raise ControllerLookupError("Nome do conjunto vazio; consulta cancelada.")
        if self._engine is None:
            self._prepare()
        try:
            with self._engine.connect() as connection:
                result = connection.execute(
                    self._statement, {"conjunto": conjunto.strip().lower()}
                )
                # A primeira coluna do SELECT deve conter um email por linha.
                values = list(result.scalars())
        except Exception as exc:
            raise ControllerLookupError(
                "Falha ao consultar o controlador (%s). "
                "Confira acesso ao banco, tabela e colunas." % type(exc).__name__
            ) from None
        return validate_recipients(values)

    def close(self):
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
