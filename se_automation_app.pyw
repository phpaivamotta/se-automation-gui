"""Starts the SE Automation window (double-click, or run via "SE Automation.bat")."""

try:
    from se_automation.gui.app import main
except Exception:   # pythonw has no console, so show start-up problems in a message box
    import ctypes
    import traceback
    ctypes.windll.user32.MessageBoxW(None, traceback.format_exc(), "SE Automation could not start", 0x10)
    raise SystemExit(1)

main()
