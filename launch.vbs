' Richie's Learning System - Silent Launcher
' Double-click this file to run without any terminal window.
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """venv\Scripts\pythonw.exe"" ""main.py""", 0, False
Set WshShell = Nothing
