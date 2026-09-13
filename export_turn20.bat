@echo off
REM The same for 20BB. Run it after the 40BB one has come back clean, so a
REM wrong filter is found once rather than twice.
REM
REM 20BB already has B33C for all six pairs, so only the 50%% and 75%%
REM branches are new here - but the frequency export is re-run whole because
REM one file has to carry every line the table names.

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
echo Done. Send peek20.txt, turn20.csv.gz, turnhands20_b.csv.gz and turnhands20_c.csv.gz.
echo The XX/XC33/B33C hands export from before is still good - no need to redo it.
