@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0

title 转换 (定调输出版)

set "IN=%~1"

if "!IN!"=="" (
    echo.
    echo   把 .mid 拖到本文件上即可转成光遇琴谱，可指定定调（游戏内需花货币兑换）
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
echo   转换 (定调输出版)
echo   正在转换: !IN!
echo.

echo   定调 = 比 C 调高几个半音？
echo     0 = C 调（游戏默认）
echo     2 = D 调   7 = G 调   9 = A 调
set /p "PL=请输入 0-11 [直接回车 = 0]: "
if "!PL!"=="" set "PL=0"
echo.
python -m muscriptor2sky "!IN!" --pitch-level !PL! --verify
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo   转换完成，pitchLevel 已写入；游戏内需把乐器调到对应调才能对上
) else (
    echo   [失败] 退出码 %RC%，请检查上面的报错信息
)
echo.
pause