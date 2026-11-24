@echo off
chcp 65001 >nul
setlocal

REM 主入口：v1.5.0 起默认改为「自动定调」，保住原曲音高。
REM
REM   转换-自动定调.bat   自动识别原曲大调（默认，推荐）
REM   转换-手动定调.bat   手动指定 0-11（备用）
REM   转换-虚音版.bat     用两键凑差音（实验性）
REM
REM 本文件保留为「自动定调」的别名，旧快捷方式可继续用。

call "%~dp0转换-自动定调.bat" %*
