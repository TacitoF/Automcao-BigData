import sys
import os

if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from gui import MonitorApp

if __name__ == "__main__":
    app = MonitorApp()
    app.mainloop()