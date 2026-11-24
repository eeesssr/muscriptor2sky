@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0

title 转换 (虚音版 实验性)

set "IN=%~1"

if "!IN!"=="" (
    echo.
    echo   用两键凑差音代替弹不出的黑键 —— 实验性，实际听感大概率更差，详见 docs/虚音说明.md
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
echo   转换 (虚音版 实验性)
echo   正在转换: !IN!
echo.

python -m muscriptor2sky "!IN!" --virtual-notes --verify
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo   转换完成（实验性）；建议戴耳机在安静环境试听，差音很可能听不见
) else (
    echo   [失败] 退出码 %RC%，请检查上面的报错信息
)
echo.
pause