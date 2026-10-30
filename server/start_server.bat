@echo off
chcp 936 >nul
cd /d "%~dp0"

rem 免得系统里的 PYTHONIOENCODING / PYTHONUTF8 把中文输出搞成乱码
set "PYTHONIOENCODING="
set "PYTHONUTF8="

rem ============================================================
rem  天马麻将 · 联机服务端（双击运行；关掉窗口 = 停服）
rem ============================================================

set "PYRUN="
where py >nul 2>nul
if not errorlevel 1 set "PYRUN=py -3"
where python >nul 2>nul
if not errorlevel 1 set "PYRUN=python"
if not defined PYRUN goto nopython

echo 正在启动联机服务端（端口 8000）...
echo 关掉这个窗口 = 服务端停止，朋友会掉线
echo.

%PYRUN% net_server.py --host 0.0.0.0 --port 8000 %*
set "CODE=%errorlevel%"

echo.
echo 服务端已退出（返回码 %CODE%）。窗口留着方便你看报错。
pause
exit /b %CODE%

:nopython
echo [错误] 找不到 python。请安装 Python 3.10+ 并勾选 "Add python.exe to PATH"。
echo        下载地址：https://www.python.org/downloads/
pause
exit /b 1
