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


def build():
    print("\nGerando executável...\n")

    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"Pasta '{folder}' removida.")

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
            print(f"\n✅ Executável gerado com sucesso!")
            print(f"Tamanho: {size_mb:.1f} MB")
            print(f"\n🚀 TUDO PRONTO!")
            print(f"Uma pasta chamada 'Monitor_Logs_ATI' foi criada na sua Área de Trabalho.")
            print(f"Basta abrir essa pasta e dar 2 cliques no executável para rodar!")
            print(f"Caminho: {target_folder}")
        else:
            print("\nBuild concluído mas .exe não encontrado na pasta dist/")
    else:
        print(f"\nFalha no build (código: {result.returncode})")
        sys.exit(1)


if __name__ == "__main__":
    check_pyinstaller()
    build()