@echo off
REM Fills the eight (pair, flop) groups missing from XC75 turn_IP at 40BB, then
REM re-exports the turn.
REM
REM   BTN_vs_BB   7s7h6s  As6s6h  JsJh9s  KsKh7s  KsTsTh
REM   BTN_vs_SB   6s4s3s
REM   SB_vs_BB    6s4s3s  AsAh7s
REM
REM These are not unreachable nodes - OOP checks the turn 37-65% of the time on
REM every one of them, against 38-99% everywhere else - so the data should be
REM there and is not.
REM
REM turn_calib.js is resumable and skips what is cached and validated, so this
REM re-runs the whole night job for the three pairs and only the missing groups
REM cost anything. Run check_gaps.bat first: its plan output says how many
REM requests that actually is before this spends them.
REM
REM Chrome must be running with --remote-debugging-port=9222 and logged into
REM app.gtowizard.com (open_chrome_debug.bat). Leave one tab open.
REM To stop: stop_night.bat

cd /d "%~dp0"
setlocal
set CONCURRENCY=5
set PACING_MS=300

node turn_calib.js night --pairs=BTN_vs_BB,BTN_vs_SB,SB_vs_BB
if errorlevel 1 (
  echo.
  echo Collection stopped with an error. Re-run this file - it resumes.
  exit /b 1
)

echo.
echo ============ re-exporting the 40BB turn ============
set CACHE=turn_calib\cache
set LINES=XX,XC33,XC50,XC75,B33C,B50C,B75C
set NODES=turn_OOP,turn_IP

python export_freqs.py --cache %CACHE% --out turn40.csv.gz ^
  --lines %LINES% --nodes %NODES% --stack 40

python export_hands.py --cache %CACHE% --out turnhands40_b.csv.gz ^
  --lines XC50,XC75 --nodes %NODES% --stack 40

echo.
echo Done. Send turn40.csv.gz and turnhands40_b.csv.gz.
echo The a and c parts are unchanged - no need to redo them.
