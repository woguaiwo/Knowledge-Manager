Set WshShell = WScript.CreateObject("WScript.Shell")
strDesktop = WshShell.SpecialFolders("Desktop")
Set oLink = WshShell.CreateShortcut(strDesktop & "\Knowledge Manager.lnk")
oLink.TargetPath = "D:\Softwares\Knowledge-Manager\dist\KnowledgeManager\KnowledgeManager.exe"
oLink.WorkingDirectory = "D:\Softwares\Knowledge-Manager\dist\KnowledgeManager"
oLink.IconLocation = "D:\Softwares\Knowledge-Manager\icon.ico,0"
oLink.Description = "Knowledge Manager"
oLink.Save
WScript.Echo "Done"
