@echo off
if "%1"=="h" goto start
mshta vbscript:createobject("wscript.shell").run("""%~nx0"" h",0)(window.close) && exit
:start
"venv\Scripts\pythonw.exe" "main.py"
