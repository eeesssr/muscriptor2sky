@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0

title 转换 (自动定调)

set "IN=%~1"

if "!IN!"=="" (
    echo.
    echo   把 .mid 拖到本文件上即可转成光遇琴谱
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
echo   转换 (自动定调)
echo   正在转换: !IN!
echo.
echo   音区怎么处理？
echo     1 = 尽量贴近原曲音高（推荐，但可能需要换乐器调性）
echo     2 = 固定落在 C4~C6（用默认乐器直接能弹，音高会整体平移）
set /p "RG=请输入 1 或 2 [直接回车 = 1]: "
if "!RG!"=="" set "RG=1"
if "!RG!"=="1" set "REGARG=auto"
if "!RG!"=="2" set "REGARG=c"
if not defined REGARG set "REGARG=auto"
echo.

python -m muscriptor2sky "!IN!" --register !REGARG! --verify
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo   转换完成，已在同目录生成 .txt 琴谱
) else (
    echo   [失败] 退出码 %RC%，请检查上面的报错信息
)
echo.
pause
