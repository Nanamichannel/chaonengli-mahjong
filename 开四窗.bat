@echo off
chcp 65001 >nul
rem ============================================================
rem  一次开 4 个客户端窗口（各坐一家），用来自己扮演四家测试
rem ------------------------------------------------------------
rem  ★ 跑之前：Godot 编辑器里把 main.gd / server_bridge.gd 关掉重开（Reload from disk），
rem    不然起的是编辑器里那份旧脚本；旧窗口也全部关掉，别和新的抢座位。
rem  · 第 1 个窗口自动坐 0 号位（屏幕下方）并开一局；
rem    后面 3 个自动接上同一局，分别坐 1/2/3 号位（右/上/左）。
rem  · 想换座位：在那个窗口按 1 / 2 / 3 / 4。
rem  · 想重开一局：在任意窗口按 F2。
rem  · 只开 1 个窗口也可以：直接关掉这个 bat 开的窗口，在编辑器里按 F5，
rem    没被窗口认领的座位仍然由服务端代打（AI）。
rem  · 每个窗口自己一对「请求/响应文件」（带进程号），四个窗口不会互相抢。
rem ============================================================
set GODOT="N:\apps\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64.exe"
set PROJ="N:\apps\tianma"

if not exist %GODOT% (
  echo 找不到 Godot：%GODOT%
  echo 请把这一行改成你机器上 Godot 的实际路径。
  pause
  exit /b 1
)

start "" %GODOT% --path %PROJ%
timeout /t 2 /nobreak >nul
start "" %GODOT% --path %PROJ%
timeout /t 2 /nobreak >nul
start "" %GODOT% --path %PROJ%
timeout /t 2 /nobreak >nul
start "" %GODOT% --path %PROJ%

echo 4 个窗口已打开（左上角会写「本窗口 = X 号位 … 第 N 局」）。
echo 四个窗口的「第 N 局」应该一样；不一样就是没接上同一局，重开那个窗口。
