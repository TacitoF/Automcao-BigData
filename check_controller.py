"""Consulta um controlador usando config.py, sem enviar email ou alterar o estado."""

import argparse
import sys

from controller_directory import ControllerDirectory, ControllerLookupError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("conjunto", help="Nome extraído do email de log")
    args = parser.parse_args()
    try:
        import config as cfg
    except ImportError:
        print("Crie config.py a partir de config.py.example ou salve pela GUI.", file=sys.stderr)
        return 1
    if not getattr(cfg, "CONTROLLER_DB_ENABLED", False):
        print("Ative CONTROLLER_DB_ENABLED em config.py para testar o banco.", file=sys.stderr)
        return 1
    try:
        with ControllerDirectory(cfg) as directory:
            recipients = directory.recipients_for(args.conjunto)
    except ControllerLookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Controlador(es) encontrado(s): " + ", ".join(recipients))
    return 0


if __name__ == "__main__":
    sys.exit(main())
