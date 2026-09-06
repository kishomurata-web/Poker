# How the training site scores a decision

Notes from reading the site's own API responses. Everything here was checked
against real numbers rather than guessed at; the arithmetic that confirms each
claim is kept alongside it, so a future disagreement can be settled by rerunning
the same subtraction.

The numbers came from the `hero-situation` response, read in Chrome's Network
panel (Preview tab). Nothing was decompiled - the server hands over its own
scores, and the only thing that had to be worked out was how they are derived.

## The two percentages on screen are not the same quantity

The site shows a percentage next to each action, and one more at the end of the
session. They are computed completely differently, and conflating them was the
first wrong turn.

**Per-action %** is the GTO frequency, not a score:

| shown | `frequency` |
| --- | --- |
| 100% | 1 |
| 27.8% | 0.278000026941 |
| 1% | 0.0100000007078 |
| 100% | 1 |
| 83.9% | 0.838550329208 |
| 0% | 0 |

**Session %** is the mean of `gto_score` over the actions the player chose:

```
 1 + 0.3866481375534103 + 0 + 1 + 1 - 0.7428011174682247
 = 2.6438470200851856
 / 6 = 0.4406411700141976   -> shown as 44%
```

## `gto_score`

Range is -1 to +1. One decision earns one score; the session is their average.

```
pot     = game.pot                      (start_pot + the bet being faced)
maxFreq = max(frequency) over solutions
maxEv   = max(ev) over solutions

in the solver's strategy (frequency >= FREQ_MIN):
    frequency == maxFreq        ->  1                      BEST_MOVE
    frequency >= MIX_MIN        ->  frequency / maxFreq    CORRECT_MOVE
    otherwise                   ->  0                      INACCURACY

not in the strategy:
    ev_loss   = maxEv - ev
    gto_score = max(-1, -20 * ev_loss / pot)               WRONG_MOVE / BLUNDER
```

Losing 5% of the pot in EV is worth -1, and nothing below that costs more.

### `BEST_MOVE` is the most frequent action, not the highest-EV one

These come apart, so the distinction is not academic:

```
R5.05 : ev 5.67534505  <- the highest EV at the node, but CORRECT_MOVE (0.6263)
R3.35 : ev 5.67364595     lower EV, but frequency 0.388 is the highest -> 1
```

`ev_loss` is measured from the highest EV; the label is decided by frequency.

### EV is ignored for anything inside the strategy

At the same node, `R12.2` is played 0.1% of the time and gives up 9% of the pot
in EV. It is still `INACCURACY` with `gto_score` 0, and its reported `ev_loss` is
0 rather than the real difference. `ev_loss` is only filled in for actions the
solver never plays.

## Confirmed by arithmetic

`ev_loss / ev_loss_as_pot` recovers the pot exactly at every node seen so far
(13.5, 8.1, 16.2, 6.1), and `-20 * ev_loss_as_pot` reproduces every `gto_score`
that belongs to a mistake:

| `ev_loss_as_pot` | `gto_score` | label |
| --- | --- | --- |
| 0.00841239506172849 | -0.16824790123456979 | WRONG_MOVE |
| 0.015446274691358113 | -0.3089254938271622 | WRONG_MOVE |
| 0.023100771604938366 | -0.4620154320987673 | WRONG_MOVE |
| 0.027935169361400370 | -0.5587033872280074 | WRONG_MOVE |
| 0.031698157407407520 | -0.6339631481481504 | WRONG_MOVE |
| 0.037140055873411240 | -0.7428011174682247 | WRONG_MOVE |
| 0.046346311176215190 | -0.9269262235243038 | BLUNDER |
| 0.070080604938271670 | -1 (from -1.4016) | BLUNDER |
| 0.219571615573770470 | -1 (from -4.3914) | BLUNDER |

The ratio rule is exact too:

```
0.278000026941 / 0.719000041485 = 0.3866481375534103
0.320000022650 / 0.388000011444 = 0.8247423020918792
0.243000015616 / 0.388000011444 = 0.6262886815689493
```

And `hand_info.ev` is the strategy-weighted EV of the hand at that node -
`sum(frequency * ev)` came to -0.0027469, against a reported -0.0027469635.

## Thresholds

`WRONG_MOVE` and `BLUNDER` are the same formula under two names. The boundary
sits between the -0.7428 seen on a `WRONG_MOVE` and the -0.9269 seen on a
`BLUNDER`, so **-0.8, or 4% of the pot**, is where it lands.

`FREQ_MIN`, below which an action counts as a mistake:

```
0.000144915189594  -> WRONG_MOVE   (a mistake)
0.001              -> INACCURACY   (inside the strategy)
```

So it is at most 0.001. The site prints frequencies to one decimal place as a
percentage, which makes **0.1% - anything that rounds to 0.0% on screen** the
natural reading.

`MIX_MIN`, above which a mixed action scores its share instead of zero, is the
one number still open:

| | frequency | ratio to `maxFreq` |
| --- | --- | --- |
| highest `INACCURACY` seen | 0.023 | 0.0593 |
| lowest `CORRECT_MOVE` seen | 0.243 | 0.3866 |

A single action played between 3% and 24% of the time will settle it, and will
also say whether the cut is on the raw frequency or on the ratio.
