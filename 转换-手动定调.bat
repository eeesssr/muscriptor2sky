@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0

title 转换 (手动定调 备用)

set "IN=%~1"

if "!IN!"=="" (
    echo.
    echo   把 .mid 拖到本文件上即可转成光遇琴谱，手动指定调
    echo   备用路径：自动识别不准，或你只有某个调的乐器时才用
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
echo   转换 (手动定调)
echo   正在转换: !IN!
echo.
echo   要把谱面写成哪个调？
echo     0 = C 调（游戏默认，不需要换乐器）
echo     2 = D 调    5 = F 调    7 = G 调    9 = A 调
echo     输入 auto 也可以，等于交给自动识别
set /p "PL=请输入 0-11 或 auto [直接回车 = 0]: "
if "!PL!"=="" set "PL=0"
echo.
python -m muscriptor2sky "!IN!" --key !PL! --verify
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo   转换完成，pitchLevel 已写入
) else (
    echo   [失败] 退出码 %RC%，请检查上面的报错信息
)
echo.
pause
