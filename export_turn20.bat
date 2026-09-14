@echo off
REM Exports whatever of the 20BB turn is on disk, for the same seven lines the
REM 40BB table uses.
REM
REM A line the cache does not hold is skipped silently rather than failing, so
REM this is safe to run before knowing whether tier 3 was ever collected at
REM this depth. run_chain.bat left it out - "2.4 days for the last 5.6% of turn
REM traffic" - so XC75 and B75C may well be absent, and the table will then
REM cover the five lines that are there. check_gaps.bat says which.
REM
REM B50C and B75C only exist for SB_vs_BB and UTG_vs_BTN, and that is correct
REM rather than a gap: a B line is OOP betting the flop, and those are the two
REM pairs whose OOP player is the preflop raiser. The other four reach the same
REM turn through XC33.
REM
REM The XX/XC33/B33C hands export from before is still good. Only the new lines
REM are exported here.

cd /d "%~dp0"

python peek_cache.py turn_calib_20_125bb\cache > peek20.txt
type peek20.txt

set CACHE=turn_calib_20_125bb\cache
set LINES=XX,XC33,XC50,XC75,B33C,B50C,B75C
set NODES=turn_OOP,turn_IP

python export_freqs.py --cache %CACHE% --out turn20.csv.gz ^
  --lines %LINES% --nodes %NODES% --stack 20

python export_hands.py --cache %CACHE% --out turnhands20_b.csv.gz ^
  --lines XC50,XC75 --nodes %NODES% --stack 20

python export_hands.py --cache %CACHE% --out turnhands20_c.csv.gz ^
  --lines B50C,B75C --nodes %NODES% --stack 20

echo.
echo Done. Send peek20.txt, turn20.csv.gz, turnhands20_b.csv.gz and
echo turnhands20_c.csv.gz.
