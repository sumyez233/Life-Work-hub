@echo off
rem 从脚本所在目录推导仓库根，克隆到任意目录均可直接运行
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m lifehub.cli bot
