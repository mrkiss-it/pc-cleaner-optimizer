@echo off
chcp 65001 > nul
title Build PC Auto Cleaner Executable
cd /d "%~dp0"
echo ===================================================
echo     DONG GOI UNG DUNG THANH FILE .EXE DOC LAP
echo ===================================================
if exist "C:\Users\ASUS\AppData\Local\Programs\Python\Python310\python.exe" (
    "C:\Users\ASUS\AppData\Local\Programs\Python\Python310\python.exe" build_exe.py
) else (
    python build_exe.py
)
if %ERRORLEVEL% NEQ 0 (
    echo [LOI] Dong goi that bai! Ma loi: %ERRORLEVEL%
    pause
) else (
    echo.
    echo [THANH CONG] File exe da duoc tao tai: dist\PCAutoCleaner\PCAutoCleaner.exe
    pause
)
