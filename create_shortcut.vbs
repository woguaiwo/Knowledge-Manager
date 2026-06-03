' Create a desktop shortcut for Richie's Learning System
Set WshShell = CreateObject("WScript.Shell")
desktop = WshShell.SpecialFolders("Desktop")

currentDir = WshShell.CurrentDirectory
exePath = currentDir & "\venv\Scripts\pythonw.exe"
scriptPath = currentDir & "\main.py"

Set shortcut = WshShell.CreateShortcut(desktop & "\Richie's Learning System.lnk")
shortcut.TargetPath = exePath
shortcut.Arguments = """" & scriptPath & """"
shortcut.WorkingDirectory = currentDir
shortcut.Description = "Richie's Learning System"
shortcut.IconLocation = exePath & ",0"
shortcut.Save

MsgBox "Shortcut 'Richie's Learning System' has been created on your Desktop!" & vbCrLf & vbCrLf & _
       "You can now double-click the shortcut to launch without any terminal window.", _
       64, "Shortcut Created"

Set shortcut = Nothing
Set WshShell = Nothing
