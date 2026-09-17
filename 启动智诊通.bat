@echo off
chcp 65001 >nul 2>&1
title 智诊通 · AI智能问诊 - 本地服务
cd /d "%~dp0"

echo.
echo ============================================================
echo    智诊通 · AI智能问诊 - 正在启动本地服务...
echo ============================================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Python，请先安装 Python 3.8+
    echo    下载地址：https://www.python.org/downloads/
    echo    安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

python start_server.py

echo.
echo 服务已停止，按任意键关闭窗口...
pause >nul
