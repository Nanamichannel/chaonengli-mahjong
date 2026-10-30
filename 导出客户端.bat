@echo off
chcp 936 >nul
cd /d "%~dp0"
title 导出客户端
set "GODOT=N:\apps\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64.exe"

echo ==========================================
echo   导出「超能力麻将」客户端（单文件 exe）
echo ==========================================
echo.
echo  会把 build\Tianma.exe 覆盖成最新代码。
echo  联网是编在工程里的（server_net.gd 的 DEFAULT_URL），
echo  导出设置里 embed_pck=true，所以产物只有一个 exe。
echo.
echo  注意：Godot 编辑器如果正开着这个项目，建议先关掉。
echo.
pause

if not exist "%GODOT%" (
  echo [X] 找不到 Godot：%GODOT%
  pause
  exit /b 1
)

if exist build\Tianma.exe del /q build\Tianma.exe

echo.
echo 正在导出，大约 1 分钟...
echo.
"%GODOT%" --headless --path "%~dp0." --export-release "天才麻将少女！" build\Tianma.exe

echo.
if exist build\Tianma.exe (
  echo [OK] 导出完成
  for %%F in (build\Tianma.exe) do echo      build\Tianma.exe  %%~zF 字节  %%~tF
  echo.
  echo 下一步：双击 build\Tianma.exe 自己试一下，能进游戏就说明没问题。
  echo 想发给朋友：让 AI 传到 GitHub Release，或自己上传。
) else (
  echo [X] 导出失败，看上面的报错信息
)
echo.
pause
