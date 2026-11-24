@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0

title 转换 (C调 默认)

set "IN=%~1"

if "!IN!"=="" (
    echo.
    echo   把 .mid 拖到本文件上即可转成光遇琴谱（C 调，游戏默认，不用花货币）
    echo.
    set /p "IN=请输入 MIDI 文件路径: "
)

if not exist "!IN!" (
    echo.
    echo   [错误] 找不到文件: !IN!
    echo.
    pause
    exit /b 1
)

echo.
echo   转换 (C调 默认)
echo   正在转换: !IN!
echo.

python -m muscriptor2sky "!IN!" --verify
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo   转换完成，已在同目录生成 .txt 琴谱（pitchLevel = 0）
) else (
    echo   [失败] 退出码 %RC%，请检查上面的报错信息
)
echo.
pause