"""Writes the simplified 40BB SRP strategy table from an exported frequency cache.

    python build.py --flop flop40.csv.gz --turn turn40.csv.gz --out 40BB_SRP_v2.txt

The two CSVs come from export_freqs.py, which reduces the solver cache to one
reach-weighted frequency per action. Flop rows cover all 1755 canonical boards
and are weighted by how often each actually comes down; turn rows cover the 49
sampled flops and carry equal weight, which is why the two sections count in
different denominators.

Each spot gets its own rule tree rather than one shared board classification.
A shared reading was measured against this and cost about half the resolution
at the same number of classes, because what separates two boards in one spot
often does not separate them in another.
"""
import argparse, collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gto, preds, turnpred, tree, turntree, round10, pattern

SEAT = {'UTG_vs_BB': ('utg', 'bb'), 'UTG_vs_SB': ('utg', 'sb'), 'UTG_vs_BTN': ('btn', 'utg'),
        'BTN_vs_BB': ('btn', 'bb'), 'BTN_vs_SB': ('btn', 'sb'), 'SB_vs_BB': ('bb', 'sb')}
PAIRNAME = {'UTG_vs_BB': 'utg vs bb', 'UTG_vs_SB': 'utg vs sb', 'UTG_vs_BTN': 'utg vs btn',
            'BTN_vs_BB': 'btn vs bb', 'BTN_vs_SB': 'btn vs sb', 'SB_vs_BB': 'sb vs bb'}
FLOPNAME = {
 ('UTG_vs_BB', 'flop_IP'): 'utg vs bb utg c-bet',  ('UTG_vs_BB', 'flop_OOP'): 'utg vs bb bb donk bet',
 ('UTG_vs_BTN', 'flop_OOP'): 'utg vs btn utg c-bet', ('UTG_vs_BTN', 'flop_IP'): 'utg vs btn btn BMCB',
 ('UTG_vs_SB', 'flop_IP'): 'utg vs sb utg c-bet',  ('UTG_vs_SB', 'flop_OOP'): 'utg vs sb sb donk bet',
 ('BTN_vs_BB', 'flop_IP'): 'btn vs bb btn c-bet',  ('BTN_vs_BB', 'flop_OOP'): 'btn vs bb bb donk bet',
 ('BTN_vs_SB', 'flop_IP'): 'btn vs sb btn c-bet',  ('BTN_vs_SB', 'flop_OOP'): 'btn vs sb sb donk bet',
 ('SB_vs_BB', 'flop_OOP'): 'sb vs bb sb c-bet',    ('SB_vs_BB', 'flop_IP'): 'sb vs bb bb BMCB'}
FORDER = ['utg vs bb utg c-bet', 'utg vs bb bb donk bet', 'utg vs btn utg c-bet',
          'utg vs btn btn BMCB', 'utg vs sb utg c-bet', 'utg vs sb sb donk bet',
          'btn vs bb btn c-bet', 'btn vs bb bb donk bet', 'btn vs sb btn c-bet',
          'btn vs sb sb donk bet', 'sb vs bb sb c-bet', 'sb vs bb bb BMCB']
PRE = {'XX': 'x-x-', 'XC33': 'x-~33-c-', 'B33C': '~33-c-'}

def turnname(pair, line, node):
    ip, oop = SEAT[pair]
    return f"{PAIRNAME[pair]} {PRE[line]}{'x-' + ip if node == 'turn_IP' else oop}アクション"

def error(leaves):
    """How far one board sits from the line it is filed under, in points:
    over the whole mix, and over the bet-or-not decision alone.

    Measured against the line as printed - rounded to tens - so the figure in
    the appendix is the error a reader of the table actually carries, not the
    error before rounding."""
    num = bet = den = 0.0
    for rs, _ in leaves:
        v = [x / 100.0 for x in round10.round_leaf(rs)]
        for f, d in rs:
            b = round10.line5({t: d.get(t, 0.0) for t in gto.TIERS})
            num += f.w * sum(abs(x - y) for x, y in zip(v, b)) / 2
            bet += f.w * abs((1 - b[0]) - (1 - v[0]))
            den += f.w
    return num / den * 100, bet / den * 100

def shapes(leaves, key, H, t, min_share=0.10):
    """For each rule: the shape its boards share, and the boards that break it.

    The rule's own shape is read off its boards merged, which is the same
    weighting its printed frequencies use, so the label and the numbers on a
    line are describing the same thing.
    """
    out = {}
    for rs, path in leaves:
        per = [(f.w, f.board, H[(key[0], key[1], key[2], f.board)])
               for f, _ in rs if (key[0], key[1], key[2], f.board) in H]
        if not per: continue
        bd = pattern.bands(pattern.merge([(w, c) for w, _, c in per]))
        if bd is None: continue
        pat = pattern.classify(bd, t)
        tw = sum(w for w, _, _ in per)
        odd = collections.defaultdict(lambda: [0.0, []])
        for w, b, counts in per:
            b2 = pattern.bands(counts)
            if b2 is None: continue
            p2 = pattern.classify(b2, t)
            if p2 == pat: continue
            e = odd[p2]; e[0] += w; e[1].append((w, b))
        ex = []
        for p2, (w, bs) in sorted(odd.items(), key=lambda x: -x[1][0]):
            if w / tw < min_share: continue
            bs.sort(reverse=True)
            ex.append((p2, w, [b for _, b in bs[:5]]))
        out[tree.label(path)] = (pat, pattern.describe(bd), ex)
    return out


HEAD = """40BB SRP 簡易GTO戦略 v2（1755フロップ全数版）

■ ベットサイズの段階
（）内は（check, ~33%, 50%, 75%, 125%~）の5枠。実サイズは以下の段階に丸める。

  段階        ポットに対する割合    含まれる実サイズ
  check       -                     チェック
  ~33%        10〜35%               10, 12, 15, 20, 25, 33%
  50%         36〜60%               40, 50, 55%
  75%         61〜110%              75, 83, 100%        ← 100%はここ
  125%~       111%以上              125, 150, 200%, オールイン

サイトのメニューは2系統ある。SB vs BB のみ 12/25/50/75/100/150(/200)%、
他の5ペアは 20/33/55/83/125(/200)%。上の段階はどちらも同じ5枠に落ちる。
フロップでは125%~の枠は全スポットで0%（40BBではフロップのオーバーベットが存在しない）。
ターンでは200%とオールインが最大3.7%現れ、125%~の枠に含めている。

■ [N] の意味
フロップ：22,100通りの実フロップのうち何通りか（1755クラスを出現確率で重み付け、合計22,100）。
ターン：49フロップ×49ターンカード=2,401通りのうち何通りか（現行版と同じ）。

■ ハンドランクとベット頻度
フロップの各ルールには、そのクラスのベットの形を付記している。レンジをメイド強度順に
並べ、上から5% / 5-15% / 15-40% / 40-100% の4区間それぞれのベット率が [ナッツ/強/中/弱]。

  レンジベット  どの強さでも同じくらい打つ。ハンドランクがサイズを決めない。
  デポラー      最上位がチェックに回り、一段下から打つ。
  ポラー        強い側と弱い側が打ち、中途半端な強さがチェックする。
  標準          強いほど打つ。

クラス内でこの形が食い違うボードは、そのルールの下に「例外」として並べてある。
4区間の切り方も、形を分ける閾値も、分布に自然な切れ目が無いため判断で置いた値である。

■ 用語
HMSD/MLSD  ハイとミドル（ミドルとロー）が5枚幅の窓に同居する＝そこにストレートドローがありうる。
           Aは A-K-Q-J-T と A-2-3-4-5 の両方で数える。
HM,MLSD    両方に存在。HM,MLnSD はそれ以外。
ストレート完成  ペアなしで3枚が5枚幅の窓に収まる。
ホイールボード  A,2,3,4,5 を2枚以上含み、A以外は9以下。
hi-mid差 / mid-lo差  ランクの差（K,9,4 なら 4 と 5）。
T以上が N枚  ボードのT,J,Q,K,Aの枚数。
BMCB       OOPのチェック後にIPが行うBet。


=========================  フロップ  =========================
"""

TURNHEAD = """
=========================  ターン  =========================

■ 注意
x-~33-c のあとにOOPが先に打つノードだけ、サイトのメニューが check / 20% / 50%
（sb vs bb は check / 15% / 40%）の3つしかない。該当スポットでは 75% と 125%~ の枠が
構造上ゼロになる。データがないのではなく、その選択肢が存在しない。
"""

def main(a):
    F = {b: preds.Flop(b, w) for b, w in gto.WEIGHTS.items()}
    fspots = collections.defaultdict(list)
    for key, d in gto.read(a.flop):
        fspots[key[:3]].append((F[key[3]], d))
    tspots = collections.defaultdict(list)
    for key, d in gto.read(a.turn):
        tspots[key[:3]].append((turnpred.Turn(key[3], key[4]), d))

    L = HEAD.split('\n')
    H = pattern.load(a.hands) if a.hands else {}
    t = pattern.THRESHOLDS[a.pattern]
    fq = {}
    for key, rows in fspots.items():
        lv = tree.grow(rows, max_leaves=a.flop_rules, min_w=150, max_depth=3)
        sh = shapes(lv, key, H, t) if H else {}
        fq[FLOPNAME[(key[0], key[2])]] = (tree.fmt(lv), tree.stats(rows)[1], error(lv), sh)
    for name in FORDER:
        rules, m, _, sh = fq[name]
        L.append(f"{name}    ベット率 {(1 - m['X']) * 100:.0f}%")
        for _, rule, v, n in rules:
            pat, bd, ex = sh.get(rule, ('', '', []))
            tail = f"  {pat} [{bd}]" if pat else ""
            L.append(f"{rule}（{v[0]}, {v[1]}, {v[2]}, {v[3]}, {v[4]}）  [{n}]{tail}")
            for p2, w, bs in ex:
                L.append(f"    例外 {p2} [{round(w)}]  {', '.join(bs)} など")
        L.append("")

    L += TURNHEAD.split('\n')
    tq, TORDER = {}, []
    for pair in ['UTG_vs_BB', 'UTG_vs_BTN', 'UTG_vs_SB', 'BTN_vs_BB', 'BTN_vs_SB', 'SB_vs_BB']:
        for line in ['XX', 'B33C', 'XC33']:
            for node in ['turn_OOP', 'turn_IP']:
                k = (pair, line, node)
                if k not in tspots: continue
                lv = turntree.grow(tspots[k], max_leaves=a.turn_rules, min_w=80, max_depth=3)
                nm = turnname(*k)
                TORDER.append(nm)
                tq[nm] = (turntree.fmt(lv), tree.stats(tspots[k])[1], error(lv))
    for nm in TORDER:
        rules, m, _ = tq[nm]
        L.append(f"{nm}    ベット率 {(1 - m['X']) * 100:.0f}%")
        for _, rule, v, n in rules:
            L.append(f"{rule}（{v[0]}, {v[1]}, {v[2]}, {v[3]}, {v[4]}）  [{n}]")
        L.append("")

    L += ["=========================  付録：精度  =========================", "",
          "各ルールの数字は、そのクラスに入る全ボードを出現確率で重み付けした平均。",
          "「誤差」は、1ボードの真の戦略とそのクラスの数字との差（重み付き平均、%ポイント）。",
          "「ベット誤差」はベットするか否かの判断だけに絞った差。いずれも10刻みに丸めた後の値。", "",
          f"{'スポット':30s} {'ルール数':>7s} {'誤差':>7s} {'ベット誤差':>9s}"]
    for name in FORDER:
        rules, _, (e, be), _ = fq[name]
        L.append(f"{name:30s} {len(rules):7d} {e:6.1f}pt {be:8.1f}pt")
    for nm in TORDER:
        rules, _, (e, be) = tq[nm]
        L.append(f"{nm:30s} {len(rules):7d} {e:6.1f}pt {be:8.1f}pt")
    fe = [fq[n][2] for n in FORDER]
    L += ["", "誤差の大半はサイズの配分であって、打つか打たないかの判断ではない。",
          f"フロップ12スポットの平均でベット誤差は{sum(b for _, b in fe)/len(fe):.1f}pt、"
          f"サイズ込みで{sum(e for e, _ in fe)/len(fe):.1f}pt。",
          "これは1755ボードを10クラス前後に畳んだことの代償で、クラスを増やせば下がるが、",
          "同じ10クラスなら他の切り方でこれ以上は下がらない水準まで詰めてある。"]

    open(a.out, "w").write("\n".join(L) + "\n")
    print(f"{a.out}: {len(L)} lines, {len(FORDER)} flop spots, {len(TORDER)} turn spots")
    for name in FORDER:
        assert sum(x[3] for x in fq[name][0]) == 22100, name
    for nm in TORDER:
        assert sum(x[3] for x in tq[nm][0]) == 2401, nm
    print("every spot's [N] adds up")

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--flop', default='flop40.csv.gz')
    p.add_argument('--turn', default='turn40.csv.gz')
    p.add_argument('--out', default='40BB_SRP_v2.txt')
    p.add_argument('--hands', default='hands40.csv.gz',
                   help="export_hands.py's output; without it the shape column is left off")
    p.add_argument('--pattern', default='B', choices=sorted(pattern.THRESHOLDS),
                   help='how hard a board has to lean before it is called a shape: '
                        'A loose, B middling, C strict')
    p.add_argument('--flop-rules', type=int, default=10)
    p.add_argument('--turn-rules', type=int, default=6)
    args = p.parse_args()
    if args.hands and not os.path.exists(args.hands): args.hands = None
    main(args)
