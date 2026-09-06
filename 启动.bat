@echo off
chcp 65001 >nul
title lifehub 个人电脑中台 启动器
cd /d "%~dp0"
echo ==========================================
echo        lifehub 个人电脑中台 一键启动
echo ==========================================
echo.
echo 正在后台静默拉起机器人、定时任务与 API 服务...
wscript.exe "scripts\start_all.vbs"
timeout /t 2 >nul
powershell -ExecutionPolicy Bypass -File "scripts\status.ps1"
echo.
echo 启动完成，窗口将在 5 秒后自动关闭。
timeout /t 5
