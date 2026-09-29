import multiprocessing

from scalperlab.desktop import run_desktop


if __name__ == "__main__":
    # Required by PyInstaller so spawned MT5 connector workers do not relaunch
    # the desktop entry point as a second application instance.
    multiprocessing.freeze_support()
    run_desktop()
