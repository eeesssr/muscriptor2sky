@echo off
chcp 65001 >nul
setlocal

REM 兼容旧入口：v1.4.0 起输出模式拆成三个 .bat
REM   转换-C调默认.bat   pitchLevel = 0（游戏默认 C 调）  推荐
REM   转换-定调版.bat     指定 pitchLevel 0~11
REM   转换-虚音版.bat     用两键凑差音（实验性）
REM
REM 本文件保留为「C 调默认」的别名，旧快捷方式可继续用。

call "%~dp0转换-C调默认.bat" %*