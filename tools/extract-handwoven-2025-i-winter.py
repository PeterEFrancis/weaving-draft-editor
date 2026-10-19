"""Read and render the supplied Winter 2025 issue for numeric draft transcription."""
from pathlib import Path
import json
import pdfplumber
from collections import defaultdict

SOURCE = Path('/Users/peterfrancis/Library/Mobile Documents/com~apple~CloudDocs/Books/Handwoven Magazine/2025 I Winter.pdf')
SCRATCH = Path(__file__).resolve().parents[1] / 'tmp/pdfs/handwoven-2025-i-winter'
SCRATCH.mkdir(parents=True, exist_ok=True)

def inside(obj, box):
    x, y = (obj['x0']+obj['x1'])/2, (obj['top']+obj['bottom'])/2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]

def cells(page, box, step=9):
    """Numeric cells; retain multi-digit shaft numbers and remove duplicate glyphs."""
    found=defaultdict(dict)
    for c in page.chars:
        if c['text'].isdigit() and inside(c,box):
            col=int((c['x0']+c['x1']-2*box[0])/2/step)
            row=int((c['top']+c['bottom']-2*box[1])/2/step)
            found[row,col][(round(c['x0'],2),c['text'])]=c['text']
    return {(row,col):int(''.join(v for k,v in sorted(chars.items()))) for (row,col),chars in found.items()}

def numbers(page,box,step=9):
    return [v for (r,c),v in sorted(cells(page,box,step).items(),key=lambda p:-p[0][1])]

def tieup(page,box,cols,step=9):
    found=cells(page,box,step)
    return [sorted(set(v for (r,c),v in found.items() if c==col)) for col in range(cols)]

def dots(page,box,shafts,step=9):
    found={}
    for c in page.curves:
        if inside(c,box) and abs(c['width']-6)<.2 and abs(c['height']-6)<.2:
            cx,cy=(c['x0']+c['x1'])/2,(c['top']+c['bottom'])/2
            found[round(cx,2)]=(cy,c['non_stroking_color'])
    top=min(v[0] for v in found.values())
    return [(shafts-round((cy-top)/step),color) for x,(cy,color) in sorted(found.items(),reverse=True)]

def treadles(page,box,cols,step=9):
    found=defaultdict(set)
    for c in page.chars:
        if c['text']=='/' and inside(c,box):
            col=int(((c['x0']+c['x1'])/2-box[0])/step)
            row=int(((c['top']+c['bottom'])/2-box[1])/step)
            found[row].add(col+1)
    # Red second-shuttle slash glyphs are outlines rather than text in this PDF.
    for c in page.curves:
        if inside(c,box) and 2<c['width']<2.6 and 5.8<c['height']<6.2:
            col=int(((c['x0']+c['x1'])/2-box[0])/step)
            row=int(((c['top']+c['bottom'])/2-box[1])/step)
            found[row].add(col+1)
    return [sorted(found[r]) for r in sorted(found)]

def squares(page,box,cols,step=9,size=6):
    found={}
    for c in page.rects:
        if inside(c,box) and abs(c['width']-size)<.2 and abs(c['height']-size)<.2:
            cx,cy=(c['x0']+c['x1'])/2,(c['top']+c['bottom'])/2
            col=int((cx-box[0])/step)
            row=int((cy-box[1])/step)
            found[row,col]=c['non_stroking_color']
    return [(r,c+1,col) for (r,c),col in sorted(found.items())]

if __name__ == '__main__':
    pages = [18,19,20,21,31,32,33,38,42,43,48,52,53,56,60,65,67,70,71,78,79]
    with pdfplumber.open(SOURCE) as pdf:
        for number in pages:
            page = pdf.pages[number-1]
            page.to_image(resolution=130).save(SCRATCH / f'p{number}.png')
            (SCRATCH / f'p{number}.txt').write_text(page.extract_text(layout=True) or '')
            (SCRATCH / f'p{number}-chars.json').write_text(json.dumps([{k:c[k] for k in ('text','x0','x1','top','bottom','fontname','size','non_stroking_color')} for c in page.chars]))
