"""Transcribe Winter 2025's printed drafts; geometry is in PDF points.

Numbered repeats are expanded. Length-only spans use a complete design unit;
the descriptions retain their measured lengths rather than inventing pick counts.
"""
import importlib
import json
from pathlib import Path
from collections import defaultdict, Counter
from pypdf import PdfReader
from PIL import Image

src=importlib.import_module('extract-handwoven-2025-i-winter')
ISSUE='handwoven-2025-i-winter'
patterns=[]

def lift(tie, treadling):
    return [sorted({s for t in ([row] if isinstance(row,int) else row) for s in tie[t-1]}) for row in treadling]

def add(page, title, designer, kind, shafts, threading, tie, treadling, description, **extra):
    serial=1+sum(p['id'].startswith(f'hw-2025-i-winter-p{page:02d}-') for p in patterns)
    entry=dict(id=f'hw-2025-i-winter-p{page:02d}-s{serial:02d}',title=title,designer=designer,
        pages=extra.pop('pages',str(page)),kind=kind,description=description,shafts=shafts,
        threading=threading,lifts=lift(tie,treadling),**extra)
    patterns.append(entry)
    return entry

def expand_rows(rows, rules):
    """Repeat the specified half-open source row ranges, from right to left."""
    for start,end,count in sorted(rules,reverse=True): rows=rows[:start]+rows[start:end]*count+rows[end:]
    return rows

def marked(page,box,cols,sizes=(6,),step=9):
    rows=defaultdict(set)
    for size in sizes:
        for r,c,color in src.squares(page,box,cols,step=step,size=size): rows[r].add(c)
    return [sorted(v) for r,v in sorted(rows.items())]

def numeric_marks(page,box,cols,step=9):
    return src.treadles(page,box,cols,step)

def colored_marks(page,box,cols,step=9):
    """Source square marks with exact treadle and CMYK color, one entry per row."""
    result={}
    for obj in page.rects:
        if src.inside(obj,box) and 3.8<obj['width']<6.4 and abs(obj['width']-obj['height'])<.05:
            x,y=(obj['x0']+obj['x1'])/2,(obj['top']+obj['bottom'])/2
            r=int((y-box[1])/step);c=int((x-box[0])/step)+1
            result[r]=(c,cmhex(obj['non_stroking_color']))
    return [result[r] for r in sorted(result)]

def cmhex(color):
    if len(color)==4:
        c,m,y,k=color; rgb=[round(255*(1-v)*(1-k)) for v in (c,m,y)]
    else: rgb=[round(255*v) for v in color]
    return '#'+''.join(f'{v:02x}' for v in rgb)

def dot_segments(page,box,shafts,repeats):
    data=src.dots(page,box,shafts)
    for start,end,count in sorted(repeats,reverse=True): data=data[:start]+data[start:end]*count+data[end:]
    palette=[];colors=[]
    for shaft,color in data:
        value=cmhex(color)
        if value not in palette:palette.append(value)
        colors.append(palette.index(value))
    return [d[0] for d in data],palette,colors

def color_order(page,box,rowmap,repeats=()):
    tokens=[]
    for w in page.within_bbox(box).extract_words():
        if w['text'].isdigit():
            row=int(((w['top']+w['bottom'])/2-box[1])/9)
            tokens.append(((w['x0']+w['x1'])/2,rowmap[row],int(w['text'])))
    tokens.sort(reverse=True)
    ranges=[]
    for left,right,count in repeats:
        indices=[i for i,(x,c,n) in enumerate(tokens) if left<x<right]
        ranges.append((min(indices),max(indices)+1,count))
    tokens=expand_rows(tokens,ranges)
    return [c for x,c,n in tokens for _ in range(n)]

def raster_assignment(image,box,cols,rows,axis):
    """Read the occupied chart row/column, excluding gray grid rules."""
    image=image.convert('L');x0,y0,x1,y1=box
    xs=[round(x0+i*(x1-x0)/cols) for i in range(cols+1)]
    ys=[round(y0+i*(y1-y0)/rows) for i in range(rows+1)]
    scores={}
    for y in range(rows):
        for x in range(cols):
            values=image.crop((xs[x]+1,ys[y]+1,xs[x+1],ys[y+1])).getdata()
            scores[x,y]=sum(255-v for v in values if v<210)
    if axis=='thread': return [rows-max(range(rows),key=lambda y:scores[x,y]) for x in range(cols)]
    return [max(range(cols),key=lambda x:scores[x,y])+1 for y in range(rows)]

def small_raster_assignment(image,box,cols,rows,axis):
    """Subpixel sampling preserves the tiny numerals of Figure 5."""
    image=image.convert('L').resize((cols*12,rows*12),Image.Resampling.BICUBIC,box=box)
    scores={}
    for row in range(rows):
        for col in range(cols):
            values=image.crop((col*12+3,row*12+3,col*12+9,row*12+9)).getdata()
            scores[col,row]=sum(255-v for v in values)
    if axis=='thread':return [rows-max(range(rows),key=lambda r:scores[c,r]) for c in range(cols)]
    return [max(range(cols),key=lambda c:scores[c,r])+1 for r in range(rows)]

with src.pdfplumber.open(src.SOURCE) as pdf:
    page=lambda n:pdf.pages[n-1]
    twill4=[[1,2],[2,3],[3,4],[1,4]]
    shadow=src.dots(page(19),(89,82,458,118),4)+src.dots(page(19),(89,136,440,172),4)
    thread=[s for s,c in shadow]
    first=marked(page(19),(458.2,118,494.2,496),4)
    cont=marked(page(19),(395.2,190,431.2,532),4)
    common=dict(colors=['#28758b','#fffbe9'],warpColors=[i%2 for i in range(80)])
    add(14,'Star of Bethlehem - Shadow Weave','Tom Knisely','Shadow weave',4,thread,twill4,first+cont,
        'The complete 80-end and 80-pick shadow-weave version in Figure 1, including the continuation. Light and dark 5/2 cotton alternate in both directions; 16 epi. Complementary incidentals adapt the overshot design to shadow weave.',pages='14-15',weftColors=[i%2 for i in range(80)],**common)
    rep=marked(page(20),(464,133,500,548),4,sizes=(6,4.5))
    rep=expand_rows(rep,[(8,10,3),(10,12,3),(12,14,3),(14,16,3),(22,24,2),(30,32,3),(32,34,3),(34,36,3),(36,38,3)])
    add(16,'Star of Bethlehem - Rep Weave','Tom Knisely','Warp-faced rep weave',4,thread,twill4,rep,
        'Figure 2 uses the same 80-end threading as the shadow-weave study, resleyed to 32 epi. All numbered treadling brackets are expanded. Thick teal cotton alternates with fine 10/2 natural weft. The ordinary drawdown shows the interlacements; the close warp sett produces the rep effect.',colors=['#28758b','#fffbe9','#28758b','#fffbe9'],warpColors=[i%2 for i in range(80)],weftColors=[2+i%2 for i in range(len(rep))],thickness=[1,1,2,0.6])
    comp=marked(page(20),(132,345,186,724),6)+marked(page(20),(51,345,105,688),6)
    add(16,'Star of Bethlehem - Complementary Plain Weave','Tom Knisely','Complementary plain weave / double-faced cloth',4,thread,
        [[1,3],[2,4],[1],[2],[3],[4]],comp,
        'Figure 3 reties the original 80-end color-and-weave threading and changes the treadling to create double-faced cloth. Both the main treadling and its continuation are included. Teal and natural 5/2 cotton alternate in warp and weft.',weftColors=[i%2 for i in range(len(comp))],**common)
    opposites=marked(page(21),(432,274,486,724),6)
    opposites=expand_rows(opposites,[(10,12,3),(12,14,3),(14,16,3),(16,18,3),(34,36,3),(36,38,3),(38,40,3),(40,42,3)])
    add(17,'Star of Bethlehem - Woven on Opposites','Tom Knisely','Weft-faced twill on opposites',4,[s for s,c in shadow[::2]]*2,
        twill4+[[1,3],[2,4]],opposites,
        'Figure 4: two repeats of the 40-end Star of Bethlehem pattern, without the shadow incidentals, are threaded in 8/4 cotton at 8 epi. Contrasting teal and ecru worsted cotton alternate in the weft. Includes the two plain-weave header picks and every numbered treadling repeat. Floating selvedges are not heddled.',colors=['#28758b','#fffbe9'],weftColors=[i%2 for i in range(len(opposites))])

    # Rebecca Winter supplies complete diagrams as raster images rather than PDF glyphs.
    reader=PdfReader(src.SOURCE)
    image=reader.pages[31].images[1].image
    rwthread=raster_assignment(image,(11,35,518,127),44,8,'thread')[::-1]
    rwtr=raster_assignment(image,(529,139,621,645),8,44,'tread')
    # Powell's turning-point ties interrupt the apparent checkerboard on each
    # paired block diagonal; retain those essential non-tabby ties.
    checker=[[1,3,5,7],[2,4,6,8],[2,3,5,7],[1,4,6,8],[2,4,5,7],[1,3,6,8],[2,4,6,7],[1,3,5,8]]
    add(28,'Daily Drafts - October 3, 2024','Rebecca Winter','Powell-method shadow weave',8,rwthread,checker,rwtr,
        'Figure 3 is the full 44-end, 44-pick shadow-weave draft developed from Figure 2. Dark and light yarns alternate, with turning-point incidentals as drawn. This is the complete numerical draft, not the adjacent profile draft.',colors=['#008064','#fffdf7'],warpColors=[i%2 for i in range(44)],weftColors=[i%2 for i in range(44)])
    image=reader.pages[32].images[0].image
    rwthread=small_raster_assignment(image,(2.7,10.9,600,32.6),220,8,'thread')[::-1]
    rwtr=small_raster_assignment(image,(602.5,35.3,624.2,632.6),8,220,'tread')
    assert rwthread[:110]==rwthread[110:] and rwtr[:110]==rwtr[110:]
    add(29,'Daily Drafts - October 18, 2024','Rebecca Winter','Powell-method shadow weave',8,rwthread,checker,rwtr,
        'Figure 5 is the complete 220-end, 220-pick shadow-weave draft, directly transcribed from the printed diagram. It includes two identical 110-end and 110-pick repeats and all turning-point incidentals omitted from the adjacent profile. The color sequence begins with a light weft pick; the first threading end, read from the right, is dark.',colors=['#008064','#fffdf7'],warpColors=[i%2 for i in range(220)],weftColors=[1-i%2 for i in range(220)])

    tie=src.tieup(page(38),(340,251,394,323),6)
    magicthread=[1,2,3,4]*22+[5,6,7,8]*4+[1,2,3,4]*22
    wc=color_order(page(38),(170,119.04,434,174.04),list(range(6)),[(235.82,253.82,2),(352.82,370.82,2)])
    assert len(wc)==192, len(wc)
    assert Counter(wc)==Counter({0:46,1:36,2:16,3:12,4:44,5:38})
    color_runs={}
    for w in page(38).within_bbox((431.94,289.426,467.94,633)).extract_words():
        if w['text'].isdigit() and 1<=int(w['text'])<=4:
            row=round((w['top']-291.64)/9)
            col=int(((w['x0']+w['x1'])/2-431.94)/12)
            color_runs[row]=([0,3,1][col],int(w['text']))
    color_runs[14]=(1,4);color_runs[23]=(0,4)
    color_runs=expand_rows([color_runs[r] for r in sorted(color_runs)],[(15,17,2),(20,22,2)])
    weft=[c for c,n in color_runs for _ in range(n)]
    add(32,'Magic Ruffles Scarf','Jennifer Sargent','Twill and basketweave',8,magicthread,tie,[1,2,3,4]*(len(weft)//4)+list(range(1,len(weft)%4+1)),
        'Figure 2: the 22x, 4x, and 22x threading brackets give 192 heddled ends; the central merino wool basketweave strip shrinks during finishing. The color-transition study follows Figure 3; sections marked 42 inches are represented by one four-pick twill unit. Wet-finishing, rather than the flat drawdown, creates the ruffles.',pages='32-34',colors=['#e86230','#111549','#a5d53a','#63b838','#933c30','#526cad'],warpColors=wc,weftColors=weft,thickness=[1,1,0.65,1,1,1])

    monkthread=([4,3]*3+[2,1]*3)*30+[4,3]*3
    mtie=[[1,2],[3,4],[1,3],[2,4]]
    garden_palette=['#99b2cc','#283a89','#cddc63','#8f962e','#fffbe9','#a389bd','#6d8eac','#fffbe9']
    garden_base=dict(colors=garden_palette,pages='36-39')
    def tabby_pattern(picks,colors):
        ts=[];cs=[]
        for i,(t,c) in enumerate(zip(picks,colors)):
            ts.extend([t,3+i%2]);cs.extend([c,0])
        return ts,cs
    border=[3,4]+[3,4]*2+[3,2,4,2]*2+[3,1,4,1]*2+[3,2,4,2]*2+[3,4]*2+[4,3]
    borderc=[1,1]+[0]*4+[0,2,0,2]*2+[0,3,0,3]*2+[0,1,0,1]*2+[0]*4+[1,1]
    t1body,c1body=tabby_pattern([2]*2+[1]*2+[2]*2,[1]*2+[1]*2+[1]*2)
    add(36,'Garden Path Towels - Towel 1','Malynda Allen','Monk\'s belt',4,monkthread,mtie,[3,4]*2+border+t1body+border+[3,4]*2,
        'Towel 1: 366 Natural heddled warp ends. The complete colored border, including its continuation, surrounds a plain-weave body unit. The numbered 2x brackets are expanded. Plain-weave hems and the 18-inch body are woven to measured length. Tabby is explicit, not inserted a second time.',warpColors=[4]*366,weftColors=[0]*4+borderc+c1body+borderc+[0]*4,**garden_base)
    t2body,c2body=tabby_pattern([2,1,2,1,2,1,2,1,2,1,2,1,2,1],[3]*14)
    add(36,'Garden Path Towels - Towel 2','Malynda Allen','Monk\'s belt',4,monkthread,mtie,[3,4]*2+border+t2body+border[::-1]+[3,4]*2,
        'Towel 2: the same Natural monk\'s-belt warp, with the printed Royal and Sage patterning, the numbered 2-2-3-3-4-4-5-5-4-4-3-3-2-2 pattern-pick sequence, and the border woven in reverse. Heather tabby alternates after every pattern pick. The measured-length center is represented by its design unit.',warpColors=[4]*366,weftColors=[0]*4+borderc+c2body+borderc[::-1]+[0]*4,**garden_base)
    # Replace each numbered pattern-pick count by that many repetitions, with tabby.
    counts=[2,2,3,3,4,4,5,5,4,4,3,3,2,2]
    t2,c2=tabby_pattern([2 if i%2==0 else 1 for i,n in enumerate(counts) for _ in range(n)],[3]*sum(counts))
    patterns[-1]['lifts']=lift(mtie,[3,4]*2+border+t2+border[::-1]+[3,4]*2)
    patterns[-1]['weftColors']=[0]*4+borderc+c2+borderc[::-1]+[0]*4
    a,ac=tabby_pattern([2]*6+[1]*4+[2]*6,[1]*6+[3]*4+[1]*6)
    b,bc=tabby_pattern([1]*2+[2]*7+[1]*2,[1]*2+[3]*7+[1]*2)
    t3=[3,4]*2+a+[3,4]*6+b*39+[3,4]*6+a+[3,4]*2
    c3=[0]*4+ac+[7]*12+bc*39+[7]*12+ac+[0]*4
    add(36,'Garden Path Towels - Towel 3','Malynda Allen','Monk\'s belt with plain-weave stripes',4,monkthread,mtie,t3,
        'Towel 3 expands the 6-4-6 pattern-pick border, six plain-weave pairs, and 39 repeats of the 2-7-2 pattern-pick body. Tabby is included explicitly in Heather; the plain-weave stripes use Natural. Hems are woven to 1.5 inches.',warpColors=[0]*366,weftColors=c3,**garden_base)
    t4tie=[[2],[1,4],[4],[2,3],[1,3],[2,4]]
    t4unit=[4,3,2,1]*2+[4,5,6,5]*2
    t4=[6,5]*2+t4unit*4+t4unit*2+t4unit*4+[4,3,2,1]*4+[6,5]*2
    add(36,'Garden Path Towels - Towel 4','Malynda Allen','Twill and plain-weave stripes',4,monkthread,t4tie,t4,
        'Towel 4 uses the printed six-treadle tie-up and no tabby. All 2x and 4x treadling brackets are expanded; the body marked 25.75 inches is represented by its complete two-part unit. The issue deliberately weaves this towel wrong side up; invert the tie-up to view the face on a rising-shed loom.',warpColors=[0]*366,weftColors=[5]*len(t4),**garden_base)
    t5tie=[[2],[1],[4],[3],[1,3],[2,4]]
    t5cell=([6,5,3,4]*2+[6,5,1,2]*2+[5,6]*2+[3,4]*2+[5,6]*2+[3,4]*2)
    t5=[6,5]*2+t5cell*18+[6,5]*2
    add(36,'Garden Path Towels - Towel 5','Malynda Allen','Honeycomb',4,monkthread,t5tie,t5,
        'Towel 5 uses its printed six-treadle honeycomb tie-up without added tabby. The 18x bracket and inner 2x brackets are expanded. Natural ground weft, Sage outlines, and Carolina Blue details form the cells. Wet-finishing creates the texture; the printed tie-up shows the reverse on a rising-shed loom.',warpColors=[4]*366,weftColors=([4]*4+([3,3,6,6]*2+[3,3,4,4]*2+[4]*4+[4]*4+[4]*4+[4]*4)*18+[4]*4),**garden_base)

    # The colored squares distinguish thick pattern yarn, fine tabby, and the two
    # natural yarns. Read them directly rather than infer color from the treadle.
    garden_source=[cmhex(c) for c in [(.249,.181,0,0),(.875,.816,0,0),(.208,0,.691,0),(.416,0,1,0),(.002,.007,.085,0),(.566,.67,0,0),(.607,.453,0,0),(.001,.007,.078,0)]]
    def garden_colors(rows):
        def rgb(h):return tuple(int(h[i:i+2],16) for i in (1,3,5))
        return [min(range(8),key=lambda i:sum((a-b)**2 for a,b in zip(rgb(h),rgb(garden_source[i])))) for t,h in rows]
    def replace_garden(number,rows,tie):
        entry=next(p for p in patterns if p['title']==f'Garden Path Towels - Towel {number}')
        entry['lifts']=lift(tie,[t for t,h in rows]);entry['weftColors']=garden_colors(rows)
    g1=colored_marks(page(42),(452,290.57,488,722.57),4)
    g1cont=colored_marks(page(42),(380,308.57,416.5,560.57),4)
    g1border=expand_rows(g1[2:48],[(a-2,b-2,2) for a,b in [(4,6),(10,12),(16,18),(22,24),(27,29),(33,35),(39,41),(45,47)]])
    g1border+=expand_rows(g1cont[:25],[(2,4,2),(8,10,2),(14,16,2),(20,22,2)])
    g1body=[(3,garden_source[0]),(4,garden_source[0])]
    replace_garden(1,g1[:2]+g1border+g1body+g1border+g1[:2],mtie)
    g2=colored_marks(page(43),(119,290.57,155,650.57),4)
    g2border=expand_rows(g2[2:26],[(2,4,2),(16,18,2),(21,23,2)])
    g2body=[(t,garden_source[2 if c==3 else c]) for t,c in zip(t2,c2)]
    replace_garden(2,g2[:2]+g2border+g2body+g2border[::-1]+g2[:2],mtie)
    g4=colored_marks(page(43),(314.75,292.145,370.26,615.95),6,step=9.2515)
    g4first=(g4[2:4]*2+g4[4:6]*2)*4+g4[6:8]*2+(g4[8:10]*2+g4[10:11]+g4[11:13]*2+g4[13:15]*2+g4[15:17]*2)*2
    g4body=g4[17:19]*2+g4[19:20]+g4[20:22]*2+g4[22:24]*2+g4[24:26]*2
    g4end=(g4[26:28]*2+g4[28:30]*2)*4
    replace_garden(4,g4[:2]+g4first+g4body+g4first+g4end+g4[30:32],t4tie)
    g5=colored_marks(page(43),(430.895,292.145,486.405,532.69),6,step=9.2515)
    g5cell=g5[2:4]+g5[4:6]*2+g5[6:8]+(g5[8:10]*2+g5[10:12]+g5[12:14]*2+g5[14:16]+g5[16:18]*2)*2+g5[18:20]+g5[20:22]*2+g5[22:24]
    replace_garden(5,g5[:2]+g5cell*18+g5[24:26],t5tie)
    for entry in patterns:
        if entry['title'].startswith('Garden Path Towels'):
            entry['warpColors']=[4]*366
    garden3=next(p for p in patterns if p['title']=='Garden Path Towels - Towel 3')
    garden3['weftColors']=[2 if c==3 else c for c in garden3['weftColors']]

    main=src.numbers(page(48),(61,328,376,400));cont=src.numbers(page(48),(250,445,367,517))
    overshotthread=(main+cont[:9])*4+cont[9:]
    assert len(overshotthread)==179
    otie=src.tieup(page(48),(385,328,475,400),10)
    opicks=[3]*2+[4]*2+[5]*4+[6]*8+[7]*8+[8]*4+[9]*2+[10]*2
    tr=[];cs=[]
    for i,t in enumerate(opicks):tr += [t,1+i%2];cs += [1,0]
    add(42,'Misty Mountains Runner','Dana Lutz','Overshot',8,overshotthread,otie,[1,2]*2+tr+[1,2]*2,
        'Figure 1 expands the 4x threading bracket across the main line and the first nine ends of the continuation, then adds the three final ends: 179 heddled ends. All 32 pattern picks are included with alternating Naturel tabby. The yarn is a slowly changing gradient; one teal shade represents the supplementary weft here. Border lengths are woven to measure.',pages='42-45',colors=['#fffbe9','#76c2bf'],thickness=[1,2.5],warpColors=[0]*179,weftColors=[0]*4+cs+[0]*4)

    stie=src.tieup(page(52),(371.625,191,461.625,263),10)
    straw=numeric_marks(page(52),(371.625,263,461.625,731),10)
    tube=straw[:8];exchange=straw[8:24];layers=straw[24:28]
    spicks=tube+exchange*2+layers*2+exchange*2+tube+exchange*5+tube
    # Color order Figure 1, read right to left. Royal's 64/34/6 ends are not repeated.
    swarp=color_order(page(52),(238,92,410,130),[3,1,2,0],[(382.76,400.76,32),(364.76,382.76,4),(346.76,364.76,16),(328.76,346.76,4),(310.76,328.76,12),(283.76,301.76,4),(265.76,283.76,12),(247.76,265.76,4)])
    assert len(swarp)==280,len(swarp)
    scolors=['#214b9d','#2ba0b6','#ce4d92','#edc72c','#112343']
    shared=dict(pages='46-49',colors=scolors,warpColors=swarp)
    add(46,'Secret Passage Scarf - Eight Shafts','Marcia Toms','Doubleweave with pebble weave',8,list(range(8,0,-1))*35,stie,spicks,
        'Figure 2 expands the 35x straight threading and all numbered 2x/5x layer-exchange repeats. Complete tube, layer-exchange, and two-layer units are included; sections labeled 17.5, 31, or 4 inches use one unit rather than an invented pick count. Red marks use the second shuttle for the bottom layer. The 4-inch two-layer section forms a tunnel.',weftColors=[4]*len(spicks),**shared)
    fourtie=src.tieup(page(53),(82,196,136,232),6)
    tube4=[[1],[2,5],[3],[4,5]];exchange4=[[1,6],[2],[3,6],[4]]*2+tube4*2
    layers4=tube4
    fpicks=tube4+exchange4*2+layers4*2+exchange4*2+tube4+exchange4*5+tube4
    add(46,'Secret Passage Scarf - Four Shafts, Six Treadles','Marcia Toms','Doubleweave with plain weave',4,[4,3,2,1]*70,fourtie,fpicks,
        'Figure 3 uses 70 repeats of the four-shaft threading and a skeleton tie-up requiring at most two treadles together. Tube, exchange, and separate-layer sections correspond to the eight-shaft project, but use plain weave. All numbered 2x/5x brackets are expanded; measured-length sections use a design unit. Two shuttles keep the tunnel layers separate.',weftColors=[4]*len(fpicks),**shared)
    eighttie=[[1],[1,2,3],[3],[1,3,4],[1,2,4],[2],[2,3,4],[4]]
    # Eight-treadle notation has exactly the same sheds as the six-treadle version.
    mapping={tuple(x):i+1 for i,x in enumerate(eighttie)}
    alt=[mapping[tuple(s)] for s in lift(fourtie,fpicks)]
    add(46,'Secret Passage Scarf - Four Shafts, Eight Treadles','Marcia Toms','Doubleweave with plain weave',4,[4,3,2,1]*70,eighttie,alt,
        'The alternative eight-treadle tie-up in Figure 3 produces the same sheds as the six-treadle skeleton notation, with one treadle per pick. The expanded tube, layer-exchange, and two-layer units are retained for direct comparison. Use a second shuttle in the separate-layer tunnel.',weftColors=[4]*len(alt),**shared)

    wtie=src.tieup(page(56),(393,250,456,313),7)
    wafflethread=[7,6,5,4,3,2,1,2,3,4,5,6]*42
    waffletr=[1,2,3,4,5,6,7,6,5,4,3,2]
    wp=([1]*12+[2]*12+[1]*12+[0]*24)*8+[0]*24
    assert len(wp)==504
    for name,warpc,weftc in [('Plaid',wp,[0]*24+[1]*12+[2]*12+[1]*12+[0]*24),('Striped',[0]*504,[0]*12+[3]*12+[2]*12+[1]*12),('Variegated',[0]*504,[3]*48)]:
        add(50,f'Blueberry Waffle Towels - {name}','Claudia Tokola','Seven-shaft waffle weave',7,wafflethread,wtie,(waffletr*((len(weftc)+11)//12))[:len(weftc)],
            f'Figure 2, {name.lower()} colorway. The 42x point threading is fully expanded to 504 ends. Figure 3 supplies the plaid/striped weft order; the variegated towel uses Blue Jay space-dyed yarn, approximated by one blue shade. Sewing-thread hems and the 32-inch body are woven to measure. Floating selvedges are omitted from the heddled draft.',pages='50-53',colors=['#fffdf6','#36566d','#6f959f','#4089a8'],warpColors=warpc,weftColors=weftc)

    wave,colors,wc=dot_segments(page(60),(206,241,458,277),4,[(i,i+2,5) for i in range(0,26,2)])
    assert len(wave)==130
    if '#ffffff' not in colors:colors.append('#ffffff')
    white=colors.index('#ffffff');colors.append('#20274b');rag=len(colors)-1
    wavetie=src.tieup(page(60),(458.5,241,494.5,277),4)
    # A and B cells: rag pick, then four repeats of the appropriate fine-weft pair.
    atr=[1]+[2,3]*4;btr=[1]+[2,4]*4
    wavetr=[1,2]*2+(atr+btr)*2+atr+[1]+[1,2]*2
    wavewc=[white]*4+([rag]+[white]*8+[rag]+[white]*8)*2+[rag]+[white]*8+[rag]+[white]*4
    add(54,'Making Waves Runner','Andrea Williams','Honeycomb with fabric-strip outlines',4,wave,wavetie,wavetr,
        'Figure 2 expands all thirteen 5x two-end threading brackets to 130 ends. The fine-weft pairs in A and B are repeated four times per cell. Alternate cells for the 38-inch body and finish with an A cell plus an outlining fabric strip. The four-inch plain-weave hems are represented by one pair unit. The outline yarn is thick fabric; its free side fringe is not represented in the drawdown.',pages='54-57',colors=colors,thickness=[1]*(len(colors)-1)+[3],warpColors=wc,weftColors=wavewc)

    dtie=src.tieup(page(65),(345,117,462,261),13)
    main=src.numbers(page(65),(93,117,345,261));dcont=src.numbers(page(65),(183,288,327,432))
    dthread=main[:2]+main[2:]*15+dcont
    assert len(dthread)==408
    dw=color_order(page(64),(125,107,440,164),[5,1,2,3,4,0],[(287.83,431.83,2)])
    dw+=color_order(page(64),(333,188,440,245),[5,1,2,3,4,0])
    assert len(dw)==408,len(dw)
    assert Counter(dw)==Counter({0:36,1:84,2:48,3:96,4:96,5:48})
    dtr=[1,2,3,4,5,6,7,8,9,10,11,12,13,12,11,10,9,8,7,6,5,4,3,2]*24
    for label,shades in [('Blue',['#007787','#248fa4','#6fa6ba','#c0d9e5','#d7e8ec','#a3aeb0']),('Gray',['#161616','#3d3d3d','#646464','#8a8a8a','#ababab','#d0d0d0','#f6f6f0'])]:
        palette=['#35579a','#171717','#cfd2cf','#a0a0a0','#626262','#fffef6']
        # Doubled wefts combine two adjacent colors; blend each pair for the screen.
        pairs=[(0,0),(0,1),(1,1),(1,2),(2,2),(2,3),(3,3),(3,4),(4,4),(4,5),(5,5)] if label=='Blue' else [(0,1),(1,1),(1,2),(2,2),(2,3),(3,3),(3,4),(4,4),(4,5),(5,5),(5,6)]
        shadesrgb=[tuple(int(v[i:i+2],16) for i in (1,3,5)) for v in shades]
        blends=['#'+''.join(f'{round((shadesrgb[a][k]+shadesrgb[b][k])/2):02x}' for k in range(3)) for a,b in pairs]
        start=len(palette);palette+=blends
        weft=[start+i for i in range(11) for _ in range(72 if i in (0,10) else 48)]
        add(58,f'Dicey Dish Towels - {label} Weft','Sheila O’Hara','Fourteen-shaft point twill with plain-weave selvedges',16,dthread,dtie,dtr,
            'Figure 4 expands the 15x point-threading bracket plus both plain-weave edges to 408 doubled heddled ends (816 individual warp threads). The 24-pick point treadling repeats 24 times, giving 576 doubled picks. Figure 2/3 weft blending follows the published 72/48/.../48/72 pick counts; mixed-color doubled yarns are represented by averaged colors. Shafts 15 and 16 weave the plain edges.',pages='58-62',colors=palette,warpColors=dw,weftColors=weft)

    bthread=[5,6]*4+([5,6]*4+[5,6]+[1,2,3,4]*6+[3,2,1,4]*6+[5,6])*4+[5,6]*4+[5,6]*4
    assert len(bthread)==264
    assert Counter(bthread)==Counter({1:48,2:48,3:48,4:48,5:36,6:36})
    btie=src.tieup(page(70),(415,236.5,469,290.5),6)
    base=marked(page(70),(415,290,469,660),6)
    middle=base[13:17]*8+base[17:24]+base[24:28]*8+base[28:35]
    btr=base[:2]*6+base[2:6]*12+base[6:13]+middle*12+base[35:39]*12+base[39:41]*6
    bcolors=[3]*60+[4]*7+([3]*32+[4]*7+[3]*32+[4]*7)*12+[3]*60
    # Color order is independent of the individual twill shafts.
    bwc=[0]*8+([1]*8+[0]*2+[2]*48+[0]*2)*4+[1]*8+[0]*8
    assert len(bwc)==264
    assert Counter(bwc)==Counter({0:32,1:40,2:192})
    add(64,'Birds of a Feather Scarf - Six Shafts','Alison Stewart-Guinee','Twill and plain weave with differential shrinkage',6,bthread,btie,btr,
        'Figure 2: a 264-end warp alternates twill Cloud panels and plain-weave colored bands. The 4x/6x threading and 6x/8x/12x treadling brackets are expanded. Black nonsuperwash wool picks (W) shrink during finishing, ruching the bamboo twill areas; the flat drawdown cannot depict that final texture.',pages='64-67',colors=['#171717','#ec5726','#b8b8b8','#161616','#242424'],warpColors=bwc,weftColors=bcolors,thickness=[1,1,1,1,0.6])
    fourdots=src.dots(page(71),(62,458.5,440,494.5),4)
    # Outer 4x encloses the 6x and 5x brackets, plus three unbracketed cloud ends.
    fthread=[s for s,c in fourdots]
    fthread=fthread[:4]*2+(fthread[4:15]+fthread[15:19]*6+fthread[19:22]+fthread[22:26]*5+fthread[26:28])*4+fthread[28:37]+fthread[37:]*2
    assert len(fthread)==265
    assert Counter(fthread)==Counter({1:70,2:67,3:62,4:66})
    fc=[0]*8+([1]*9+[0]*2+[2]*47+[0]*2)*4+[1]*9+[0]*8
    ftie=src.tieup(page(71),(449,458.5,503,494.5),6)
    add(64,'Birds of a Feather Scarf - Four Shafts','Alison Stewart-Guinee','Twill with differential shrinkage',4,fthread,ftie,btr,
        'Figure 4: the four-shaft twill variation has 265 heddled ends plus two floating selvedges. Figure 3 supplies the 32 Onyx, 45 Persimmon, and 188 Cloud ends. Treadling is the same as the six-shaft version, including the W-marked nonsuperwash wool rows. Wet-finishing creates the ruffles.',pages='64-67',colors=['#171717','#ec5726','#b8b8b8','#161616','#242424'],warpColors=fc,weftColors=bcolors,thickness=[1,1,1,1,0.6])

    issue=dict(id=ISSUE,patterns=patterns,_omissions=[
        'A Shaggy-Bag Story (pp. 22-24): Ghiordes knots on a plain-weave ground; hand-manipulation-only project.',
        'Dip-Dyed Shetland Fringe (pp. 68-72): hand-worked passementerie and dyeing, without a numeric shaft draft.',
        'Yarn Lab Zephira/Zephyr samples (pp. 73-75): photographs and weave descriptions only; numeric drafts are not printed.',
        'Jump-Start Your Designs with Historic Drafts (p. 63): small reference thumbnails and external Handweaving.net identifiers, rather than project drafts.',
        'The reader-guide draft (p. 80) illustrates how to read repeats; it is not an additional issue project.'
    ])
    target=Path(__file__).with_name('handwoven-2025-i-winter.json')
    target.write_text(json.dumps([issue],ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'patterns':len(patterns),'variants':[p['title'] for p in patterns]}))
