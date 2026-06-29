import subprocess
import sys
import os
import shutil
from pathlib import Path


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"PyInstaller encontrado: {PyInstaller.__version__}")
    except ImportError:
        print("PyInstaller não encontrado. Instalando...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("PyInstaller instalado.")


def get_desktop_path():
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Área de Trabalho"
    return desktop


def clean_build_dirs():
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"Pasta '{folder}' removida.")


def build_gui():
    """Gera o executável COM interface gráfica (para configurar e testar localmente)."""
    print("\nGerando executável da GUI (configuração/uso manual)...\n")
    clean_build_dirs()

    sep = os.pathsep

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "monitor_logs_ati",
        "--add-data", f"gui.py{sep}.",
        "--add-data", f"imap_reader.py{sep}.",
        "--add-data", f"parser.py{sep}.",
        "--add-data", f"tracker.py{sep}.",
        "--add-data", f"alert.py{sep}.",
        "--add-data", f"tls_compat.py{sep}.",
        "main.py",
    ]

    print("Comando:", " ".join(cmd))
    print()

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        exe_path = os.path.join("dist", "monitor_logs_ati.exe")
        config_path = "config.py"

        if os.path.exists(exe_path):
            desktop_dir = get_desktop_path()
            target_folder = desktop_dir / "Monitor_Logs_ATI"
            target_folder.mkdir(parents=True, exist_ok=True)

            shutil.copy(exe_path, target_folder / "monitor_logs_ati.exe")

            if os.path.exists(config_path):
                shutil.copy(config_path, target_folder / "config.py")

            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n✅ Executável da GUI gerado com sucesso!")
            print(f"Tamanho: {size_mb:.1f} MB")
            print(f"Pasta: {target_folder}")
            print("Use este executável para configurar (IMAP/SMTP/regex) e gerar o config.py.")
        else:
            print("\nBuild concluído mas .exe não encontrado na pasta dist/")
    else:
        print(f"\nFalha no build (código: {result.returncode})")
        sys.exit(1)


def build_service():
    """Gera o executável HEADLESS (sem janela, sem Tkinter) para rodar no servidor."""
    print("\nGerando executável de SERVIÇO (headless, para rodar no servidor)...\n")
    clean_build_dirs()

    sep = os.pathsep

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",  # mantém um console mínimo; útil se rodar manualmente para depurar
        "--name", "monitor_logs_ati_service",
        "--add-data", f"imap_reader.py{sep}.",
        "--add-data", f"parser.py{sep}.",
        "--add-data", f"tracker.py{sep}.",
        "--add-data", f"alert.py{sep}.",
        "--add-data", f"tls_compat.py{sep}.",
        "service.py",
    ]

    print("Comando:", " ".join(cmd))
    print()

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        exe_path = os.path.join("dist", "monitor_logs_ati_service.exe")

        if os.path.exists(exe_path):
            desktop_dir = get_desktop_path()
            target_folder = desktop_dir / "Monitor_Logs_ATI_Servico"
            target_folder.mkdir(parents=True, exist_ok=True)

            shutil.copy(exe_path, target_folder / "monitor_logs_ati_service.exe")

            config_path = "config.py"
            if os.path.exists(config_path):
                shutil.copy(config_path, target_folder / "config.py")

            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n✅ Executável de serviço gerado com sucesso!")
            print(f"Tamanho: {size_mb:.1f} MB")
            print(f"Pasta: {target_folder}")
            print("Copie esta pasta (exe + config.py) para o servidor e registre como")
            print("serviço do Windows com o NSSM (veja DEPLOY.md).")
        else:
            print("\nBuild concluído mas .exe não encontrado na pasta dist/")
    else:
        print(f"\nFalha no build (código: {result.returncode})")
        sys.exit(1)


if __name__ == "__main__":
    check_pyinstaller()

    modo = sys.argv[1] if len(sys.argv) > 1 else "all"

    if modo == "gui":
        build_gui()
    elif modo == "service":
        build_service()
    else:
        build_gui()
        build_service()
        print("\n" + "=" * 60)
        print("Dois executáveis foram gerados:")
        print("  1) monitor_logs_ati.exe          -> GUI, use na sua máquina para configurar")
        print("  2) monitor_logs_ati_service.exe  -> headless, deploy no servidor (NSSM)")
        print("=" * 60)