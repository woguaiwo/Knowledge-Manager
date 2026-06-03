' Create a desktop shortcut for Knowledge Manager (dev/source version)
Set WshShell = CreateObject("WScript.Shell")
desktop = WshShell.SpecialFolders("Desktop")

currentDir = WshShell.CurrentDirectory
exePath = currentDir & "\venv\Scripts\pythonw.exe"
scriptPath = currentDir & "\main.py"

Set shortcut = WshShell.CreateShortcut(desktop & "\Knowledge Manager (Dev).lnk")
shortcut.TargetPath = exePath
shortcut.Arguments = """" & scriptPath & """"
shortcut.WorkingDirectory = currentDir
shortcut.Description = "Knowledge Manager (Dev)"
shortcut.IconLocation = currentDir & "\icon.ico,0"
shortcut.Save

MsgBox "Shortcut 'Knowledge Manager (Dev)' has been created on your Desktop!" & vbCrLf & vbCrLf & _
       "You can now double-click the shortcut to launch without any terminal window.", _
       64, "Shortcut Created"

Set shortcut = Nothing
Set WshShell = Nothing
