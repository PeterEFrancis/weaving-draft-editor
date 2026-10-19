"""Source-aware Fall 2024 Handwoven transcription and reproducible expansion."""
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "tmp/pdfs/handwoven-2024-iv-fall"
PDF = Path("/Users/peterfrancis/Library/Mobile Documents/com~apple~CloudDocs/Books/Handwoven Magazine/2024 IV Fall.pdf")
ISSUE = "handwoven-2024-iv-fall"
PATTERNS = []

def inside(x, y, bbox):
    return bbox[0] < x < bbox[2] and bbox[1] < y < bbox[3]

def numeric(pg, bbox, pixels=False):
    if pixels:
        bbox = tuple(v * pg.height / 1500 for v in bbox)
    out = []
    for c in pg.chars:
        if c['text'].isdigit() and len(c['text']) == 1:
            x, y = (c['x0'] + c['x1']) / 2, (c['top'] + c['bottom']) / 2
            if inside(x, y, bbox):
                out.append((x, y, int(c['text'])))
    return out

def clusters(values, tolerance=2):
    out=[]
    for v in sorted(values):
        if not out or v-out[-1][-1]>tolerance:
            out.append([v])
        else:
            out[-1].append(v)
    return [sum(v)/len(v) for v in out]

def article(pg, name, threading_box, tieup_box, treadling_box, ordinal):
    thread = numeric(pg, threading_box, True)
    tie = numeric(pg, tieup_box, True)
    xs = clusters([c[0] for c in tie])
    ties = [[] for x in xs]
    for x,y,n in tie:
        ties[min(range(len(xs)),key=lambda i:abs(xs[i]-x))].append(n)
    bbox=tuple(v*pg.height/1500 for v in treadling_box)
    slashes=[((c['x0']+c['x1'])/2,(c['top']+c['bottom'])/2) for c in pg.chars if c['text']=='/' and inside((c['x0']+c['x1'])/2,(c['top']+c['bottom'])/2,bbox)]
    ys=clusters([c[1] for c in slashes],1)
    tread=[[] for y in ys]
    for x,y in slashes:
        tread[min(range(len(ys)),key=lambda i:abs(ys[i]-y))].append(min(range(len(xs)),key=lambda i:abs(xs[i]-x)))
    shafts=max(c[2] for c in tie)
    add(f"p{pg.page_number-4}-s{ordinal:02}",name,"Madelyn van der Hoogt",str(pg.page_number-4),"Twill",shafts,[v[2] for v in sorted(thread,reverse=True)],[sorted(set(s for t in ts for s in ties[t])) for ts in tread],description="Numeric example from The Draft: What Is a Twill? Threading, tie-up, and full illustrated treadling follow the printed diagram; source threading is read from right to left.",colors=["#eee7d6","#244f83"])

def add(suffix,title,designer,pages,kind,shafts,threading,lifts,description,**extra):
    PATTERNS.append(dict(id=f"hw-2024-iv-fall-{suffix}",title=title,designer=designer,pages=pages,kind=kind,description=description,shafts=shafts,threading=threading,lifts=lifts,**extra))

def rep(data,ranges):
    """Expand nonoverlapping, end-exclusive, source-index brackets."""
    out=[]
    pos=0
    for start,end,count in ranges:
        out.extend(data[pos:start])
        out.extend(data[start:end]*count)
        pos=end
    return out+data[pos:]

def ties_for(pg,box):
    tie=numeric(pg,box,True)
    xs=clusters([x for x,y,n in tie])
    out=[set() for x in xs]
    for x,y,n in tie:
        out[min(range(len(xs)),key=lambda i:abs(xs[i]-x))].add(n)
    return [sorted(v) for v in out]

def project(suffix,title,designer,pages,kind,shafts,thread,rows,ties,description,palette=None,thickness=None):
    palette=list(palette or [])
    def color(c):
        if c not in palette: palette.append(c)
        return palette.index(c)
    warp=[color(t[2]) for t in thread]
    weft=[color(r['color']) for r in rows]
    lifts=[sorted(set(s for t in r['t'] for s in ties[t])) for r in rows]
    add(suffix,title,designer,pages,kind,shafts,[t[1] for t in thread],lifts,description,colors=palette,warpColors=warp,weftColors=weft,**({'thickness':thickness} if thickness else {}))

def project_drafts(pdf):
    threads={}
    for n,(boxes,sh,col) in THREAD_BOXES.items():
        threads[n]=[threadmarks(pdf.pages[n-1],b,sh,col) for b in boxes]
    rawrows={n:[marked_rows(pdf.pages[n-1],b,c) for b,c in bs] for n,bs in ROW_BOXES.items()}
    # Repeated ends are expanded before reversing the printed right-to-left draft.
    t=threads[46][0]
    threads[46]=list(reversed(t[:4]+t[4:10]*8+(t[10:16]*8+t[16:22]*8)*3+t[22:]))
    t=threads[50][0]
    threads[50]=list(reversed(t[:1]+t[1:3]*2+(t[3:5]*2+t[5:8]+t[8:10]*2+t[10:13])*32+t[13:15]*4+t[15:]))
    t=threads[54][0]
    threads[54]=list(reversed(sum((t[2*i:2*i+2]*count for i,count in enumerate([16,12,8,16,8,12,16,8,12,16,8,16])),[])))
    t=threads[57][0]
    left=rep(t[:21],[(0,2,10),(3,5,4),(5,7,2),(7,9,2),(9,11,2),(11,13,4),(15,17,2),(19,21,4)])
    middle=rep(t[21:37],[(2,4,2),(6,8,4),(10,12,2),(14,16,4)])*3
    right=rep(t[37:],[(0,2,2),(2,4,2),(4,6,2),(6,8,4),(8,10,10)])
    threads[57]=list(reversed(left+middle+right))
    t=threads[60][0]
    threads[60]=list(reversed(t[:6]+t[6:10]*3+(t[10:14]+t[14:18]*3+t[18:22]+t[22:26]*3)*9+t[26:]))
    t=threads[63][0]
    middle=rep(t[2:20],[(1,3,8),(4,6,5),(7,9,3),(10,12,5),(13,15,3),(16,18,5)])
    threads[63]=list(reversed(t[:2]*32+middle*5+t[20:21]+t[21:23]*40))
    a,b,c=threads[66]
    threads[66]=list(reversed(sum((a[i*4:i*4+4]*n for i,n in enumerate([2,2,2,2,2,3,2,2])),[])))+list(reversed(sum((b[i:i+4]*2 for i in range(0,32,4)),[])))+list(reversed(c[:1]+sum((c[1+i*4:5+i*4]*n for i,n in enumerate([2,2,3,2,2])),[])))
    a,b=threads[70]
    threads[70]=(list(reversed(a[:18]+a[18:]*2))+list(reversed(b[3:])))*4+list(reversed(b[:3]))
    t=threads[74][0]
    threads[74]=list(reversed((t[:4]*4+(t[4:8]*4+t[8:12]*4)*4+t[12:16]*4+(t[16:20]*4+t[20:24]*4)*4)*2))
    expected={46:344,50:462,54:296,57:201,60:310,63:465,66:177,70:259,74:576}
    for n,count in expected.items():
        assert len(threads[n])==count,(n,len(threads[n]),count)
    # Autumn Jewel: 15 complete thick/thin design sections, including every tabby.
    r=rawrows[46][0]
    rows=r[:4]+(r[4:10]*8+r[10:12]*24+r[12:18]*8)*15+r[18:]
    project('p42-s01','Autumn Jewel Scarf','Véronique Perrot','40-42','Diversified plain weave and plain weave',4,threads[46],rows,ties_for(pdf.pages[45],(861,406,931,478)),"Full 344-end threading with the three expanded diversified-plain-weave stripes and all 15 treadling repeats. Dark blue and purple fine warp ends are threaded randomly in the source; one dark tone represents that unspecified mixture. The variegated wool is approximated by its blue-green warp and pink-orange weft key colors.",palette=['#4f3bff','#23c6b0','#6304fc','#ff3382'],thickness=[1,3,1,3])
    # The sherbet warp colors are deliberately randomized in the source. Preserve
    # its measured triple-color order with a reproducible allowed ordering.
    p=['#637aa3','#a777b6','#e99774','#66a778']
    held=[[0,1,2]]*7+([[3,1,0]]*7+[[3,2,0]]*8+[[3,2,1]]*7+[[2,1,0]]*6)*5+[[3,1,0]]*7
    wc=sum(held,[])
    assert len(wc)==462,len(wc)
    th=[(x,s,p[ci]) for (x,s,c),ci in zip(threads[50],wc)]
    def colorcounts(box,ncols):
        b=tuple(v*774/1500 for v in box)
        words=[w for w in pdf.pages[49].extract_words(x_tolerance=1) if w['text'].isdigit() and inside((w['x0']+w['x1'])/2,(w['top']+w['bottom'])/2,b)]
        return [(min(ncols-1,int((((w['x0']+w['x1'])/2-b[0])/(b[2]-b[0]))*ncols)),int(w['text'])) for w in sorted(words,key=lambda w:w['top'])]
    c1=colorcounts((582,579,654,1347),4)
    c2=colorcounts((740,579,777,1069),2)
    assert len(c1)==44 and len(c2)==28,(len(c1),len(c2))
    c1=rep(c1,[(2,34,3)])
    c2=rep(c2,[(2,18,6)])
    weft1=sum(([ci]*n for ci,n in c1),[])
    weft2=sum(([ci]*n for ci,n in c2),[])
    # Read the 28-row numeric treadling itself, not its threading analogy.
    slashes=sorted([c for c in pdf.pages[49].chars if c['text']=='/' and 462<c['x0']<482 and 125<c['top']<380],key=lambda c:c['top'])
    tread=[0 if c['x0']<470 else 1 for c in slashes]
    assert len(tread)==28
    bodycount=len(weft1)-60
    assert bodycount==len(weft2)-60 and (bodycount-10)%14==0,(bodycount,len(weft2))
    tread=tread[:2]*15+tread[2:5]+tread[5:19]*((bodycount-10)//14)+tread[19:26]+tread[26:28]*15
    for i,pair in enumerate([None,(0,1),(2,3),(3,0)],1):
        if pair is None: colors=weft1
        else:colors=[pair[ci] for ci in weft2]
        assert len(colors)==len(tread),(len(colors),len(tread))
        rows=[dict(t=[tread[j]],color=p[ci],width=4.5) for j,ci in enumerate(colors)]
        project(f'p46-s{i:02}',f'Rainbow Sherbet Towels - Towel {i}','Malynda Allen','44-46','Plain weave with basketweave',2,th,rows,[[1],[2]],"Two-shaft hopsack design with the complete 462-end bracket expansion. Warp groups are held in threes and threaded in random color order in the published instructions; the catalog uses a repeatable ordering of those groups. Mock-plain-weave hems are included. Towel color versions follow the project's named palettes.")
    # Honeycomb: preserve the two separately printed treadlings, their 4x
    # plain-weave groups, and the thick denim strip picks.
    pal=['#e3e0ae','#757dff','#ffffff','#6665a2','#f8f8f6']
    for variant,(first,cont,tbox) in enumerate([(rawrows[54][0],rawrows[54][1],(855,166,960,236)),(rawrows[54][2],rawrows[54][3],(489,305,595,375))],1):
        first=rep(first,[(11,13,4),(22,24,4),(33,35,4),(44,46,4)] if variant==1 else [(11,13,4),(22,24,4),(33,35,4)])
        cont=rep(cont,[(0,2,4),(11,13,4)] if variant==1 else [(0,2,4),(11,13,4),(22,24,4)])
        rows=first+cont
        for rr in rows:
            if rr['width']>5.5: rr['color']=pal[3] if rr['color']==pal[1] else pal[4]
        thread=[(x,s,pal[0]) for x,s,c in threads[54]]
        project(f'p50-s{variant:02}',f'Dizzy Drones Honeycomb Pillows - Pillow {variant}','Rebecca Fox','48-50','Honeycomb',4,thread,rows,ties_for(pdf.pages[53],tbox),"Complete 296-end honeycomb threading and this pillow's distinct thin-weft and denim-strip sequence, with every 4x bracket expanded. The 6-inch plain-weave sections at each end are represented by their two-pick repeat; repeat them to the specified length. Wet-finishing and denim-strip deflection create the honeycomb relief.",palette=pal,thickness=[1,1,1,3,3])
    r=rawrows[57][0]
    rows=r[:2]*12+r[2:4]*8+rep(r[4:20],[(0,2,3),(2,4,3),(4,6,3),(6,8,5),(8,10,3),(10,12,3),(12,14,3),(14,16,5)])*23+r[20:22]*3+r[22:24]*3+r[24:26]*3+r[26:28]*8+r[28:30]*12
    project('p53-s01','A Taste of Sonoma Scarf','Robin Monogue','51-53','Barleycorn',4,threads[57],rows,ties_for(pdf.pages[56],(898,355,968,426)),"Full 201-end barleycorn threading, 23 body repeats, three-pick and five-pick pattern groups, and the printed opening and closing color borders. Every tabby pick is explicit; the thicker Tawny wool pattern weft alternates with Tencel ground weft.",palette=['#9b4e00','#af86ff','#7d94ff','#922f99'],thickness=[.8,1,.8,1.8])
    r=rawrows[60][0]
    rows=r[:2]+(r[2:5]+r[5:13]*2+r[13:17]+r[17:25]*2+r[25:26])*8+r[26:29]+r[29:37]*2+r[37:]
    project('p56-s01','Blue Willow Towels','Susie Hodges','54-56','Summer and winter',4,threads[60],rows,ties_for(pdf.pages[59],(791,249,896,320)),"Complete 310-end color-and-weave threading with both 3x and 9x brackets expanded, and the 8x windowpane treadling repeat with its nested 2x groups. The two-inch hems are represented by one plain-weave cycle, to be repeated to length. All ground picks are explicit.")
    r,c=rawrows[63]
    rows=r[:4]*16+r[4:8]*12+r[8:20]+r[20:24]*6+(r[24:36]+r[36:40]*11)*2+r[40:52]+r[52:56]*6+c[:12]+c[12:16]*11+c[16:18]+c[18:22]*16+c[22:23]
    tie=ties_for(pdf.pages[62],(903,201,973,307))
    for i,(title,rr) in enumerate([('front',rows),('back',c[23:])],1):
        project(f'p59-s{i:02}',f'Corduroy Patch Pillow - {title}','Sue Anne Sullivan','57-59','Corduroy' if i==1 else 'Plain weave',6,[(x,s,'#f9f6b6') for x,s,_ in threads[63]],rr,tie,"Full 465-end six-shaft corduroy threading. The front contains every printed float-pattern repeat, with doubled Lavender Bright and Green Teal pattern yarns; cut the wool float columns after weaving to form pile. The back uses the separately printed four-pick plain-weave repeat, repeated for 23 1/4 inches. The drawdown represents interlacements before the pile is cut.",palette=['#f9f6b6','#892bff','#6affd1'],thickness=[1,2,2])
    rows=supplement_numbers(next(SCRATCH.glob('*schipf*.pdf')),with_colors=True)
    assert len(rows)==536,len(rows)
    project('p62-s01','Taqueté All Day Tote','Annette Swan Schipf','60-62','Taqueté',8,[(x,s,'#211712') for x,s,_ in threads[66]],rows,[[s] for s in range(1,9)],"All three threading continuations are expanded. The publisher's complete 536-pick numeric lift plan supplies the exact shed and color on every pick, including red-leading blocks and separate cotton headers/footers. That official plan differs from the magazine diagram at its first pick of one block (pick 77) and some repeat extents, so the complete publisher plan is used. The skeleton tie-up's paired treadles are represented by their raised-shaft union; there is no inserted tabby.",palette=['#211712','#2b160d','#d40600'],thickness=[1,2,2])
    rr=rawrows[70]
    tie=ties_for(pdf.pages[69],(791,256,966,398))
    for i,(name,rows) in enumerate([('advancing point',rr[0]),('straight draw',rr[1]),('point draw',rr[2]+rr[3]),('rosepath',rr[4])],1):
        project(f'p66-s{i:02}',f'Gilded Amethyst Scarf - {name}','Laurie Brown','64-67','Stitched doubleweave',8,threads[70],rows,tie,"Complete 259-end threading with its continued 4x bracket and nested 2x group expanded. This is the separately labeled "+name+" treadling from the printed draft. Gold pattern picks alternate with Amethyst tie-down picks, with the two tie-down sheds kept explicit. Repeat or combine these motifs as described in the project.")
    # The publisher's six-page numeric plan is the standard 10-treadle
    # treadling, not shaft lifts (the printed digit 0 denotes treadle 10).
    path=next(SCRATCH.glob('*kaestner*.pdf'))
    tread=supplement_numbers(path)
    assert len(tread)==1524,len(tread)
    tie=ties_for(pdf.pages[73],(519,207,694,314))
    pal=['#ffffff','#d8d9cd','#959490','#424647','#141414']
    warp=[0]*144+[1]*144+[2]*144+[3]*144
    modthread=[(x,s,pal[ci]) for (x,s,_),ci in zip(threads[74],warp)]
    for i,cc in enumerate([[2,4,4,4,4,4,2],[3,3,2,2,2,1,1],[2,1,0,3,2,1,0]],1):
        weft=[cc[0]]*132+sum(([ci]*252 for ci in cc[1:6]),[])+[cc[6]]*132
        rows=[dict(t=[ts[0]-1],color=pal[ci],width=6) for ts,ci in zip(tread,weft)]
        project(f'p70-s{i:02}',f'Mod Block Towels - Towel {i}','Tracy Kaestner','68-71','Summer and winter',6,modthread,rows,tie,"Complete 576-end, four-block threading and the publisher's 1,524-pick standard treadling. The five 252-pick pattern blocks and the 132-pick hem/border sections use this towel's published weft colors. The printed 8-treadle skeleton tie-up produces the same raised-shaft unions; the standard version is stored once. All tabby picks are explicit.",palette=pal)

def supplement_numbers(path,with_colors=False):
    result=[]
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            chars=[c for c in pg.chars if c['text'].isdigit() and len(c['text'])==1 and c['upright'] and 5<c['size']<9 and 20<c['top']<780]
            groups=clusters([c['x0'] for c in chars],40)
            for center in reversed(groups):
                cs=[c for c in chars if min(range(len(groups)),key=lambda i:abs(groups[i]-c['x0']))==groups.index(center)]
                ys=clusters([c['top'] for c in cs],1)
                right=max(c['x1'] for c in cs)
                for y in ys:
                    vals=sorted([c for c in cs if abs(c['top']-y)<1],key=lambda c:c['x0'])
                    numbers=[10 if c['text']=='0' else int(c['text']) for c in vals]
                    if not with_colors:
                        result.append(numbers)
                    else:
                        cy=(vals[0]['top']+vals[0]['bottom'])/2
                        bars=[r for r in pg.rects if right<r['x0']<right+30 and 6<r['width']<10 and r['top']<cy<r['bottom'] and r['non_stroking_color']!=1.0]
                        assert bars,(path,y,right)
                        bar=min(bars,key=lambda r:r['x0'])
                        c=bar['non_stroking_color']
                        color='#2b160d' if isinstance(c,(int,float)) else '#d40600' if max(c)-min(c)>.1 else '#211712'
                        result.append(dict(t=[n-1 for n in numbers],color=color,width=4.5 if color=='#211712' else 6))
    return result

def runner(pdf):
    # Abbreviated block draft, p.38, read right to left. C1/C2 and B1
    # contain the single contrasting warp ends exactly where marked.
    wine,safari,pistachio,ruby='#8b1d49','#c7b572','#91c74e','#751d7b'
    blocks={k:[(0,s,wine) for s in ss] for k,ss in {'A':[1,2,3,4,5],'B':[6,7,8,9,10],'C':[11,12,13,14,15]}.items()}
    blocks['B1']=[(x,s,pistachio if s==6 else c) for x,s,c in blocks['B']]
    blocks['C1']=[(x,s,safari if s==11 else c) for x,s,c in blocks['C']]
    blocks['C2']=[(x,s,safari if s==15 else c) for x,s,c in blocks['C']]
    names=['A','C','C1','C','A','B','B1','B','A','C','A','B','C2','C1','B','A','C','A','B','B1','B','A','C','C1','C','A']
    counts=[3,9,1,10,2,2,1,3,2,10,2,2,1,1,2,2,10,2,2,1,3,2,9,1,10,3]
    units=list(zip(names,counts))
    units=units[:9]+units[9:22]*2+units[22:]
    thread=[(0,16,wine)]*2+sum((blocks[k]*n for k,n in reversed(units)),[])+[(0,16,wine)]*2
    assert len(thread)==684,len(thread)
    path=next(SCRATCH.glob('*o-hara*lift-plan.pdf'))
    with pdfplumber.open(path) as d:
        # These liftplans contain filled grid cells rather than numeric text.
        def read(pg,x,y,n):
            result=[dict(t=[],color=ruby,width=6) for _ in range(n)]
            for r in pg.rects:
                cx,cy=(r['x0']+r['x1'])/2,(r['top']+r['bottom'])/2
                if 4<r['width']<8 and 4<r['height']<8 and x<cx<x+144 and y<cy<y+9*n:
                    row=int((cy-y)/9); shaft=int((cx-x)/9)
                    result[row]['t'].append(shaft)
                    col=hexcolor(r['non_stroking_color'])
                    # Palette keys are CMYK fills, not color-managed sRGB.
                    if r['non_stroking_color'][0]<.3:result[row]['color']=safari
                    elif r['non_stroking_color'][1]<.3:result[row]['color']=pistachio
            for r in result:r['t']=sorted(set(r['t']))
            assert all(r['t'] for r in result)
            return result
        a=read(d.pages[0],234,36,60)
        b=read(d.pages[0],27,36,60)
        c=read(d.pages[1],225,36,65)
        e=read(d.pages[1],18,36,65)
    center=(a[40:60]+b[:30]+b[30:40]*5+b[40:]+c[:30]+c[30:40]*5)*2
    rows=a[:10]*3+a[10:20]*14+(a[20:30]+a[30:40]*13)*2+center+c[40:]+e[:25]+e[25:35]*14+(e[35:45]+e[45:55]*13)*2+e[55:65]*3
    assert len(rows)==1350,len(rows)
    project('p38-s01','Vis-à-Vis Runner','Sheila O’Hara','36-38','5-end satin damask',16,thread,rows,[[s] for s in range(1,17)],"Full three-block satin-damask runner: 682 working ends (684 physical threads, with doubled selvedges on shaft 16) and all 1,350 picks. The publisher's freely provided two-page lift plan completes the abbreviated threading printed on p.38; all continued brackets and single Safari/Pistachio picks are expanded. The loom-controlled selvedges are included.")

def article_drafts(pdf):
    configs = [
      (37,"3-shaft straight twill - 1/2",(574,723,612,762),(612,723,652,762),(612,762,652,801),1),
      (37,"4-shaft straight twill - 1/3",(669,697,720,748),(720,697,771,748),(720,748,771,800),2),
      (37,"4-shaft straight twill - 2/2",(782,697,834,748),(834,697,886,748),(834,748,886,800),3),
      (37,"4-shaft straight twill - 3/1",(895,697,948,748),(948,697,999,748),(948,748,999,800),4),
      (37,"6-shaft straight twill - 2/4",(573,916,649,990),(649,916,725,990),(649,990,725,1066),5),
      (37,"6-shaft straight twill - 1/1/1/3",(735,916,812,990),(812,916,888,990),(812,990,888,1066),6),
      (37,"8-shaft twill - 3/2/1/2",(573,1178,676,1278),(676,1178,778,1278),(676,1278,778,1380),7),
      (37,"8-shaft twill - 3/3/1/1",(788,1178,891,1278),(891,1178,994,1278),(891,1278,994,1380),8),
      (38,"4-shaft broken twill",(133,142,397,201),(397,142,455,201),(397,201,455,466),1),
      (38,"4-shaft point twill",(134,515,398,572),(398,515,455,572),(398,572,455,837),2),
      (38,"8-shaft point twill - 3/2/1/2",(71,886,475,999),(475,886,589,999),(475,999,589,1403),3),
      (38,"4-shaft extended point twill",(618,645,884,702),(884,645,941,702),(884,702,941,967),4),
      (38,"8-shaft extended point twill",(615,1022,888,1128),(888,1022,994,1128),(888,1128,994,1402),5),
      (39,"4-shaft irregular twill",(92,136,385,193),(385,136,469,193),(385,193,469,487),1),
      (39,"8-shaft irregular twill",(92,566,435,661),(435,566,531,661),(435,661,531,1006),2),
      (39,"Twill blocks (turned twill)",(568,134,883,238),(883,134,990,238),(883,238,990,556),3),
      (39,"Double-two-tie (plaited) twill",(569,645,881,750),(881,645,1012,750),(881,750,1012,1190),4),
    ]
    for n,name,th,ti,tr,o in configs:
        article(pdf.pages[n-1],name,th,ti,tr,o)

def hexcolor(c):
    if len(c)==4:
        return '#'+''.join(f'{round(255*(1-v)*(1-c[3])):02x}' for v in c[:3])
    if len(c)==1:
        return '#'+f'{round(c[0]*255):02x}'*3
    return '#'+''.join(f'{round(v*255):02x}' for v in c[:3])

def threadmarks(pg,bbox,shafts,colored=False):
    box=tuple(v*pg.height/1500 for v in bbox)
    if not colored:
        return [(x,n,'#eee7d6') for x,y,n in sorted(numeric(pg,bbox,True))]
    found={}
    for c in pg.curves:
        x,y=(c['x0']+c['x1'])/2,(c['top']+c['bottom'])/2
        if 3<c['width']<7 and 3<c['height']<7 and inside(x,y,box):
            shaft=shafts-round((y-box[1])/(box[3]-box[1])*shafts-.5)
            found[round(x,1)]=(x,shaft,hexcolor(c['non_stroking_color']))
    return sorted(found.values())

THREAD_BOXES={
46:([(407,406,861,476)],4,True),
50:([(582,209,897,248)],2,False),
54:([(401,166,855,239)],4,False),
57:([(90,355,898,425)],4,True),
60:([(266,248,791,319)],4,True),
63:([(466,201,903,310)],6,False),
66:([(235,232,811,376),(218,442,777,586),(392,651,777,796)],8,False),
70:([(249,256,774,397),(302,465,756,606)],8,True),
74:([(65,207,519,316)],6,False),
}

def dump_threads(pdf):
    for n,(boxes,sh,col) in THREAD_BOXES.items():
        pg=pdf.pages[n-1]
        print('\nPAGE',n)
        for box in boxes:
            data=threadmarks(pg,box,sh,col)
            print('BOX',box,[(i,round(x*1500/pg.height),s,c) for i,(x,s,c) in enumerate(data)])

def marked_rows(pg,box,cols,pixelheight=1500):
    bbox=tuple(v*pg.height/pixelheight for v in box)
    marks={}
    for r in pg.rects:
        x,y=(r['x0']+r['x1'])/2,(r['top']+r['bottom'])/2
        if 3<r['width']<7.1 and 3<r['height']<7.1 and inside(x,y,bbox):
            marks[(round(x,2),round(y,2))]=(x,y,hexcolor(r['non_stroking_color']),r['width'])
    ys=clusters([v[1] for v in marks.values()],1)
    rows=[dict(t=[],color=None,width=0) for y in ys]
    for x,y,c,w in marks.values():
        row=rows[min(range(len(ys)),key=lambda i:abs(ys[i]-y))]
        row['t'].append(min(cols-1,max(0,int((x-bbox[0])/(bbox[2]-bbox[0])*cols))))
        row['color']=c
        row['width']=max(row['width'],w)
    return [dict(t=sorted(set(r['t'])),color=r['color'],width=r['width']) for r in rows]

ROW_BOXES={
46:[((861,476,931,859),4)],
54:[((855,235,960,1195),6),((663,436,768,856),6),((489,375,595,1144),6),((279,436,385,1047),6)],
57:[((898,425,968,950),4)],
60:[((791,319,896,1070),6)],
63:[((903,306,973,1283),4),((745,480,815,970),4)],
66:[((811,372,986,1280),10),((584,860,759,1280),10),((357,860,532,1280),10),((131,860,306,1210),10)],
70:[((791,396,966,1408),10),((546,674,721,954),10),((546,954,721,1338),10),((302,674,477,849),10),((302,849,477,1338),10)],
}

def dump_rows(pdf):
    for n,bs in ROW_BOXES.items():
        print('\nPAGE',n)
        for b,c in bs:
            data=marked_rows(pdf.pages[n-1],b,c)
            print('BOX',b,'N',len(data),'DATA',[(i,r['t'],r['color'],r['width']) for i,r in enumerate(data)])

def acquire():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    html = urllib.request.urlopen("https://lt.media/HWFA2024-Extras").read().decode()
    urls = sorted(set(re.findall(r"/files/75077/[^\s\"<>\\]+\.pdf", html)))
    for url in urls:
        out = SCRATCH / url.split("/")[-1]
        if not out.exists():
            urllib.request.urlretrieve("https://handwovenmagazine.com" + url, out)
        print(out.name)

if __name__ == "__main__" and "--download" in sys.argv:
    acquire()
elif __name__ == "__main__":
    with pdfplumber.open(PDF) as pdf:
        if '--dump' in sys.argv:
            dump_threads(pdf)
        elif '--rows' in sys.argv:
            dump_rows(pdf)
        else:
            article_drafts(pdf)
            runner(pdf)
            project_drafts(pdf)
    for p in PATTERNS:
        print(p['title'],p['shafts'],len(p['threading']),len(p['lifts']))
    if '--dump' not in sys.argv and '--rows' not in sys.argv:
        out=ROOT/'tools/handwoven-2024-iv-fall.json'
        out.write_text(json.dumps([{'id':ISSUE,'patterns':PATTERNS,'notes':[
            'Show Your Team Spirit (pp.22-24) uses finnweave hand pick-up; its ground-only draft and logo pick-up charts are omitted under the existing catalog policy.',
            'From Jacquard to Rigid Heddle (pp.25-28) contains illustrative pickup designs, not a complete numeric project draft.',
            'Yarn Lab (pp.72-75) shows eight photographed samples but supplies no numerical threading/tie-up/treadling, so those are not invented.',
            'The 17 numeric examples in The Draft: What Is a Twill? (pp.33-35) are included separately.',
            'Vis-à-Vis Runner uses the official freely accessible lift-plan supplement linked by the issue, https://handwovenmagazine.com/files/75077/1722288901-o-hara-hwf24-runner-lift-plan.pdf.',
            'Mod Block Towels uses the official standard-treadling supplement, https://handwovenmagazine.com/files/75077/1722460285-hwfa24-kaestner-mod-block-towels-lift-plan.pdf; its digit 0 denotes treadle 10, not a shaft.',
            'Length-only plain-weave borders on Blue Willow and Honeycomb are stored as their short repeat, to be woven to the specified inch measurement.',
            'Rainbow Sherbet randomizes the color order within three-end groups. A deterministic permissible order is used; every printed color-group count and every numbered weft-color repeat is expanded.',
            'The three subscriber-exclusive photo-only projects on p.77 require separate project downloads and are outside the supplied issue; their drafts are not reconstructed from photographs.'
        ]}],ensure_ascii=False,indent=2)+'\n')
