import gto, tree, collections, round10
RV = gto.RV
RANKS = 'AKQJT98765432'

BOOL = {
 'fpair': ('フロップがペアボード','フロップがペアでない'),
 'fmono': ('フロップがモノトーン','モノトーン以外'),
 'frain': ('フロップがレインボー','レインボー以外'),
 'fstr':  ('フロップでストレート完成','フロップでストレート未完成'),
 'pnow':  ('ターンまでにボードがペア','ターンまでボードがペアにならない'),
 'tpair': ('ターンでボードがペアになる','ターンでボードがペアにならない'),
 'flush': ('フラッシュ完成盤面','フラッシュ未完成盤面'),
 'tflush':('ターンでフラッシュ完成','ターンでフラッシュ完成しない'),
 'four':  ('同スート4枚目','同スート4枚目でない'),
 'fdrain':('レインボーのフロップにフラッシュドローが出現','そうでない'),
 'over':  ('ターンがオーバーカード','ターンがオーバーカードでない'),
 'phi':   ('ターンがフロップhiとペア','ターンがフロップhiとペアでない'),
 'plo':   ('ターンがフロップloとペア','ターンがフロップloとペアでない'),
 'run3':  ('ボードに3連続カード','ボードに3連続カードなし'),
 'f4str': ('ボード4枚がストレート圏内','ボード4枚がストレート圏内でない'),
}
NUM = {
 'nT':  ('ボードのT以上の枚数 ', lambda v: str(v), ''),
 'fhi': ('フロップhi ', lambda v: RANKS[12-v], ''),
 'fmid':('フロップmid ', lambda v: RANKS[12-v], ''),
 'flo': ('フロップlo ', lambda v: RANKS[12-v], ''),
 'turn':('ターン ', lambda v: RANKS[12-v], ''),
 'ghm': ('hiとmidの差 ', lambda v: str(v), ''),
 'gml': ('midとloの差 ', lambda v: str(v), ''),
}
BF = {'fpair':lambda t:t.flop_paired,'fmono':lambda t:t.flop_mono,'frain':lambda t:t.flop_rain,
 'fstr':lambda t:t.flop_str,'pnow':lambda t:t.paired_now,'tpair':lambda t:t.turn_pairs,
 'flush':lambda t:t.flush_made,'tflush':lambda t:t.turn_flush,'four':lambda t:t.fourth_suit,
 'fdrain':lambda t:t.fd_on_rainbow,'over':lambda t:t.overcard,'phi':lambda t:t.pairs_hi,
 'plo':lambda t:t.pairs_lo,'run3':lambda t:t.run3,'f4str':lambda t:t.four_straight}
NF = {'nT':lambda t:t.nT,'fhi':lambda t:t.hi,'fmid':lambda t:t.mid,'flo':lambda t:t.lo,
 'turn':lambda t:t.tr,'ghm':lambda t:t.gap_hm,'gml':lambda t:t.gap_ml}
RNG = {'nT':range(1,5),'fhi':range(RV['5'],13),'fmid':range(0,13),'flo':range(0,13),
 'turn':range(0,13),'ghm':range(0,10),'gml':range(0,10)}

CAND = [(k,None,None,f) for k,f in BF.items()]
for fam,g in NF.items():
    for v in RNG[fam]: CAND.append((fam,v,g,None))

def label(path):
    bools, nums = [], collections.defaultdict(lambda:[None,None])
    for fam,pos,v in path:
        if fam in BOOL: bools.append(BOOL[fam][0 if pos else 1])
        else:
            b=nums[fam]
            if pos: b[0]=v if b[0] is None else max(b[0],v)
            else:   b[1]=v-1 if b[1] is None else min(b[1],v-1)
    ORD=list(BOOL)
    bools.sort(key=lambda w: min((i for i,k in enumerate(ORD) for lab in BOOL[k] if lab==w),default=99))
    words=list(bools)
    for fam,(lo,hi) in nums.items():
        pre,r,suf=NUM[fam]
        if fam in ('fhi','fmid','flo','turn'):
            if lo is not None and hi is not None:
                words.append(f"{pre}{r(hi)}〜{r(lo)}" if hi!=lo else f"{pre}{r(lo)}")
            elif lo is not None: words.append(f"{pre}{r(lo)}以上")
            else: words.append(f"{pre}{r(hi)}以下")
        else:
            if lo is not None and hi is not None:
                words.append(f"{pre}{r(lo)}{suf}" if lo==hi else f"{pre}{r(lo)}〜{r(hi)}{suf}")
            elif lo is not None: words.append(f"{pre}{r(lo)}{suf}以上")
            else: words.append(f"{pre}{r(hi)}{suf}以下")
    return '　'.join(words) if words else '全ボード'

def grow(rows, max_leaves=6, min_w=80, max_depth=3, min_split=4):
    leaves=[(rows,[])]
    while len(leaves)<max_leaves:
        best=None
        for i,(rs,path) in enumerate(leaves):
            fams={p[0] for p in path}
            if len(fams)>=max_depth or len(rs)<2: continue
            base=tree.sse(rs)
            for c in CAND:
                fam,v,g,fn=c
                if fn and fam in fams: continue
                A=[(f,d) for f,d in rs if (fn(f) if fn else g(f)>=v)]
                B=[(f,d) for f,d in rs if not (fn(f) if fn else g(f)>=v)]
                if not A or not B: continue
                if sum(f.w for f,_ in A)<min_w or sum(f.w for f,_ in B)<min_w: continue
                gg=base-tree.sse(A)-tree.sse(B)
                if best is None or gg>best[0]: best=(gg,i,c,A,B)
        if best is None or best[0]<1e-4: break
        gg,i,c,A,B=best; rs,path=leaves.pop(i); fam,v,g,fn=c
        leaves.append((A,path+[(fam,True,v)])); leaves.append((B,path+[(fam,False,v)]))
    changed=True
    while changed:
        changed=False
        byp=collections.defaultdict(list)
        for idx,(rs,path) in enumerate(leaves):
            if path: byp[tuple(path[:-1])].append(idx)
        for par,idxs in byp.items():
            if len(idxs)!=2: continue
            a,b=idxs
            va,vb=tree.vec5(tree.stats(leaves[a][0])[1]),tree.vec5(tree.stats(leaves[b][0])[1])
            if sum(abs(x-y) for x,y in zip(va,vb))/2 < min_split:
                m=(leaves[a][0]+leaves[b][0],list(par))
                for j in sorted(idxs,reverse=True): leaves.pop(j)
                leaves.append(m); changed=True; break
    return leaves

def fmt(leaves, step10=True):
    out=[]
    for rs,path in leaves:
        tw,m=tree.stats(rs)
        v=round10.round_leaf(rs) if step10 else tree.vec5(m)
        out.append((tw,label(path),v,round(tw)))
    out.sort(reverse=True,key=lambda x:x[0])
    return out
