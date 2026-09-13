@echo off
REM Re-exports the 40BB turn, fixing the B33C gap and adding the 50%% and 75%%
REM flop-bet branches.
REM
REM Run peek first. It reads filenames only, so it takes seconds, and its
REM "pairs x lines" table says whether a line is missing for a pair or was
REM merely dropped by a filter - which is the difference between "re-export"
REM and "re-collect". Compare its "turn spots that exist" list against what
REM the CSVs come back with.
REM
REM The hands export is split three ways because one file for seven lines
REM would be about 60MB. Each part stands on its own and they concatenate.

python peek_cache.py turn_calib\cache > peek40.txt
type peek40.txt

set CACHE=turn_calib\cache
set LINES=XX,XC33,XC50,XC75,B33C,B50C,B75C
set NODES=turn_OOP,turn_IP

python export_freqs.py --cache %CACHE% --out turn40.csv.gz ^
  --lines %LINES% --nodes %NODES% --stack 40

python export_hands.py --cache %CACHE% --out turnhands40_a.csv.gz ^
  --lines XX,XC33,B33C --nodes %NODES% --stack 40

python export_hands.py --cache %CACHE% --out turnhands40_b.csv.gz ^
  --lines XC50,XC75 --nodes %NODES% --stack 40

python export_hands.py --cache %CACHE% --out turnhands40_c.csv.gz ^
  --lines B50C,B75C --nodes %NODES% --stack 40

echo.
echo Done. Send peek40.txt, turn40.csv.gz and the three turnhands40_*.csv.gz.
