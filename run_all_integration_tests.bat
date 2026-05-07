@echo off
REM Batch script to run all integration tests for AI Architect Cloud Studio
REM Runs render flow and regional edit flow scripts sequentially

setlocal
set PYTHON=python

REM Optionally set environment variables here
REM set SUPABASE_URL=https://your-supabase-url.supabase.co
REM set SUPABASE_ANON_KEY=your-anon-key
REM set SUPABASE_USER_ID=your-user-id
REM set TARGET_IMAGE_URL=https://your-image-url.png

cd /d %~dp0

%PYTHON% scripts\integration_test_render_flow.py
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] Render flow integration test failed.
    exit /b 1
)

%PYTHON% scripts\integration_test_regional_edit.py
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] Regional edit integration test failed.
    exit /b 1
)

echo [OK] All integration tests completed successfully.
exit /b 0
