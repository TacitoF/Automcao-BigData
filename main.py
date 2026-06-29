import sys
import os

if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(sys.executable)
    os.chdir(_exe_dir)
    if _exe_dir not in sys.path:
        sys.path.insert(0, _exe_dir)

from gui import MonitorApp

if __name__ == "__main__":
    app = MonitorApp()
    app.mainloop()