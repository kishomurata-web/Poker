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
import argparse, collections, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gto, preds, turnpred, tree, turntree, round10, pattern, maxscore

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

def refit(leaves, rows):
    """The same partition, filled with another stack depth's strategies.

    The board reading is the expensive half to learn and the boards do not
    change with the stack, so one depth's cuts carry to another and only the
    numbers on them are learned again. Measured at 1.2 points against cutting
    20BB its own way, where learning the conditions twice buys nothing.
    """
    by = {}
    for f, d in rows:
        by[(f.board, getattr(f, 'card', '-'))] = (f, d)
    out = []
    for rs, path in leaves:
        moved = [by[k] for k in ((f.board, getattr(f, 'card', '-')) for f, _ in rs) if k in by]
        if moved: out.append((moved, path))
    return out


def shapes(leaves, key, H, t, label, min_share=0.10, min_cover=0.70):
    """For each rule: the shape its boards share, and the boards that break it.

    The rule's own shape is read off its boards merged, which is the same
    weighting its printed frequencies use, so the label and the numbers on a
    line are describing the same thing.
    """
    out = {}
    for rs, path in leaves:
        per = []
        for f, _ in rs:
            k = (key[0], key[1], key[2], f.board, getattr(f, 'card', '-'))
            if k in H:
                nm = f.board if k[4] == '-' else f"{f.board}+{k[4]}"
                per.append((f.w, nm, H[k]))
        # A rule whose boards are mostly absent from the export would still
        # produce a confident-looking label off whatever is left, so it gets
        # none at all.
        if sum(w for w, _, _ in per) < min_cover * sum(f.w for f, _ in rs):
            continue
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
        out[label(path)] = (pat, pattern.describe(bd), ex)
    return out


def play_table(leaves, key, H, label, weight, by_action, names, scale=1.0):
    """For each rule: one action per group of hand strengths, biggest group first."""
    out = []
    for rs, path in leaves:
        tw = sum(f.w for f, _ in rs)
        by = collections.defaultdict(list)
        for f, _ in rs:
            k = (key[0], key[1], key[2], f.board, getattr(f, 'card', '-'))
            for bk, c, what in H.get(k, []):
                by[bk].append((weight(f.w, c), what))
        if not by: continue
        if by_action == 'ev':
            gs = [(names.get((key[0], key[2], code), code), bks, w, s)
                  for code, bks, w, s in maxscore.action_groups_ev(by, pattern.BUCKETS)]
        elif by_action == 'action':
            gs = [(names.get((key[0], key[2], code), code), bks, w, s)
                  for code, bks, w, s in maxscore.action_groups(by, pattern.BUCKETS)]
        else:
            gs = [(maxscore.TIER_NAMES[t], bks, w, s)
                  for t, bks, w, s in maxscore.groups(by, pattern.BUCKETS)]
        out.append((tw, label(path), round(tw * scale), gs))
    out.sort(reverse=True, key=lambda x: x[0])
    return out


def rule_block(rule, v, n, shape, play, play_label='打つなら'):
    """The lines one rule occupies: its frequencies, its shape, and how to play it."""
    pat, bd, ex = shape
    tail = f"  {pat} [{bd}]" if pat else ""
    out = [f"{rule}（{v[0]}, {v[1]}, {v[2]}, {v[3]}, {v[4]}）  [{n}]{tail}"]
    for p2, w, bs in ex:
        out.append(f"    例外 {p2} [{round(w)}]  {', '.join(bs)} など")
    if play:
        # The label sits on its own line: it is Japanese, so padding the first
        # entry across from it would misalign against every entry below.
        out.append(f"    {play_label}")
        out += ['  ' + l for l in group_lines(play)]
    return out


def group_lines(gs):
    """One line per action, with how much of the range it covers."""
    tot = sum(x[2] for x in gs)
    out = []
    for i, (name, bks, w, _) in enumerate(gs):
        # Only the first line may be the remainder; every other line has to name
        # its own buckets, or two of them read as "everything else" at once.
        if len(gs) == 1:              who = '全区分'
        elif i == 0 and len(bks) > 6: who = 'それ以外'
        else:                         who = ', '.join(bks)
        pc = w / tot * 100
        share = '<1%' if 0 < pc < 1 else f'{pc:.0f}%'
        out.append(f"    {name:6s} ← {who}    (レンジの{share})")
    return out


def hands_by_decision(path, want_ev=False):
    """(pair, line, node, board, card) -> [(bucket, combos, what to choose on)].

    The last element is a map of real action to frequency when the export
    carries one, and the five-tier mix when it does not. The app scores the
    action, so the first is what the table wants; the second is what an older
    export can still answer with.
    """
    out = collections.defaultdict(list)
    if maxscore.has_actions(path):
        ev = want_ev and maxscore.has_ev(path)
        for r, _, f in maxscore.action_rows(path, lambda r: 1.0, ev):
            out[(r['pair'], r['line'], r['node'], r['board'], r['card'])].append(
                (r['bucket'], float(r['combos']), f))
        return out, ('ev' if ev else 'action')
    for r, _, mix in maxscore.rows(path, lambda r: 1.0):
        out[(r['pair'], r['line'], r['node'], r['board'], r['card'])].append(
            (r['bucket'], float(r['combos']), mix))
    return out, 'tier' 


def size_labels(path):
    """(pair, node, code) -> the size as a share of pot, e.g. "33%"."""
    import csv, gzip
    out = {}
    with gzip.open(path, 'rt') as fh:
        for r in csv.DictReader(fh):
            code = r['code']
            if code == 'X': out[(r['pair'], r['node'], code)] = 'check'
            elif code == 'RAI': out[(r['pair'], r['node'], code)] = 'all-in'
            elif r['frac']: out[(r['pair'], r['node'], code)] = f"{round(float(r['frac']) * 100)}%"
    return out


MERGED_HEAD = """__LABEL__ SRP 簡易GTO戦略 v2 統合版

■ 1つのルールに2種類の情報が載っている

    ペアなし　T以上が1枚以上　hi-mid差 4以下（10, 40, 30, 20, 0）  [9600]  レンジベット [93/96/90/88]
        打つなら  ~33%   ← それ以外    (レンジの90%)
                  75%    ← オーバーペア, ナッツFD    (レンジの6%)

カッコの5つ組はレンジ全体がどう動くかで、混ぜることが前提。「打つなら」以下は、
自分の手で何を打つかを1つに決めたもので、混ぜない。

アプリの採点は1ハンドの選択を、そのハンドにとっての最頻アクションと比べて付く
（index.html の tierFor / gtoScoreFor）。混ぜるほど点は下がるので、点を取りにいくなら
「打つなら」の行だけを見ればよい。レンジがどう組まれているかを知りたいときに5つ組を見る。

「打つなら」の通りに打った場合の期待スコアは巻末の付録にある。混ぜた場合はそれより
10〜20ポイント低い。

"""


PLAY_HEAD = """__LABEL__ SRP 実戦用アクション表（スコア最大化版）

■ これは何か
頻度表（__LABEL___SRP_v2.txt）はレンジ全体がどう動くかの記述で、混ぜて打つことを前提にしている。
この表はそれとは目的が違い、アプリの採点で点を取るための表である。

アプリは1ハンドの選択を、そのハンドにとっての最頻アクションと比べて採点する
（index.html の tierFor / gtoScoreFor）。最頻アクションちょうどなら1.0、そうでなければ
その最頻アクションに対する頻度の比。つまり混ぜるほど点は下がり、毎回その場の最頻
アクションを選ぶのが最大化になる。人が正確に混ぜるのは難しいという前提に立つなら、
実戦で引くのはこちらの表になる。

■ 読み方
ボードのルールを引き、自分のハンドがどの区分かを見て、その行のアクションを打つ。
混ぜない。カッコ内はその区分がレンジに占める割合で、その行が何割の場面で効くかを示す。

■ ハンドの区分（強い順）
メイド: ストフラ・4カード / フルハウス / フラッシュ / ストレート / 3カード / 2ペア /
        オーバーペア / トップペア / 2nd-3rdペア / 最下位ペア以下
ノーペア: コンボドロー / ナッツFD / FD / OESD / ガットショット / 2BDFD / ノーペア
メイドのペアはホールカードが絡んだものだけを数える。K K 7 で A 2 を持つ手は場のペアを
見ているだけなので「ノーペア」に入る。

■ アクション
check / ~33% / 50% / 75% / 125%~ の5段階。実サイズの丸め方は頻度表と同じ。
「~33%」に実サイズが2つ含まれるスポットがあり、どちらを打つかは使う人の判断になる。
下の期待スコアは、そこを常に正しく選べた場合の値なので、その分だけ上振れしている。

"""

HEAD = """__LABEL__ SRP 簡易GTO戦略 v2（1755フロップ全数版）

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
__TIERNOTE__

■ [N] の意味
フロップ：22,100通りの実フロップのうち何通りか（1755クラスを出現確率で重み付け、合計22,100）。
ターン：49フロップ×49ターンカード=2,401通りのうち何通りか（現行版と同じ）。

■ ハンドランクとベット頻度
各ルールには、そのクラスのベットの形を付記している。レンジをメイド強度順に
並べ、上から5% / 5-15% / 15-40% / 40-100% の4区間それぞれのベット率が [ナッツ/強/中/弱]。

  レンジベット  どの強さでも同じくらい打つ。ハンドランクがサイズを決めない。
  デポラー      最上位がチェックに回り、一段下から打つ。
  ポラー        強い側と弱い側が打ち、中途半端な強さがチェックする。
  標準          強いほど打つ。

クラス内でこの形が食い違うボードは、そのルールの下に「例外」として並べてある。クラスの形は
そのクラス全体を混ぜて読むので、ポラーのように一部のボードだけがU字を描く形は平均に埋もれる。
ボード単位ではポラーはフロップの5.6%、ターンの5.4%にあたり、いずれもIPがチェックを受けて
打つノードに偏っている。クラスのラベルではなく例外欄の方に現れることが多い。
形を読むだけのデータが揃わないクラスには、ラベルを付けていない。
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
    # A depth whose turn has not been collected yet gets a flop-only table
    # rather than one quietly carrying another depth's turn.
    tspots = collections.defaultdict(list)
    if a.turn:
        for key, d in gto.read(a.turn):
            tspots[key[:3]].append((turnpred.Turn(key[3], key[4]), d))

    L = HEAD.split('\n')
    ALLOC = json.load(open(a.alloc)) if a.alloc else {}
    def rules_for(prefix, key, default):
        """How many rules this spot earns. allocate.py decides it per spot when
        the table is meant to be memorised; otherwise every spot gets the same."""
        return ALLOC.get(prefix + '|' + '|'.join(key), default)

    t = pattern.THRESHOLDS[a.pattern]
    H = pattern.load(a.hands) if a.hands else {}
    TH = pattern.load(a.turn_hands) if a.turn_hands else {}
    # --tree-from cuts the boards on one depth's strategies and fills the
    # classes with this one's, so the board reading is learned once.
    # A spot the reference depth did not collect is cut on its own boards
    # instead. Reaching into a defaultdict for it would hand grow() an empty
    # reference and produce a spot with no boards at all, which is worse than
    # learning that spot's conditions twice.
    rspots = tspots_ref = None
    borrowed = []
    if a.tree_from:
        rspots = {}
        for key, d in gto.read(a.tree_from):
            rspots.setdefault(key[:3], []).append((F[key[3]], d))
    if a.turn_tree_from:
        tspots_ref = {}
        for key, d in gto.read(a.turn_tree_from):
            tspots_ref.setdefault(key[:3], []).append((turnpred.Turn(key[3], key[4]), d))

    fq, FLOPKEY, TURNKEY = {}, {}, {}
    for key, rows in fspots.items():
        ref = rspots.get(key) if rspots else None
        if rspots and ref is None: borrowed.append(('フロップ', key))
        lv = tree.grow(ref or rows,
                       max_leaves=rules_for('F', key, a.flop_rules),
                       min_w=150, max_depth=a.depth)
        if ref: lv = refit(lv, rows)
        sh = shapes(lv, key, H, t, tree.label) if H else {}
        FLOPKEY[FLOPNAME[(key[0], key[2])]] = (key, lv)
        fq[FLOPNAME[(key[0], key[2])]] = (tree.fmt(lv), tree.stats(rows)[1], error(lv), sh)
    for name in FORDER:
        rules, m, _, sh = fq[name]
        L.append(f"{name}    ベット率 {(1 - m['X']) * 100:.0f}%")
        for _, rule, v, n in rules:
            L += rule_block(rule, v, n, sh.get(rule, ('', '', [])), None)
        L.append("")

    L += TURNHEAD.split('\n')
    tq, TORDER = {}, []
    for pair in ['UTG_vs_BB', 'UTG_vs_BTN', 'UTG_vs_SB', 'BTN_vs_BB', 'BTN_vs_SB', 'SB_vs_BB']:
        for line in ['XX', 'B33C', 'XC33']:
            for node in ['turn_OOP', 'turn_IP']:
                k = (pair, line, node)
                if k not in tspots: continue
                ref = tspots_ref.get(k) if tspots_ref else None
                if tspots_ref and ref is None: borrowed.append(('ターン', k))
                lv = turntree.grow(ref or tspots[k],
                                   max_leaves=rules_for('T', k, a.turn_rules),
                                   min_w=80, max_depth=a.depth)
                if ref: lv = refit(lv, tspots[k])
                nm = turnname(*k)
                TORDER.append(nm)
                TURNKEY[nm] = (k, lv)
                tq[nm] = (turntree.fmt(lv), tree.stats(tspots[k])[1], error(lv),
                          shapes(lv, k, TH, t, turntree.label) if TH else {})
    for nm in TORDER:
        rules, m, _, sh = tq[nm]
        L.append(f"{nm}    ベット率 {(1 - m['X']) * 100:.0f}%")
        for _, rule, v, n in rules:
            L += rule_block(rule, v, n, sh.get(rule, ('', '', [])), None)
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
        rules, _, (e, be), _ = tq[nm]
        L.append(f"{nm:30s} {len(rules):7d} {e:6.1f}pt {be:8.1f}pt")
    fe = [fq[n][2] for n in FORDER]
    L += ["", "誤差の大半はサイズの配分であって、打つか打たないかの判断ではない。",
          f"フロップ12スポットの平均でベット誤差は{sum(b for _, b in fe)/len(fe):.1f}pt、"
          f"サイズ込みで{sum(e for e, _ in fe)/len(fe):.1f}pt。",
          "これは1755ボードを10クラス前後に畳んだことの代償で、クラスを増やせば下がるが、",
          "同じ10クラスなら他の切り方でこれ以上は下がらない水準まで詰めてある。"]

    # What the last column actually holds is a fact about the stack depth, not
    # a sentence to carry over: at 40BB the flop never overbets, at 20BB the
    # column is all-ins that happen to be three times the pot.
    big = collections.defaultdict(float)
    tot = 0.0
    for key, rows in fspots.items():
        for f, d in rows:
            for t in ('XL', 'OB'): big[t] += d.get(t, 0.0) * f.w
            tot += f.w
    xl, ob = big['XL'] / tot * 100, big['OB'] / tot * 100
    note = (f"フロップで125%~の枠に入るのは{xl + ob:.1f}%"
            + (f"（オーバーベット{xl:.1f}% ＋ オールイン{ob:.1f}%）。" if xl + ob >= 0.05
               else "で、事実上使われない。"))
    if TORDER:
        note += "ターンでは200%とオールインもこの枠に含めている。"
    L = [x.replace('__TIERNOTE__', note) for x in L]
    open(a.out, "w").write("\n".join(L) + "\n")

    if a.play_out and (H or TH):
        P = [PLAY_HEAD.replace('__LABEL__', a.label), "=========================  フロップ  =========================", ""]
        ev = a.objective == 'ev'
        HF, FA = hands_by_decision(a.hands, ev) if a.hands else ({}, 'tier')
        HT, TA_ = hands_by_decision(a.turn_hands, ev) if a.turn_hands else ({}, 'tier')
        NF = size_labels(a.flop) if FA != 'tier' else {}
        NT = size_labels(a.turn) if TA_ != 'tier' else {}
        EV = FA == 'ev' or TA_ == 'ev'
        sc = {}
        for name in FORDER:
            key, lv = FLOPKEY[name]
            rt = play_table(lv, key, HF, tree.label, lambda w, c: w * c, FA, NF)
            if not rt: continue
            P.append(f"{name}")
            for _, rule, n, gs in rt:
                P.append(f"{rule}  [{n}]")
                P += group_lines(gs)
                P.append("")
            sw = sum(w for _, _, _, gs in rt for _, _, w, _ in gs)
            sc[name] = (sum(s2 * w for _, _, _, gs in rt for _, _, w, s2 in gs) / sw,
                        sw, FA == 'ev')
        if TORDER: P += ["", "=========================  ターン  =========================", ""]
        for nm in TORDER:
            key, lv = TURNKEY[nm]
            rt = play_table(lv, key, HT, turntree.label, lambda w, c: c, TA_, NT)
            if not rt: continue
            P.append(f"{nm}")
            for _, rule, n, gs in rt:
                P.append(f"{rule}  [{n}]")
                P += group_lines(gs)
                P.append("")
            sw = sum(w for _, _, _, gs in rt for _, _, w, _ in gs)
            sc[nm] = (sum(s2 * w for _, _, _, gs in rt for _, _, w, s2 in gs) / sw,
                      sw, TA_ == 'ev')
        P += ["", "=========================  付録：この表の成績  =========================", "",
              "平均EVロス：各ハンドにとっての最善手と比べて失うEV。単位はソリューションと同じ",
              "（チップEVならbb）。0に近いほどよい。",
              "期待スコア：アプリが付ける点の見込み。EVを持たないエクスポートのスポットはこちら。",
              "いずれも17区分の集計で測っているので、同じ区分の中でハンドごとに最善手が割れる",
              "分だけ実際はこれより不利に出る。", ""]
        # EV given up and the app's score are different quantities in different
        # units, and an export that carries EV for one street and not the other
        # leaves both in play. They are never averaged together.
        for by_ev, what in ((True, '平均EVロス'), (False, '期待スコア')):
            part = {n: sc[n] for n in
                    [x for x in FORDER if x in sc] + [x for x in TORDER if x in sc]
                    if sc[n][2] == by_ev}
            if not part: continue
            fmt2 = (lambda v: f"{v:.4f}") if by_ev else (lambda v: f"{v * 100:.1f}%")
            P.append(f"── {what}（{len(part)}スポット）")
            for nm in part:
                P.append(f"{nm:30s} {fmt2(part[nm][0])}")
            plain = sum(v for v, _, _ in part.values()) / len(part)
            wsum = sum(w for _, w, _ in part.values())
            weighted = sum(v * w for v, w, _ in part.values()) / wsum
            P += ["", f"   単純平均 {fmt2(plain)}   到達レンジ量で重み付け {fmt2(weighted)}", ""]
        P += ["前者は各スポットを等しく数え、後者は実際に手が来る量で数える。滅多に座らない",
              "スポットは実戦にほとんど効かないので、後者の方が実感に近い。"]
        open(a.play_out, "w").write("\n".join(P) + "\n")
        print(f"{a.play_out}: {len(P)} lines")

        if a.json_out:
            # The drill app evaluates the conditions itself rather than being
            # handed a board-to-rule table: 88,288 decisions would not travel,
            # and a rule carried as its own conditions can be asked of a board
            # nobody solved.
            J = {'buckets': pattern.BUCKETS, 'spots': []}
            for street, order, keyed, tq_, labeller, hands, acts, names, wf in (
                    ('flop', FORDER, FLOPKEY, fq, tree.label, HF, FA, NF, lambda w, c: w * c),
                    ('turn', TORDER, TURNKEY, tq, turntree.label, HT, TA_, NT, lambda w, c: c)):
                for name in order:
                    key, lv = keyed[name]
                    rules, m, _, sh = tq_[name]
                    by_label = {lab: (v, n) for _, lab, v, n in rules}
                    plays = {lab: gs for _, lab, _, gs in
                             play_table(lv, key, hands, labeller, wf, acts, names)}
                    out = []
                    for rs, path in lv:
                        lab = labeller(path)
                        if lab not in by_label: continue
                        v, n = by_label[lab]
                        pat, bd, _ = sh.get(lab, ('', '', []))
                        gs = plays.get(lab, [])
                        tot = sum(g[2] for g in gs) or 1.0
                        out.append({
                            'label': lab, 'cond': [[f, bool(p), x] for f, p, x in path],
                            'freq': v, 'n': n, 'pattern': pat, 'bands': bd,
                            'play': [{'act': g[0], 'buckets': g[1],
                                      'share': round(g[2] / tot, 4)} for g in gs]})
                    out.sort(key=lambda r: -r['n'])
                    J['spots'].append({'name': name, 'street': street,
                                       'pair': key[0], 'line': key[1], 'node': key[2],
                                       'bet': round((1 - m['X']) * 100), 'rules': out})
            json.dump(J, open(a.json_out, 'w'), ensure_ascii=False)
            print(f"{a.json_out}: {len(J['spots'])} spots, "
                  f"{sum(len(s2['rules']) for s2 in J['spots'])} rules")

        if a.merged_out:
            play = {}
            for name in FORDER:
                key, lv = FLOPKEY[name]
                for _, rule, _, gs in play_table(lv, key, HF, tree.label, lambda w, c: w * c, FA, NF):
                    play[(name, rule)] = gs
            for nm in TORDER:
                key, lv = TURNKEY[nm]
                for _, rule, _, gs in play_table(lv, key, HT, turntree.label, lambda w, c: c, TA_, NT):
                    play[(nm, rule)] = gs
            M = MERGED_HEAD.replace('__LABEL__', a.label).split("\n")
            if a.alloc:
                M += ["■ この版について",
                      "暗記用に、ルール数をスポットごとに配分しなおした版である。次の1ルールは、",
                      "覚える行数あたりで最も点が伸びるスポットに渡してある。ボードの読み分けが",
                      "点にならないスポットは1ルールのままで、その分をフロップの数スポットに寄せている。",
                      ""]
            M += [x.replace('__TIERNOTE__', note) for x in HEAD.split("\n")[1:]]
            for name in FORDER:
                rules, m, _, sh = fq[name]
                M.append(f"{name}    ベット率 {(1 - m['X']) * 100:.0f}%")
                for _, rule, v, n in rules:
                    M += rule_block(rule, v, n, sh.get(rule, ('', '', [])),
                                    play.get((name, rule))) + [""]
            if TORDER: M += TURNHEAD.split("\n")
            for nm in TORDER:
                rules, m, _, sh = tq[nm]
                M.append(f"{nm}    ベット率 {(1 - m['X']) * 100:.0f}%")
                for _, rule, v, n in rules:
                    M += rule_block(rule, v, n, sh.get(rule, ('', '', [])),
                                    play.get((nm, rule))) + [""]
            M += L[L.index("=========================  付録：精度  ========================="):]
            M += ["", "=========================  付録：この表の成績  ========================="]
            head = "=========================  付録：この表の成績  ========================="
            M += P[P.index(head) + 1:]
            open(a.merged_out, "w").write("\n".join(M) + "\n")
            print(f"{a.merged_out}: {len(M)} lines")
    print(f"{a.out}: {len(L)} lines, {len(FORDER)} flop spots, {len(TORDER)} turn spots")
    if borrowed:
        print("these spots were cut on their own boards - the reference depth "
              "did not collect them, so their conditions are learned separately:")
        for street, k in borrowed:
            print(f"  {street}  {'  '.join(k)}")
    # [N] counts the real flops a rule covers, so a spot whose sweep did not
    # finish adds up short. That is worth saying rather than asserting away -
    # the table is still usable, it just describes slightly fewer boards.
    short = []
    for name in FORDER:
        got = sum(x[3] for x in fq[name][0])
        if got != 22100: short.append((name, got, 22100))
    for nm in TORDER:
        got = sum(x[3] for x in tq[nm][0])
        if got != 2401: short.append((nm, got, 2401))
    if not short:
        print("every spot's [N] adds up")
    else:
        print("incomplete sweeps - these spots describe fewer boards than exist:")
        for name, got, want in short:
            print(f"  {name:30s} {got:,} / {want:,}  ({got / want * 100:.1f}%)")

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--flop', default='flop40.csv.gz')
    p.add_argument('--turn', default='turn40.csv.gz',
                   help='omit with --turn "" for a flop-only table')
    p.add_argument('--out')
    p.add_argument('--hands', default='hands40.csv.gz',
                   help="export_hands.py's output; without it the shape column is left off")
    p.add_argument('--turn-hands', default='turnhands40.csv.gz',
                   help='export_hands.py run over the turn cache')
    p.add_argument('--pattern', default='B', choices=sorted(pattern.THRESHOLDS),
                   help='how hard a board has to lean before it is called a shape: '
                        'A loose, B middling, C strict')
    p.add_argument('--label', default='40BB',
                   help='the stack depth this table is for, as it heads the page')
    p.add_argument('--tree-from', help="cut the flop boards on this depth's "
                   "frequency export, and fill the classes with --flop's")
    p.add_argument('--turn-tree-from', help='the same for the turn')
    p.add_argument('--objective', default='score', choices=('score', 'ev'),
                   help="what the play lines optimise. 'score' maximises what the "
                        "app grades, which never looks at EV inside the strategy "
                        "and so drops the overbets; 'ev' minimises what the choice "
                        "costs, and needs an export carrying EV")
    p.add_argument('--depth', type=int, default=3,
                   help='how many conditions a rule may carry. A fourth is worth about\n'
                        'two tenths of a point and costs no lines, but is one more thing\n'
                        'to check at the table')
    p.add_argument('--alloc', help="allocate.py's per-spot rule counts, for a "
                                   "table sized to be memorised")
    p.add_argument('--json-out',
                   help='the same table as structured data, for the drill app')
    p.add_argument('--merged-out',
                   help='both documents woven into one')
    p.add_argument('--play-out',
                   help='where to write the score-maximising action table')
    p.add_argument('--flop-rules', type=int, default=10)
    p.add_argument('--turn-rules', type=int, default=6)
    args = p.parse_args()
    # The output names carry the depth, so a 20BB run cannot land on the 40BB
    # files by leaving a flag off. They used to default to the 40BB names,
    # which quietly overwrote that table whenever another depth was built.
    for f, suffix in (('out', '_SRP_v2.txt'), ('json_out', '_SRP.json'),
                      ('merged_out', '_SRP_all.txt'), ('play_out', '_SRP_play.txt')):
        if getattr(args, f) is None: setattr(args, f, args.label + suffix)
    for f in ('hands', 'turn_hands'):
        if getattr(args, f) and not os.path.exists(getattr(args, f)): setattr(args, f, None)
    main(args)
