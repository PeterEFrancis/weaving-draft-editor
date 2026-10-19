"""Extract reviewed vector weaving charts from Handwoven Spring 2025."""
import json, math, re
from pathlib import Path
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/Users/peterfrancis/Library/Mobile Documents/com~apple~CloudDocs/Books/Handwoven Magazine/2025 II Spring.pdf')
PDF = pdfplumber.open(SOURCE)
SCRATCH = ROOT / 'tmp/pdfs/handwoven-2025-ii-spring'
SCRATCH.mkdir(parents=True, exist_ok=True)

def page(n): return PDF.pages[n-1]

def segments(p):
    out=[]
    for obj in p.lines+p.curves+p.rects:
        pts=obj.get('pts',[])
        for a,b in zip(pts,pts[1:]):
            if abs(a[0]-b[0])<.02 or abs(a[1]-b[1])<.02:
                out.append((a,b))
    return out

def repeats(p, axis, region):
    """Read the two vector halves adjacent to each printed repeat count."""
    segs=segments(p); result=[]
    for w in p.extract_words():
        if not re.fullmatch(r'\d+x',w['text']): continue
        cx=(w['x0']+w['x1'])/2;cy=(w['top']+w['bottom'])/2
        if not(region[0]<cx<region[2] and region[1]<cy<region[3]): continue
        if (axis=='x') != w['upright']: continue
        c,at=(cy-1.75,cx) if axis=='x' else (cx+.25,cy)
        candidates=[]
        for a,b in segs:
            const=(a[1],b[1]) if axis=='x' else (a[0],b[0])
            lo,hi=sorted((a[0],b[0]) if axis=='x' else (a[1],b[1]))
            if abs(const[0]-const[1])<.02 and abs(const[0]-c)<4 and hi-lo>.5:
                candidates.append((abs(const[0]-c),const[0],lo,hi))
        # For each candidate bracket line, find its nearest halves around the label.
        options=[]
        for coord in set(round(a[1],2) for a in candidates):
            runs=[a for a in candidates if abs(a[1]-coord)<.6]
            left=[a for a in runs if a[3]<=at+1]
            right=[a for a in runs if a[2]>=at-1]
            if left and right:
                l=min(left,key=lambda a:abs(a[3]-at));r=min(right,key=lambda a:abs(a[2]-at))
                score=abs(coord-c)*3+abs(l[3]-at)+abs(r[2]-at)
                options.append((score,l[2],r[3],coord))
        if not options: raise ValueError(('No bracket',w))
        _,lo,hi,coord=min(options)
        result.append((lo,hi,int(w['text'][:-1]),w['text']))
    return result

def expand(seq,reps,start,cell):
    rr=[]
    for lo,hi,n,*_ in reps:
        a=round((lo-start)/cell);b=round((hi-start)/cell)
        if a<0 or b>len(seq) or a>=b: raise ValueError(('bad bracket',lo,hi,a,b,len(seq)))
        rr.append((a,b,n))
    def part(a,b,exclude=None):
        out=[];i=a
        while i<b:
            choices=[r for r in rr if r!=exclude and r[0]==i and r[1]<=b]
            if choices:
                r=max(choices,key=lambda r:r[1]);out+=part(r[0],r[1],r)*r[2];i=r[1]
            else:out.append(seq[i]);i+=1
        return out
    return part(0,len(seq))

def glyphgrid(p,x,y,cols,rows,cell):
    out=[[[] for _ in range(cols)] for _ in range(rows)]
    for ch in p.chars:
        cx=(ch['x0']+ch['x1'])/2;cy=(ch['top']+ch['bottom'])/2
        if x<cx<x+cols*cell and y<cy<y+rows*cell and ch['text'].isdigit():
            out[int((cy-y)/cell)][int((cx-x)/cell)].append(int(ch['text']))
    return out

def threading(p,x,y,n,shafts,cell=9,reps=None):
    g=glyphgrid(p,x,y,n,shafts,cell)
    seq=[sum((g[r][c] for r in range(shafts)),[]) for c in range(n)]
    if any(len(v)!=1 for v in seq):raise ValueError(('bad threading',seq))
    seq=[v[0] for v in seq]
    return expand(seq,reps or [],x,cell)

def circle_threading(p,x,y,n,shafts,cell=9,reps=None):
    seq=[None]*n
    for obj in p.curves:
        cx=(obj['x0']+obj['x1'])/2;cy=(obj['top']+obj['bottom'])/2
        if x<cx<x+n*cell and y<cy<y+shafts*cell and .45*cell<obj['width']<.75*cell and abs(obj['height']-cell*2/3)<.2 and any(op[0]=='c' for op in obj.get('path',[])):
            col=int((cx-x)/cell);row=int((cy-y)/cell)
            value=(shafts-row,cmyk(obj['non_stroking_color']))
            if seq[col] is None:seq[col]=value
            elif seq[col][0]!=value[0]:raise ValueError(('multiple circle threading',col))
    if None in seq:raise ValueError(('missing circle threading',[i for i,v in enumerate(seq) if v is None],x,y))
    return expand(seq,reps or [],x,cell)

def tieup(p,x,y,n,shafts,cell=9):
    g=glyphgrid(p,x,y,n,shafts,cell)
    return [sorted(set(sum((g[r][c] for r in range(shafts)),[]))) for c in range(n)]

def cmyk(color):
    if isinstance(color,(tuple,list)) and len(color)==4:
        c,m,y,k=color; return '#'+''.join(f'{round(255*(1-v)*(1-k)):02x}' for v in (c,m,y))
    if isinstance(color,(tuple,list)) and len(color)==3:return '#'+''.join(f'{round(255*v):02x}' for v in color)
    return '#222222'

def treadling(p,x,y,n,rows,cell=9,reps=None):
    result=[None]*rows
    for r in p.rects:
        cx=(r['x0']+r['x1'])/2;cy=(r['top']+r['bottom'])/2
        if x<cx<x+n*cell and y<cy<y+rows*cell and .4*cell<r['width']<.9*cell and .4*cell<r['height']<.9*cell:
            i=int((cy-y)/cell);value=(int((cx-x)/cell),cmyk(r['non_stroking_color']))
            if result[i] is not None and result[i]!=value:raise ValueError(('multiple treadles',i,result[i],value))
            result[i]=value
    if None in result:raise ValueError(('missing treadling',[(i,v) for i,v in enumerate(result) if v is None]))
    return expand(result,reps or [],y,cell)

def slash_treadling(p,x,y,n,rows,cell=9,reps=None):
    result=[None]*rows
    for ch in p.chars:
        cx=(ch['x0']+ch['x1'])/2;cy=(ch['top']+ch['bottom'])/2
        if x<cx<x+n*cell and y<cy<y+rows*cell and ch['text']=='/':result[int((cy-y)/cell)]=(int((cx-x)/cell),'#f3efe4')
    # Blank grid separator rows are printed between the lace and its ending.
    return [v for v in expand(result,reps or [],y,cell) if v is not None]

PATTERNS=[]
def add(printpage,title,designer,kind,thread,picks,tie,description,variant=1,colors=None,warp=None,weft=None,shafts=None,thickness=None):
    palette=list(colors or dict.fromkeys([c for _,c in thread]+[c for _,c in picks]))
    obj=dict(id=f'hw-2025-ii-spring-p{printpage:02}-s{variant:02}',title=title,designer=designer,pages=str(printpage),kind=kind,description=description,shafts=shafts or max(s for s,_ in thread),threading=[s for s,_ in thread],lifts=[tie[t] for t,_ in picks],colors=palette,warpColors=warp if warp is not None else [palette.index(c) for _,c in thread],weftColors=weft if weft is not None else [palette.index(c) for _,c in picks])
    if thickness:obj['thickness']=thickness
    PATTERNS.append(obj)

def extract():
    # Seven towels share the exact huck threading, with five printed treadlings;
    # the source explicitly obtains towels 2 and 4 by swapping weft colors.
    p=page(32);tx=292.2125;ty=96
    wr=repeats(p,'x',(290,60,430,95))
    th=threading(p,tx,ty,15,4,reps=wr)[::-1]
    assert len(th)==537,(len(th),wr)
    tu=tieup(p,427.2125,96,6,4)
    for towel,x,y,rows in [(1,427.2125,132,61),(3,328.2125,195,51),(5,238.2125,195,47),(6,139.2125,114,65),(7,40.2125,114,67)]:
        rr=repeats(p,'y',(x+54,y,x+99,y+rows*9))
        picks=treadling(p,x,y,6,rows,reps=rr)
        thread=[(s,'#f7f4d5') for s in th]
        desc=f'Full 537-end huck-lace threading and Towel {towel} treadling, including the printed numeric repeat brackets. Length-only plain-weave hem brackets are represented by one shown shed pair; weave those hems to the stated 2¾ inches in the source.'
        add(28,f'Sweet Linen and Lace Towels - Towel {towel}','Malynda Allen','Huck lace and plain weave',thread,picks,tu,desc,variant=towel)
        if towel in (1,3):
            cs=list(dict.fromkeys(c for _,c in picks));assert len(cs)==2,cs
            swaps=[(t,cs[1-cs.index(c)]) for t,c in picks]
            add(28,f'Sweet Linen and Lace Towels - Towel {towel+1}','Malynda Allen','Huck lace and plain weave',thread,swaps,tu,desc.replace(f'Towel {towel} treadling',f'Towel {towel+1} color-swapped treadling'),variant=towel+1)

    # Lighter than Air: both shaft-count alternatives are printed. The source
    # stripe tables specify the individual hues represented by multicolor marks.
    p=page(36)
    palette=['#f5f1e5','#12334e','#2b5597','#54aaca','#9bc77a','#edb9bc','#b55c9c','#ed9254','#e9d557']
    warp=[1]*14+[0]*12+[1]*12+[0]*12
    for c in [2,8,7,6,5,4,3,2]:warp+=([c]*12+[0]*12)*2
    warp += [1]*12+[0]*12+[1]*14
    assert len(warp)==472
    # The printed weft list is ordered from top to bottom; each colored stripe
    # is woven three times, alternating 12 colored and 12 white picks.
    weftlist=[1,2,3,4,5,6,7,8,4,3,6,5,8,7,4,6,5,7,2,6,7,3,5,4,8,6,2,5,7,4,3,2,1]
    weft=[]
    for c in weftlist:weft+=([c]*12+[0]*12)*3
    for v,shafts,x,y in [(1,4,223.3718,422.45),(2,2,225.16,647.4)]:
        reps=repeats(p,'x',(x-1,y-25,x+217,y))
        th=circle_threading(p,x,y,24,shafts,reps=reps)[::-1]
        assert len(th)==472
        # Actual loom sheds: even versus odd shafts, using the printed tie-up.
        tie=[[s for s in range(1,shafts+1) if s%2],[s for s in range(1,shafts+1) if not s%2]]
        picks=[(i%2,palette[c]) for i,c in enumerate(weft)]
        add(32,f'Lighter than Air Shawl - {shafts} Shafts','Véronique Perrot','Plain weave',th,picks,tie,'Full 472-end striped-linen warp and both published shaft-count options. Warp stripes follow Figure 1; weft color stripes follow Figure 4, with each color stripe repeated three times and alternated with half-bleached linen. Use the source beat adjustments to square the differing linen yarns.',variant=v,colors=palette,warp=list(reversed(warp)),weft=weft,thickness=[.8,1,1,1,1,1,1,1,1])

    p=page(43)
    th=circle_threading(p,343.63,538.17,12,4,reps=repeats(p,'x',(340,520,452,538)))[::-1]
    tu=tieup(p,451.63,538.17,6,4)
    picks=treadling(p,451.63,574.17,6,9)
    add(39,'Cherry Blossom Scarf','Yvonne Ellsworth','Plain weave and doubleweave',th,picks,tu,'Published 180-heddle mohair threading with plain-weave side panels and a doubleweave center. The doubled selvedge ends and denting groups are source loom instructions; this chart retains one assignment per heddle. The nine displayed picks repeat for 66 inches.')

    # The accompanying design article spells out a separate numeric example,
    # and explicitly directs the reader to use the table-linens tie-up.
    outline=[6,6,6,5,6,6,5]
    th=[]
    for i,s in enumerate(outline):
        th += [(a,'#f2ede2') for a in ([1,2,1,2] if i%2==0 else [3,4,3,4])]+[(s,'#31425e')]
    picks=[]
    for i,t in enumerate([5,6,6,5,5]):
        picks += [(a-1,'#f2ede2') for a in ([1,2,1,2] if i%2==0 else [3,4,3,4])]+[(t-1,'#31425e')]
    tu=[[s for s in shed if s<=6] for shed in tieup(page(48),386.12,236.02,6,8)]
    add(41,'Create Sashiko Weaving Drafts with Ease - Worked Example','Mary McConnell','Plain weave with supplemental warp and weft',th,picks,tu,'The article’s complete 35-end threading and 25-pick treadling example, transcribed from its spelled-out numeric sequences. It uses the Sashiko Trails tie-up as directed, reduced to the six shafts this example needs. Monochrome ground and outline colors are illustrative; the article does not specify yarn colors for this example.',shafts=6)

    # Sashiko Trails placemats: four individual treadling variations.
    p=page(48)
    th=circle_threading(p,62.12,236.02,36,8,reps=repeats(p,'x',(60,212,386,236)))[::-1]
    assert len(th)==236
    tu=tieup(p,386.12,236.02,6,8)
    for v,x,y,rows,rx in [(1,386.12,308.02,19,480),(2,386.12,479.02,26,480),(3,251.12,326.02,37,345),(4,116.12,326.02,37,210)]:
        rr=repeats(p,'y',(x+54,y,rx,y+rows*9))
        picks=treadling(p,x,y,6,rows,reps=rr)
        add(44,f'Sashiko Trails Table Linens - Placemat {v}','Mary McConnell','Plain weave with supplemental warp and weft',th,picks,tu,'Full 236-end placemat threading with the separately printed sashiko treadling. All numbered brackets are expanded. Hem and border shed pairs marked only in inches are shown once; repeat them to the source length. Four Alabaster ground picks alternate with one Peach Harvest supplementary pattern pick.',variant=v)

    # The runner has five successive panels on a narrower threading.
    p=page(49)
    th=circle_threading(p,160.76,117.04,30,8,reps=repeats(p,'x',(159,95,431,117)))[::-1]
    assert len(th)==166
    tu=tieup(p,430.76,117.04,6,8)
    picks=[]
    for x,y,rows,right in [(430.76,189.04,44,527),(304.76,216.04,32,402)]:
        rr=repeats(p,'y',(x+54,y,right,y+rows*9))
        picks+=treadling(p,x,y,6,rows,reps=rr)
    add(45,'Sashiko Trails Table Linens - Five-panel Runner','Mary McConnell','Plain weave with supplemental warp and weft',th,picks,tu,'Complete 166-end runner threading and all five sashiko panels in their printed order. Numeric repeat brackets are expanded. Hem and border pairs specified only in inches are represented once; repeat those pairs to the source length. The source runner is about 58 inches long.')

    p=page(54)
    a=circle_threading(p,202.12,125.54,24,4,reps=repeats(p,'x',(200,95,428,125)))
    b=circle_threading(p,238.12,206.54,19,4,reps=repeats(p,'x',(229,185,410,206)))
    th=a[::-1]+b[::-1];assert len(th)==413
    tu=tieup(p,427.12,125.54,5,4)
    rr=repeats(p,'y',(472,161,495,432))
    picks=slash_treadling(p,427.12,161.54,5,30,reps=rr)
    add(50,'Sugar Plum Lace Scarf','Susan Du Bois; woven by Robin Wilton','Swedish lace',th,picks,tu,'Complete 413-heddle threading (the two unthreaded floating selvedges are not included), with the 82-pick Swedish-lace repeat and the displayed starting and ending plain-weave picks. As printed, this rising-shed version shows warp floats on the upper face; the source derives it from Johann D’s Lace #32 in Davison.')

    # Canvas-weave threading has an outer 2x bracket continued onto row two.
    p=page(58)
    ra=repeats(p,'x',(35,200,461,225));ra=[r for r in ra if r[2]!=2 or abs(r[1]-r[0])<200]
    rb=repeats(p,'x',(55,282,443,297))
    a=circle_threading(p,37.64,225.5,46,4)
    b=circle_threading(p,64.64,297.5,42,4)
    left=expand(a[:32],[r for r in ra if r[1]<326],37.64,9)
    right=expand(a[32:],[r for r in ra if r[0]>325],325.64,9)
    bottom_right=expand(b[2:],[r for r in rb if r[0]>82],82.64,9)
    bottom_left=expand(b[:2],[r for r in rb if r[0]<82],64.64,9)
    th=right[::-1]+(left[::-1]+bottom_right[::-1])*2+bottom_left[::-1]
    assert len(th)==268,len(th)
    tu=tieup(p,460.64,225.5,4,4)
    rp=repeats(p,'y',(496.64,261.5,527,729.5))
    pk=treadling(p,460.64,261.5,4,52,reps=rp)
    add(54,'Shades of Flax Towels - Towel 1','Dana Lutz','Canvas weave and plain weave with color-and-weave',th,pk,tu,'Full 268-heddle colored canvas-weave threading and Towel 1 treadling, with the six printed 12x sections expanded. The floating selvedges remain loom instructions. Hem pairs marked only in inches are shown once; extend them to the printed length.',variant=1)
    def piece(x,y,rows,right,skiptop=False):
        r=repeats(p,'y',(x+36,y+(10 if skiptop else 0),right,y+rows*9))
        return treadling(p,x,y,4,rows),r
    a,ra=piece(370.64,414.5,35,448)
    b,rb=piece(289.64,414.5,26,369,True)
    ra=[r for r in ra if r[2]!=3]
    pk=a[:3]+(expand(a[3:],ra,441.5,9)+expand(b[:24],[r for r in rb if r[1]<=630.6],414.5,9))*3+b[24:]
    add(54,'Shades of Flax Towels - Towel 2','Dana Lutz','Canvas weave and plain weave with color-and-weave',th,pk,tu,'Full 268-heddle colored threading and Towel 2, including its continued outer 3x treadling bracket. Numeric repeats are expanded across both printed columns. The inch-marked hems are represented by their shown shed pairs.',variant=2)
    a,ra=piece(190.64,414.5,34,252)
    # Towel 3's two blank separator rows are not picks.
    b=treadling(p,109.64,414.5,4,25)
    rb=repeats(p,'y',(145.64,425,188,639.5))
    ra=[r for r in ra if not(r[2]==2 and r[1]-r[0]>200)]
    front=expand(a[2:],ra,432.5,9)
    whole=expand(b,rb,414.5,9)
    partial=expand(b[:19],[r for r in rb if r[1]<=585.6],414.5,9)
    ending=treadling(p,109.64,657.5,4,2)
    pk=a[:2]+front+whole+front+partial+ending
    add(54,'Shades of Flax Towels - Towel 3','Dana Lutz','Canvas weave and plain weave with color-and-weave',th,pk,tu,'Full 268-heddle colored threading and Towel 3, including the continued outer 2x bracket and the second-repeat jump to the final hem. Numeric repeats are expanded. Length-only hem and stripe pairs are represented once; use the printed inch lengths at the loom.',variant=3)

    # Mosaic Tiles: 6 motifs plus a Navy balance end. The 6x threading
    # bracket continues through seven ends on its second printed row.
    p=page(62)
    ra=repeats(p,'x',(44,185,380,209));ra=[r for r in ra if r[2]!=6]
    a=circle_threading(p,46.68,209.88,36,8,reps=ra)[::-1]
    b=circle_threading(p,55.68,308.88,8,8)[::-1]
    th=(a+b[:-1])*6+b[-1:]
    assert len(th)==277
    tu=tieup(p,379.68,209.88,10,8)
    rr=repeats(p,'y',(469.68,281.88,491,713.88))
    raw=treadling(p,379.68,281.88,10,48)
    # Pattern repeat has a single Navy balance pick outside its brackets.
    unit=expand(raw[2:45],[r for r in rr if 300<r[0]<690],299.88,9)
    assert len(unit)==46,len(unit)
    palette=['#243052','#625c8d','#eed35a','#b59a78','#d2a2a0','#a89bc5','#be6797']
    wc=[]
    for c in [6,5,4,3,2,1]:wc += [0]+[c]*45
    wc += [0]
    weft=[0]*4
    for c in [1,2,3,4,5,6]*8+[1,2]:weft += [0]+[c]*45
    weft += [0]*5
    patt=(unit*50)+raw[45:46]
    picks=expand(raw[:2],[r for r in rr if r[1]<300],281.88,9)+patt+expand(raw[46:],[r for r in rr if r[0]>690],695.88,9)
    assert len(weft)==len(picks),(len(weft),len(picks))
    add(58,'Mosaic Tiles Scarf','Eileen Lee','Twill',th,picks,tu,'Full 277-heddle threading and the complete colored-weft order from Figures 1–3. The threading bracket continues through the second row; the source adds separate floating selvedges. Eight cycles of the six 45-pick colors are followed by Blue Purple and Lemon Drop, with single Navy dividing picks and four-pick plain-weave ends.',colors=palette,warp=list(reversed(wc)),weft=weft)

    # City Circuits: initial section, six center motifs with the published
    # shortened last repeat, balance, and ending section.
    p=page(79)
    a=circle_threading(p,51.5,126,38,8,reps=repeats(p,'x',(50,95,394,126)))
    b=circle_threading(p,159.5,234,24,8,reps=repeats(p,'x',(158,205,376,234)))
    th=a[::-1]+b[::-1];assert len(th)==504
    tu=tieup(p,393.5,126,10,8)
    first=treadling(p,393.5,198,10,55,reps=repeats(p,'y',(483.5,198,513,693)))
    rr=repeats(p,'y',(312.5,333,365,720));rr=[r for r in rr if r[2]!=6]
    center=treadling(p,222.5,333,10,32,reps=[r for r in rr if r[1]<=621])
    short=treadling(p,222.5,333,10,30,reps=[r for r in rr if r[1]<=603])
    balance=treadling(p,222.5,630,10,10,reps=[r for r in rr if r[0]>=630])
    final=treadling(p,51.5,315,10,45,reps=repeats(p,'y',(141.5,315,180,720)))
    picks=first+center*5+short+balance+final
    def citycolor(c):return '#d67a9e' if c=='#fe52f8' else '#167b85'
    th=[(s,citycolor(c)) for s,c in th]
    picks=[(s,citycolor(c)) for s,c in picks]
    add(75,'City Circuits Scarf','Kate Lange-McKibben','Deflected doubleweave',th,picks,tu,'Full 504-end threading and complete initial, center, balance, and ending sections. Nested numeric brackets are expanded. The center motif is woven six times; the last repeat skips its final treadling block as printed. English Rose and Teal have independent layer selvedges; correct shuttle routing and a soft beat are essential. The flat draft cannot show the relaxation of the finished deflected doubleweave.')

    # Peach Harvest is a multicolored yarn represented by a striped marker;
    # use a blended peach-gold for its editable single-color approximation.
    for pat in PATTERNS:
        if 'Sashiko Trails' in pat['title']:
            pat['colors']=['#c8b06e' if c=='#000000' else c for c in pat['colors']]

    return PATTERNS

if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='render':
        for n in map(int,sys.argv[2:]):page(n).to_image(resolution=130).save(SCRATCH/f'p{n}.png')
    else:
        patterns=extract()
        target=ROOT/'tools/handwoven-2025-ii-spring.json'
        target.write_text(json.dumps([dict(id='handwoven-2025-ii-spring',patterns=patterns)],indent=2)+'\n')
        print(json.dumps(dict(patterns=len(patterns),sizes=[(p['title'],len(p['threading']),len(p['lifts'])) for p in patterns])))
