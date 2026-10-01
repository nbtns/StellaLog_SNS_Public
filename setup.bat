@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================
echo StellaLog SNS Studio 初回セットアップ
echo ==============================================
echo.

set "PYTHON_COMMAND="
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_COMMAND=python"
)

if not defined PYTHON_COMMAND (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.11 -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PYTHON_COMMAND=py -3.11"
    )
)

if not defined PYTHON_COMMAND goto python_missing

%PYTHON_COMMAND% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto python_old

if not exist "requirements.txt" goto requirements_missing
if not exist "pyproject.toml" goto project_missing

if not exist ".venv\Scripts\python.exe" (
    echo 専用のPython環境を作成しています...
    %PYTHON_COMMAND% -m venv ".venv"
    if errorlevel 1 goto venv_error
) else (
    echo 既存の専用環境を使用します。
)

echo 必要な部品をインストールしています...
echo 初回は数分かかることがあります。
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto install_error

echo アプリ本体を専用環境へ登録しています...
".venv\Scripts\python.exe" -m pip install --no-deps -e .
if errorlevel 1 goto install_error

echo.
echo ==============================================
echo セットアップが完了しました。
echo start_StellaLog_SNS_Studio.bat をダブルクリックすると起動できます。
echo 初回セットアップ後の通常利用はオフラインで行えます。
echo ==============================================
echo.
pause
exit /b 0

:python_missing
echo.
echo [エラー] Pythonが見つかりません。
echo Python 3.11以上をインストールしてください。
echo インストール画面では「Add Python to PATH」にチェックを入れてください。
echo その後、この画面を閉じて setup.bat をもう一度実行してください。
goto failed

:python_old
echo.
echo [エラー] Python 3.11以上が必要です。
echo Python 3.11以上をインストールしてから setup.bat をやり直してください。
goto failed

:requirements_missing
echo.
echo [エラー] requirements.txt が見つかりません。
echo このファイルをプロジェクトのフォルダ内に戻してからやり直してください。
goto failed

:project_missing
echo.
echo [エラー] pyproject.toml が見つかりません。
echo setup.bat をStellaLog SNS Studioのフォルダ内で実行してください。
goto failed

:venv_error
echo.
echo [エラー] 専用のPython環境を作成できませんでした。
echo Pythonのインストール状態を確認してから、setup.bat をやり直してください。
goto failed

:install_error
echo.
echo [エラー] 必要な部品をインストールできませんでした。
echo インターネット接続を確認して、setup.bat をもう一度実行してください。
goto failed

:failed
echo.
echo 上の案内を確認してください。この画面はキーを押すまで閉じません。
pause
exit /b 1
