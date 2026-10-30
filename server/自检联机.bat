@echo off
chcp 936 >nul
title 超能力麻将 · 联机自检
echo ==========================================
echo    超能力麻将  联机自检
echo ==========================================
echo.

echo [1/4] Tailscale 服务（要有 RUNNING）
sc query Tailscale | findstr /i "STATE"
echo.

echo [2/4] Funnel 公网通道（要显示 Funnel on）
"C:\Program Files\Tailscale\tailscale.exe" funnel status
echo.

echo [3/4] 服务端端口 8000
netstat -ano | findstr ":8000" | findstr LISTEN
if errorlevel 1 (
  echo    [X] 8000 没在监听 —— 服务端没起来
  echo        解决：双击 server\start_server.bat
) else (
  echo    [OK] 端口在监听
)
echo.

echo [4/4] 公网连通性（要 HTTP 200）
curl -s -m 12 -o nul -w "    HTTP %%{http_code}\n" https://desktop-an1ub6a.tail7ef5a6.ts.net/health
if errorlevel 1 echo    [X] 连不上，检查第 2 步的 Funnel 状态
echo.

echo ==========================================
echo  四项都正常 = 可以叫人开打了
echo ==========================================
pause >nul
