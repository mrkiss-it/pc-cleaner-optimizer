@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

:: 1. Uu tien khoi chay file EXE doc lap khong console neu da build
if exist "dist\PCAutoCleaner\PCAutoCleaner.exe" (
    start "" "dist\PCAutoCleaner\PCAutoCleaner.exe" %*
    exit /b 0
)

:: 2. Khoi chay bang pythonw.exe (trinh thong dich Python khong hien thi cua so CMD)
if exist "C:\Users\ASUS\AppData\Local\Programs\Python\Python310\pythonw.exe" (
    start "" "C:\Users\ASUS\AppData\Local\Programs\Python\Python310\pythonw.exe" main.py %*
    exit /b 0
)

:: 3. Du phong chay qua VBScript an hoan toan
if exist "start_silent.vbs" (
    wscript.exe "start_silent.vbs"
    exit /b 0
)

:: 4. Fallback pythonw trong PATH
start "" pythonw main.py %*
exit /b 0
