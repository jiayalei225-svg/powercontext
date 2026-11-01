@echo off
rem Start the project-owned PowerContext instance on 8010.
rem It asks StudyCoach for embeddings through POST /v1/embeddings, so memory
rem search and document search share one local BGE model and no external key.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\powercontext.exe" (
  echo PowerContext is not installed yet. Run scripts\start_windows.bat first.
  exit /b 1
)

if not defined APP_PORT set "APP_PORT=8090"
if not defined EMBEDDING_MODEL set "EMBEDDING_MODEL=bge-small-zh-v1.5"
if not defined EMBEDDING_DIM set "EMBEDDING_DIM=512"
if not defined POWERCONTEXT_PORT set "POWERCONTEXT_PORT=8010"
if not defined POWERCONTEXT_EMBEDDING_BASE_URL set "POWERCONTEXT_EMBEDDING_BASE_URL=http://127.0.0.1:%APP_PORT%/v1"

if not defined POWERCONTEXT_HOME set "POWERCONTEXT_HOME=%CD%\data\powercontext"
if not exist "%POWERCONTEXT_HOME%" mkdir "%POWERCONTEXT_HOME%"

set "POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1"
set "POWERCONTEXT_SERVER_HTTP_PORT=%POWERCONTEXT_PORT%"
set "POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_MODEL=openai:%EMBEDDING_MODEL%"
set "POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_BASE_URL=%POWERCONTEXT_EMBEDDING_BASE_URL%"
set "POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_PROFILE_ID=%EMBEDDING_MODEL%"
set "POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_DIMENSION=%EMBEDDING_DIM%"

echo PowerContext starting on http://127.0.0.1:%POWERCONTEXT_PORT%
echo Embedding provider: %POWERCONTEXT_EMBEDDING_BASE_URL%
".venv\Scripts\powercontext.exe" server run --no-env-file
