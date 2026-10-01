@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "APP_PYTHON=.venv\Scripts\python.exe"
if defined STELLALOG_SNS_PYTHON set "APP_PYTHON=%STELLALOG_SNS_PYTHON%"
if not exist "%APP_PYTHON%" goto setup_required
set "PYTHONPATH=%~dp0src"
set "PYTHONDONTWRITEBYTECODE=1"

"%APP_PYTHON%" -m stellalog_sns
if errorlevel 1 goto app_error
exit /b 0

:setup_required
echo ==============================================
echo StellaLog SNS Studioをまだ起動できません。
echo ==============================================
echo.
echo 先に setup.bat をダブルクリックして、初回セットアップを完了してください。
echo.
pause
exit /b 1

:app_error
echo.
echo ==============================================
echo アプリを起動できませんでした。
echo ==============================================
echo.
echo 上に表示されたエラー内容を確認してください。
echo 初回の場合は setup.bat を実行し直してください。
echo 記事データが見つからない場合は、同梱のsample_dataフォルダも確認してください。
echo.
pause
exit /b 1
