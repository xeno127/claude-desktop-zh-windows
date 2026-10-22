@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if defined CLAUDE_ZH_PYTHON goto custom_python
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto py_launcher
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto python_path
echo 未找到 Python 3.10 或更新版本。
echo 请安装 Python 并勾选 Add Python to PATH，再重新运行本文件。
echo 也可以设置环境变量 CLAUDE_ZH_PYTHON 为 python.exe 的完整路径。
set "setup_exit=1"
goto finish
:custom_python
"%CLAUDE_ZH_PYTHON%" -X utf8 "%~dp0setup.py" %*
goto result
:py_launcher
py -3 -X utf8 "%~dp0setup.py" %*
goto result
:python_path
python -X utf8 "%~dp0setup.py" %*
:result
set "setup_exit=%errorlevel%"
:finish
if not "%setup_exit%"=="0" echo 安装或检查未成功，请保留错误信息并查看中文文档。
if not defined CLAUDE_ZH_NO_PAUSE pause
exit /b %setup_exit%
