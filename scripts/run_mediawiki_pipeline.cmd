@echo off
setlocal

for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

if not exist "logs" mkdir "logs"
if errorlevel 1 exit /b %ERRORLEVEL%

set "LOG_FILE=logs\mediawiki_pipeline.log"
>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo ===== %date% %time% MediaWiki pipeline =====

set "SPARK_JOB_SCRIPT=/opt/project/src/run_mediawiki_pipeline.py"
docker compose --env-file .env -f infra\docker-compose.yml --profile spark run --rm spark >>"%LOG_FILE%" 2>&1
set "PIPELINE_EXIT_CODE=%ERRORLEVEL%"

>>"%LOG_FILE%" echo ===== finished %date% %time% exit_code=%PIPELINE_EXIT_CODE% =====
exit /b %PIPELINE_EXIT_CODE%
