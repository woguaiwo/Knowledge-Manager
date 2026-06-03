@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo =========================================
echo  Knowledge Manager Build Script
echo =========================================

set DIST_DIR=dist\KnowledgeManager
set BACKUP_DIR=%TEMP%\km_build_backup_%RANDOM%

:: 1. Backup existing user data if present
set NEED_RESTORE=0
if exist "%DIST_DIR%\data.db" (
    echo [Backup] Found existing data.db
    mkdir "%BACKUP_DIR%" 2>nul
    copy "%DIST_DIR%\data.db" "%BACKUP_DIR%\data.db" >nul
    set NEED_RESTORE=1
)
if exist "%DIST_DIR%\vocab" (
    echo [Backup] Found existing vocab/ directory
    mkdir "%BACKUP_DIR%\vocab" 2>nul
    xcopy /E /I /Y "%DIST_DIR%\vocab" "%BACKUP_DIR%\vocab" >nul
    set NEED_RESTORE=1
)

:: 2. Kill running process to unlock _internal
 taskkill /F /IM KnowledgeManager.exe >nul 2>&1

:: 3. Run PyInstaller
venv\Scripts\python -m PyInstaller -y KnowledgeManager.spec
if errorlevel 1 (
    echo [Error] PyInstaller build failed!
    goto cleanup
)

:: 4. Restore user data
echo [Build] Success. Restoring user data...
if exist "%BACKUP_DIR%\data.db" (
    copy "%BACKUP_DIR%\data.db" "%DIST_DIR%\data.db" >nul
    echo [Restore] data.db restored
)
if exist "%BACKUP_DIR%\vocab" (
    xcopy /E /I /Y "%BACKUP_DIR%\vocab" "%DIST_DIR%\vocab" >nul
    echo [Restore] vocab/ restored
)

echo =========================================
echo  Build Complete: %DIST_DIR%
echo =========================================

:cleanup
if exist "%BACKUP_DIR%" rmdir /S /Q "%BACKUP_DIR%"
endlocal
