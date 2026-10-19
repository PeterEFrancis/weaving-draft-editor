#!/usr/bin/env python3
"""Transcribe Fall 2025 vector draft charts and their printed repeat brackets.

Coordinates are PDF points, with origin at the top left. Only loom assignments
and project attribution are exported; source pages and photographs stay local.
"""
import json
import re
from itertools import groupby
from pathlib import Path

import pdfplumber

SOURCE = Path('/Users/peterfrancis/Library/Mobile Documents/com~apple~CloudDocs/Books/Handwoven Magazine/2025 IV Fall.pdf')
OUTPUT = Path(__file__).with_name('handwoven-2025-iv-fall.json')


def hexcolor(value):
    if len(value) == 4:
        c, m, y, k = value
        value = [(1-c)*(1-k), (1-m)*(1-k), (1-y)*(1-k)]
    elif len(value) == 1:
        value = value * 3
    return '#' + ''.join(f'{round(max(0,min(1,v))*255):02x}' for v in value[:3])


def chart(page, x, y, columns, rows, step=9, numeric=False):
    cells = [[[] for _ in range(columns)] for _ in range(rows)]
    objects = page.chars if numeric else page.rects + page.curves
    for obj in objects:
        if numeric:
            if not obj['text'].isdigit() and obj['text'] != '/':
                continue
        elif not (2 < obj['width'] < step and 2 < obj['height'] < step):
            continue
        cx = (obj['x0'] + obj['x1']) / 2
        cy = (obj['top'] + obj['bottom']) / 2
        col, row = int((cx-x)//step), int((cy-y)//step)
        if x <= cx < x+columns*step and y <= cy < y+rows*step:
            value = obj['text'] if numeric else hexcolor(obj['non_stroking_color'])
            if value not in cells[row][col]:
                cells[row][col].append(value)
    return cells


def warp(page, x, y, columns, shafts, step=9, numeric=False, color='#eee7db'):
    cells = chart(page, x, y, columns, shafts, step, numeric)
    result = []
    for col in range(columns):
        active = [(shafts-row, color if numeric else values[-1]) for row in range(shafts) if (values := cells[row][col])]
        assert len(active) == 1, ('threading', col, active, x, y)
        result.append(active[0])
    return result


def tieup(page, x, y, columns, shafts, step=9):
    cells = chart(page, x, y, columns, shafts, step, True)
    return [[shafts-row for row in range(shafts) if cells[row][col]] for col in range(columns)]


def picks(page, x, y, columns, rows, step=9, numeric=False, color='#66778d'):
    cells = chart(page, x, y, columns, rows, step, numeric)
    glyphs = chart(page, x, y, columns, rows, step, True) if not numeric else None
    result = []
    for row in range(rows):
        active = [col for col in range(columns) if cells[row][col]]
        if not active and glyphs:
            active = [col for col in range(columns) if glyphs[row][col]]
            for col in active:
                cells[row][col] = ['#d1d1d1']
        assert active, ('treadling', row, x, y)
        colors = [cells[row][col][-1] for col in active]
        result.append((active, color if numeric else colors[0]))
    return result


def expand(sequence, spans):
    """Expand nested (start, stop, repetitions) spans in original cell indexes."""
    spans = sorted(spans, key=lambda span: (span[0], -span[1]))
    def segment(start, stop, candidates):
        out = []
        pos = start
        while pos < stop:
            match = next((span for span in candidates if span[0] == pos), None)
            if match:
                a, b, count = match
                inside = [span for span in candidates if span != match and a <= span[0] and span[1] <= b]
                out.extend(segment(a, b, inside) * count)
                pos = b
            else:
                out.append(sequence[pos])
                pos += 1
        return out
    return segment(0, len(sequence), spans)


def brackets(page, axis, region):
    segments = []
    for obj in page.lines + page.curves + page.rects:
        points = obj.get('pts', [])
        for a, b in zip(points, points[1:]):
            if abs(a[0]-b[0]) < .02 or abs(a[1]-b[1]) < .02:
                segments.append((a,b))
    result = []
    for word in page.extract_words():
        if not re.fullmatch(r'\d+x', word['text']):
            continue
        cx, cy = (word['x0']+word['x1'])/2, (word['top']+word['bottom'])/2
        if not (region[0] < cx < region[2] and region[1] < cy < region[3]) or (axis=='x' and not word['upright']):
            continue
        c, at = (cy-1.75,cx) if axis=='x' else (cx+.25,cy)
        candidates = []
        for a,b in segments:
            const = (a[1],b[1]) if axis=='x' else (a[0],b[0])
            lo,hi = sorted((a[0],b[0]) if axis=='x' else (a[1],b[1]))
            if abs(const[0]-const[1]) < .02 and abs(const[0]-c) < 4 and hi-lo > .5:
                candidates.append((const[0],lo,hi))
        options = []
        for coord in set(round(a[0],2) for a in candidates):
            runs = [a for a in candidates if abs(a[0]-coord)<.35]
            left, right = [a for a in runs if a[2]<=at+1], [a for a in runs if a[1]>=at-1]
            if left and right:
                l = min(left,key=lambda a:abs(a[2]-at))
                r = min(right,key=lambda a:abs(a[1]-at))
                options.append((abs(coord-c)*3+abs(l[2]-at)+abs(r[1]-at),l[1],r[2]))
        assert options, ('repeat bracket',word)
        _,lo,hi = min(options)
        result.append((lo,hi,int(word['text'][:-1])))
    return result


def repeated(page, sequence, axis, region, start, step=9):
    spans = [(round((a-start)/step),round((b-start)/step),n) for a,b,n in brackets(page,axis,region)]
    assert all(0<=a<b<=len(sequence) for a,b,n in spans), (len(sequence),spans)
    return expand(sequence,spans)


def color_order(page, box, repeat_region=None, reverse=True, repeat_counts=None):
    """Expand the sparse numeric color-order columns, including their repeats."""
    x0,y0,x1,y1 = box
    swatches = [r for r in page.rects if x1-1 < (r['x0']+r['x1'])/2 < x1+10 and y0<(r['top']+r['bottom'])/2<y1 and r.get('fill')]
    palette = {round(((r['top']+r['bottom'])/2-y0-4.5)/9):hexcolor(r['non_stroking_color']) for r in swatches}
    words = [w for w in page.extract_words(x_tolerance=1) if w['text'].isdigit() and x0<(w['x0']+w['x1'])/2<x1 and y0<(w['top']+w['bottom'])/2<y1]
    runs = sorted([((w['x0']+w['x1'])/2, [palette[round(((w['top']+w['bottom'])/2-y0-4.5)/9)]]*int(w['text'])) for w in words])
    seq = [v for _,v in runs]
    if repeat_region:
        spans = [(sum(x<a for x,_ in runs),sum(x<b for x,_ in runs),(repeat_counts or {}).get(n,n)) for a,b,n in brackets(page,'x',repeat_region)]
        seq = expand(seq,spans)
    result = sum(seq,[])
    return result[::-1] if reverse else result


def add(patterns, page, title, designer, kind, shafts, threading, treadling, sheds, description, variant=1, thickness=None):
    colors = list(dict.fromkeys([c for _, c in threading] + [c for _, c in treadling]))
    entry = {
        'id': f'hw-2025-iv-fall-p{page}-s{variant:02}',
        'title': title, 'designer': designer, 'pages': str(page),
        'kind': kind, 'description': description, 'shafts': shafts,
        'threading': [s for s, _ in threading],
        'lifts': [sorted(set(s for t in ts for s in sheds[t])) for ts, _ in treadling],
        'colors': colors,
        'warpColors': [colors.index(c) for _, c in threading],
        'weftColors': [colors.index(c) for _, c in treadling],
    }
    if thickness:
        entry['thickness'] = [thickness.get(c, 1) for c in colors]
    patterns.append(entry)
    return entry


def main():
    patterns = []
    with pdfplumber.open(SOURCE) as document:
        build(document, patterns)
    OUTPUT.write_text(json.dumps([{'id': 'handwoven-2025-iv-fall', 'patterns': patterns}], indent=2) + '\n')
    print(json.dumps({'issue': 'Fall 2025', 'patterns': len(patterns), 'sizes': [(p['title'], len(p['threading']), len(p['lifts'])) for p in patterns]}))


def build(document, patterns):
    page = lambda n: document.pages[n-1]
    # Zigzag Basket: each of the 89 color rows operates all three treadles.
    p = page(26)
    threading = [(s, '#262626') for s in [1,2,3,2]*15]
    treadling = []
    words = p.extract_words()
    for x, rows in [(214.82,30),(141.32,30),(70.82,29)]:
        grid = chart(p,x,454.66,3,rows)
        for row in range(rows):
            cy = 459.16+9*row
            label = next(w['text'] for w in words if re.fullmatch(r'\d+x',w['text']) and x+27<(w['x0']+w['x1'])/2<x+45 and abs((w['top']+w['bottom'])/2-cy)<5)
            picks_row = [([t],grid[row][t][0]) for t in range(3)]
            treadling.extend(picks_row*int(label[:-1]))
    add(patterns,20,'Zigzag Basket','Annette Swan Schipf','Krokbragd',3,threading,treadling,tieup(p,201,341.5,3,3),
        'The complete 89-row weft-color sequence, with each numbered row expanded into the three krokbragd picks and its printed repeats. Threading represents the 60 doubled warp ends; basket shaping and tripled floating selvedges are worked separately.')

    # Plaid About You: the outer fourfold repeat continues onto the second staff.
    p = page(30)
    a = repeated(p,warp(p,47,178.6,44,4),'x',(47,165,443,179),47)
    b = repeated(p,warp(p,38,250.55,44,4),'x',(38,236,435,251),38)
    threading = (a[::-1]+b[::-1])*4
    assert len(threading)==608
    a = repeated(p,picks(p,443,214.6,4,56),'y',(480,214,490,719),214.6)
    b = repeated(p,picks(p,371,305.9,4,32),'y',(407,306,424,595),305.9)
    add(patterns,24,'Plaid About You Throw','Kathy Broughton','Twill',4,threading,(a+b)*6,tieup(p,443,178.6,4,4),
        'Full 608-end multicolor plaid threading and six complete passes of the printed two-column weft repeat. Inner stripe repeats are expanded; floating selvedges and fringe are separate from the draft.')

    # Shadow Play: one threading, three complete printed treadlings.
    p = page(34)
    threading = repeated(p,warp(p,46.5,231.16,42,4),'x',(45,207,425,231),46.5)[::-1]
    assert len(threading)==442
    warp_colors = color_order(p,(122.5,99.32,458.5,162.32),(122,87,459,100))
    threading = [(s,c) for (s,_),c in zip(threading,warp_colors)]
    sheds = tieup(p,433.5,231.16,4,4)
    color_key = chart(p,38.65,362.5,6,1)[0]
    orders = []
    for row in range(3):
        marks = sorted((c for c in p.chars if c['text'] in ['X','O'] and 38.65<c['x0']<92.65 and 371.5+90*row<c['top']<461.5+90*row),key=lambda c:c['top'])
        orders.append([(c['text'],color_key[int(((c['x0']+c['x1'])/2-38.65)//9)][0]) for c in marks])
    motifs = {}
    for v,(name,x,y,rows,region) in enumerate([
        ('Towel 1 — X',433.5,267.16,38,(469,267,489,609)),
        ('Towel 2 — O',343.5,357.16,38,(379,357,399,700)),
        ('Towel 3',262.5,357.16,18,(298,357,330,520)),
    ],1):
        raw = picks(p,x,y,4,rows)
        spans = [(round((a-y)/9),round((b-y)/9),n) for a,b,n in brackets(p,'y',region) if n<10]
        treadling = expand(raw,spans)
        if v < 3:
            motifs['X' if v==1 else 'O'] = treadling[2:-2]
            treadling = [(ts,orders[v-1][0][1]) for ts,c in treadling[:2]] + [
                (ts,color if c=='#9f4111' else c)
                for _,color in orders[v-1] for ts,c in treadling[2:-2]
            ] + [(ts,orders[v-1][-1][1]) for ts,c in treadling[-2:]]
        else:
            treadling = treadling[:2]+treadling[2:-2]*10+treadling[-2:]
        add(patterns,28,f'Shadow Play Dish Towels — {name}','Dorothy Tuthill','Shadow weave',4,threading,treadling,sheds,
            'Full 442-end threading and warp color order. Numeric treadling brackets and the motif color order are expanded; inch-length hems retain the displayed starter and ending picks. Towel 3 shows ten repeats of its continuous motif.',v)
    treadling = [([0],orders[2][0][1]),([1],orders[2][0][1])]+[
        (ts,color if c=='#9f4111' else c) for motif,color in orders[2] for ts,c in motifs[motif]
    ]+[([0],orders[2][-1][1]),([1],orders[2][-1][1])]
    add(patterns,28,'Shadow Play Dish Towels — Towel 4 — X and O','Dorothy Tuthill','Shadow weave',4,threading,treadling,sheds,
        'The printed mixed X-and-O treadling sequence and matching accent colors on the shared 442-end shadow-weave warp. Inch-length hems are represented by their displayed picks.',4)

    # Autumn Berries: two-treadle combinations in the skeleton tie-up are unions.
    p = page(38)
    threading = repeated(p,warp(p,269.4,118.75,15,8),'x',(278,106,405,119),269.4)[::-1]
    assert len(threading)==477
    a = picks(p,404.4,190.75,10,50)
    b = picks(p,287.4,218.16,10,26)
    swatches = sorted((r for r in p.rects if r['fill'] and 290<r['x0']<340 and 649<r['top']<651),key=lambda r:r['x0'])
    accent = [hexcolor(r['non_stroking_color']) for r in swatches[:-1]][::-1]
    treadling = a[:2]*6+a[2:26]
    for color in accent*9:
        treadling += [(ts,color if c=='#63176e' else c) for ts,c in a[26:50]]
    treadling += b[:24]+b[24:26]*6
    add(patterns,32,'Autumn Berries Cushion Cover','Jeremy Uden','Doubleweave',8,threading,treadling,tieup(p,404.4,118.75,10,8),
        'The 477-end point threading and skeleton tie-up, including simultaneous treadles. All 36 accent-color repeats are represented. This is the flat loom draft; fulling produces the cushion’s sculptural doubleweave texture.')

    # Stormy Skies: the same huck threading is used for towels and a wrap.
    p = page(44)
    threading = repeated(p,warp(p,297.49,187.55,15,4,numeric=True),'x',(297,166,433,188),297.49)[::-1]
    assert len(threading)==415
    warp_colors = color_order(p,(69.76,102.82,438.76,138.82),(69,90,440,103))
    assert len(warp_colors)==415
    threading = [(s,c) for (s,_),c in zip(threading,warp_colors)]
    treadling = repeated(p,picks(p,432.49,223.55,4,10,numeric=True),'y',(469,240,490,297),223.55)
    cycle = treadling[2:-2]
    sheds = tieup(p,432.49,187.55,4,4)
    shades = [hexcolor(next(r for r in p.rects if r['fill'] and 438<r['x0']<450 and abs(r['top']-(104.82+9*row))<2)['non_stroking_color']) for row in range(4)]
    bands = [(color,len(list(run))) for color,run in groupby(warp_colors)]
    sample_band = sum([[color]*count for color,count in bands[:9]],[])
    for v,(name,main_color) in enumerate(zip(['Slate','Olive','Flax','Charcoal'],shades),1):
        weft_colors = [main_color]*310+sample_band+[main_color]*(550-310-len(sample_band))
        treadling = [([0],main_color),([3],main_color)]*5+[(cycle[i%len(cycle)][0],color) for i,color in enumerate(weft_colors)]+[([0],main_color),([3],main_color)]*5
        add(patterns,36,f'Stormy Skies Towels — {name}','Rebecca Logan','Huck spots',4,threading,treadling,sheds,
            'Full 415-end huck warp with this solid cotton weft and a contrasting plaid band. The band uses the project’s example sequence from the start of the warp color order; its placement follows the 20-inch starting section. The 35-inch towel and ten-pick hems are expanded at the specified 16 picks per inch. The article invites changes to the plaid bands.',v)
    # The fifth towel follows the warp colors with its central bracket changed to 12x.
    center = color_order(p,(69.76,102.82,438.76,138.82),(69,90,440,103),repeat_counts={3:12})
    assert len(center)==505
    charcoal = shades[3]
    treadling = [([0],charcoal),([3],charcoal)]*10+[(cycle[i%len(cycle)][0],color) for i,color in enumerate(center)]+[([0],charcoal),([3],charcoal)]*10
    add(patterns,36,'Stormy Skies Towels — Plaid','Rebecca Logan','Huck spots',4,threading,treadling,sheds,
        'The fifth towel follows the entire warp color order as weft, expanding the central 3x color bracket to 12x as instructed. The complete plaid sequence is framed by twenty plain-weave picks at each end.',5)
    treadling = [([0],'#777d84'),([3],'#777d84')]*2+[(cycle[i%len(cycle)][0],'#777d84') for i in range(1344)]+[([0],'#777d84'),([3],'#777d84')]*2
    add(patterns,36,'Stormy Skies Wrap','Rebecca Logan','Huck spots',4,threading,treadling,sheds,
        'The same complete 415-end cotton warp with Quarry-colored silk weft. The 84-inch patterned length is expanded at 16 picks per inch, with four plain-weave picks at each end; hemstitching and fringe are separate.',6)

    # Prairie School Rug: preserve the complete asymmetrical 1,080-end color order.
    p = page(48)
    colors = color_order(p,(205.5,108.75,433.5,198.75),(205,94,434,109)) + color_order(p,(223.5,225.75,430.5,315.75),(223,210,431,226))
    assert len(colors)==1080
    threading = [(1+i%2,c) for i,c in enumerate(colors)]
    treadling = picks(p,61.34,197.78,2,13)
    for row,(ts,_) in enumerate(treadling):
        symbol = next(r for r in p.rects if 61<r['x0']<79 and abs((r['top']+r['bottom'])/2-(202.28+row*9))<2 and 2<r['width']<9)
        treadling[row] = (ts,'#242424' if symbol['width']>5 else '#252525')
    treadling = repeated(p,treadling,'y',(79,197,104,315),197.78)
    add(patterns,42,'Prairie School Rug','Debra K. Sharpee','Rep weave',2,threading,treadling,[[1],[2]],
        'Complete 1,080-end warp color order, alternating shafts 1 and 2. The printed thick-and-thin weft cycle and its numeric brackets are expanded. The three-inch hems remain the displayed thin-pick pair. Relative yarn thickness distinguishes the tripled heavy weft from the fine cotton binder.',thickness={'#242424':3,'#252525':.45})

    # The article supplies both complete turned-twill teaching drafts.
    p = page(52)
    for v,(shafts,x,y,tx,ty,cols) in enumerate([(8,105,161.54,177,233.54,10),(12,59.44,448.46,167.44,556.46,14)],1):
        threading = warp(p,x,y,shafts,shafts,numeric=True)[::-1]*4
        treadling = picks(p,tx,ty,cols,shafts+2,numeric=True)
        add(patterns,48,f'Turned Twill on Three Blocks — {shafts}-shaft study','Véronique Perrot','Turned twill',shafts,threading,treadling[:2]+treadling[2:]*4,tieup(p,tx,y,cols,shafts),
            'The article’s complete comparison tie-up, with the numbered block threadings and treadlings. The source design unit is repeated four times for a readable sample; the first two picks show the plain-weave hem sheds.',v)

    # Ribbons and Blocks: 430 threaded ends, two distinct complete runners.
    p = page(56)
    threading = []
    for x,y,n,region in [(56,224.54,31,(56,210,335,225)),(38,368.54,32,(38,354,327,369)),(47,503.53,39,(47,489,399,504))]:
        threading += repeated(p,warp(p,x,y,n,12),'x',region,x)[::-1]
    assert len(threading)==430
    sheds = tieup(p,344,224.54,14,12)
    p = page(57)
    def blocks(x,y,rows):
        result = []
        for row in range(rows):
            cy = y+row*9+4.5
            word = next(w for w in p.extract_words(x_tolerance=.4) if w['text'].isdigit() and x<(w['x0']+w['x1'])/2<x+27 and abs((w['top']+w['bottom'])/2-cy)<3)
            block = int(((word['x0']+word['x1'])/2-x)//9)
            swatch_x = x-5 if block==0 else x+31
            swatch = next(r for r in p.rects if abs((r['x0']+r['x1'])/2-swatch_x)<3 and abs((r['top']+r['bottom'])/2-cy)<3 and 5<r['width']<8)
            color = hexcolor(swatch['non_stroking_color'])
            result += [([block*4+t],color) for t in range(4)]*int(word['text'])
        return result
    for v,panels in enumerate([[(162.5,280.98,31),(54.5,280.98,26)],[(412.2,277.96,37),(304.2,277.96,34)]],1):
        treadling = sum([blocks(x,y,rows) for x,y,rows in panels],[])
        add(patterns,50,f'Ribbons and Blocks Runner — Runner {v}','Véronique Perrot','Three-block turned twill',12,threading,treadling,sheds,
            'Complete 430-end threading, with all four-end module repeats expanded. Every numbered block repeat and accent color in the two-column runner chart is encoded as four consecutive picks. The background block uses Royal; the other two blocks form interlacing ribbons. Hem picks and floating selvedges are separate.',v)

    # Choose a Path: full pillow treadling, followed by five numbered studies.
    p = page(63)
    threading = warp(p,351.06,119.92,10,4)[::-1]*36
    sheds = tieup(p,450.06,119.92,6,4)
    treadling = repeated(p,picks(p,450.06,155.92,6,62),'y',(504,155,527,714),155.92)
    add(patterns,56,'Choose a Path Pillows','Angela K. Schneider','Plain weave and reversing twill',4,threading,treadling,sheds,
        'The full 360-end five-yarn point threading and printed sequence of differently colored reversing-twill bands, including its 3x and 2x brackets. Plain-weave sections are woven to the project’s measured lengths. Bouclé picks are doubled.',thickness={c:2 for c in ['#e1ff9d','#a8ffc4','#403600','#ffbc02']})
    for v,(title,sequence) in enumerate([
        ('Twill circle',[1,2,3,4,1,2,3,4]),
        ('Simple reversing twill',[1,2,3,4,1,4,3,2,1]),
        ('Twill from a different start',[2,3,4,1,2,1,4,3,2]),
        ('Longer twill',[1,2,3,4,1,2,3,2,1,4,3,2,1]),
        ('Fancy twill',[4,3,2,1,4,3,2,3,4,1,2,1,4,3,2,3,4,1,2,3,4]),
    ],2):
        treadling = [([t-1],'#8cb3a6') for t in sequence]*4
        add(patterns,60,f'Choose a Path — {title}','Angela K. Schneider','Reversing-twill treadling study',4,threading,treadling,sheds,
            'The numbered treadling example from the twill-circle article, repeated four times on the project’s point threading. The studies compare direction changes and starting treadles using the same four twill sheds.',v)

    # Family Dinner: six linen colorways and the cotton/cottolin towel version.
    p = page(68)
    threading = repeated(p,warp(p,37.5,209.5,41,8),'x',(37,190,407,210),37.5)[::-1]
    threading += repeated(p,warp(p,298.5,317.5,9,8),'x',(298,303,380,318),298.5)[::-1]
    assert len(threading)==604
    colors = color_order(p,(154.5,80.27,294,143.27))
    threading = [(s,c) for (s,_),c in zip(threading,colors)]
    sheds = tieup(p,406.5,209.5,6,8)
    napkin_palette = chart(p,137,408.16,6,8)
    def color_bands(p,x,y,palette):
        raw = [(ts,c,row) for row,(ts,c) in enumerate(picks(p,x,y,6,49))]
        expanded = repeated(p,raw,'y',(x+54,y,x+105,y+442),y)
        result, stripe, was_band = [], -1, False
        for ts,c,row in expanded:
            band = 8<=row<23 or 26<=row<41
            if band and not was_band:
                stripe += 1
            if band:
                c = palette[stripe+1]
            elif 2<=row<5:
                c = palette[0]
            elif 44<=row<47:
                c = palette[-1]
            elif row not in [0,1,47,48]:
                c = '#fff5e0'
            result.append((ts,c))
            was_band = band
        assert stripe+1==len(palette)-2, (stripe,palette)
        return result
    for v in range(6):
        palette = [napkin_palette[row][v][0] for row in range(8)]
        treadling = color_bands(p,406.5,281.5,palette)
        add(patterns,62,f'Family Dinner Napkins — Napkin {v+1}','Susan E. Horton','Plain weave with warp floats',8,threading,treadling,sheds,
            'Complete 604-end color-striped threading and this napkin’s eight-row linen weft color order. All numeric 2x and 5x treadling brackets are expanded. Hem and white-frame sections specified in inches retain their printed starter picks; weave those sections to the stated lengths in the project.',v+1)
    p = page(70)
    palette = [row[0][0] for row in chart(p,242.2,132.57,1,11)]
    treadling = color_bands(p,54.5,192.412,palette)
    add(patterns,62,'Family Dinner — Towel','Susan E. Horton','Plain weave with warp floats',8,threading,treadling,sheds,
        'The towel treadling on the shared 604-end warp. All 2x, 3x, and 8x brackets and nine colored stripes are expanded, with the printed cotton/cottolin color sequence. Inch-length sewing hems and white frames retain their displayed starter picks.',7)

    # Falling Leaves: the complete colored warp and four readable leaf repeats.
    p = page(75)
    threading = repeated(p,warp(p,206.16,219.46,19,8,numeric=True),'x',(206,196,378,220),206.16)[::-1]
    assert len(threading)==247
    colors = color_order(p,(214.83,93.59,421.83,147.59))
    assert len(colors)==247
    threading = [(s,c) for (s,_),c in zip(threading,colors)]
    treadling = repeated(p,picks(p,386.16,291.46,10,26,numeric=True,color='#191919'),'y',(476,310,500,510),291.46)
    add(patterns,68,'Falling Leaves Runner','Sue Anne Sullivan','Twill',8,threading,treadling[:2]+treadling[2:-2]*4+treadling[-2:],tieup(p,386.16,219.46,10,8),
        'Full 247-end autumn-color warp, with the nested 15x and 2x threading brackets expanded. Four complete leaf motifs are shown between the two-pick plain-weave ends. The original runner continues the motif to a measured 75-inch woven length; floating selvedges and Italian hemstitching are separate.')


if __name__ == '__main__':
    main()
