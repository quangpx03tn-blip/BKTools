@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   BK Tools — Commit & Push len GitHub
echo   (Railway se tu dong cap nhat web)
echo ========================================
echo.

set /p MSG="Noi dung update (vd: sua thumbnail): "
if "%MSG%"=="" set MSG=update

git add -A
git status
echo.
git commit -m "%MSG%"
if errorlevel 1 (
  echo.
  echo Khong co thay doi de commit, hoac chua cai Git.
  pause
  exit /b 1
)

git push
echo.
echo Done. Vao Railway xem Deployments sau 1-2 phut.
pause
