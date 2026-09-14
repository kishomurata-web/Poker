@echo off
REM What is actually on disk, before anything long is started.
REM
REM Every command here is a dry run: turn_calib.js's plan and defence-plan
REM modes read the cache and print what a real run would fetch, with no
REM network and no browser. Safe to run while a crawl is going.
REM
REM Writes gaps.txt. Send that file.

cd /d "%~dp0"
if exist gaps.txt del gaps.txt

echo ============ 40BB: the three pairs missing XC75 turn_IP ============ >> gaps.txt
node turn_calib.js plan --pairs=BTN_vs_BB,BTN_vs_SB,SB_vs_BB >> gaps.txt 2>&1

echo. >> gaps.txt
echo ============ 20BB: whole job ============ >> gaps.txt
node turn_calib.js plan --depth=20 >> gaps.txt 2>&1

echo. >> gaps.txt
echo ============ 20BB: the 50%% and 75%% lines ============ >> gaps.txt
node turn_calib.js defence-plan --depth=20 --lines=XC50,XC75,B50C,B75C >> gaps.txt 2>&1

echo. >> gaps.txt
echo ============ 20BB cache, by pair and line ============ >> gaps.txt
python peek_cache.py turn_calib_20_125bb\cache >> gaps.txt 2>&1

echo.
echo Done. Send gaps.txt.
type gaps.txt | more
