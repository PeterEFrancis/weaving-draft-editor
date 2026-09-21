const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'drafter.html'), 'utf8');
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const renderer = script.slice(script.indexOf('function findCompactDrawdownTrack('),
  script.indexOf('function renderCompactDrawdown('));

test('large drafts render visible crossings at native resolution throughout scrolling', () => {
  const columnWidths = Array.from({ length: 368 }, (_, i) => i % 3 ? 20 : 30);
  const rowHeights = Array.from({ length: 5542 }, (_, i) => i % 5 ? 20 : 10);
  const edges = sizes => sizes.reduce((result, size) => [...result, result.at(-1) + size], [0]);
  const columnEdges = edges(columnWidths), rowEdges = edges(rowHeights);
  const canvas = { style: {} };
  let rectangles = [];
  let transform;
  const ctx = {
    setTransform(...args) { transform = args; },
    clearRect() { rectangles = []; },
    fillRect(x, y, w, h) { rectangles.push({ x, y, w, h, color: this.fillStyle }); }
  };
  const view = {
    canvas, ctx, columnWidths, rowHeights, columnEdges, rowEdges,
    totalWidth: columnEdges.at(-1), totalHeight: rowEdges.at(-1),
    warpAssignments: columnWidths.map((_, i) => ({ shaft: i % 2, color: '#123456' })),
    pickRows: rowHeights.map((_, i) => ({ raised: [i % 2, 1 - i % 2], hasWeft: true, color: '#abcdef' })),
    ink: '#000000'
  };
  const scroll = { clientWidth: 800, clientHeight: 600 };
  const window = { innerWidth: 1200, innerHeight: 900 };
  const context = vm.createContext({ compactDrawdownView: view, drawdownScrollElement: scroll, window });
  vm.runInContext(renderer, context);
  for (const dpr of [1, 1.25, 2]) {
    window.devicePixelRatio = dpr;
    for (const [left, top] of [[0, 0], [3456.5, 50123.5], [view.totalWidth - 800, view.totalHeight - 600]]) {
      Object.assign(scroll, { scrollLeft: left, scrollTop: top });
      for (const style of ['color', 'structure', 'warp-faced', 'weft-faced', 'realistic']) {
        view.renderStyle = style;
        context.paintCompactDrawdown();
        assert.equal(canvas.width / parseFloat(canvas.style.width), dpr);
        assert.equal(canvas.height / parseFloat(canvas.style.height), dpr);
        assert.ok(canvas.width <= 1056 * dpr + 1 && canvas.height <= 856 * dpr + 1);
        assert.equal(transform[0], dpr);
        assert.equal(transform[3], dpr);
        assert.ok(rectangles.length < 6000, 'only nearby crossings should be drawn');
        for (const [x, y] of [[left + 1, top + 1], [left + 799, top + 599]]) {
          const rect = rectangles.findLast(r => r.x <= x && r.x + r.w > x && r.y <= y && r.y + r.h > y);
          assert.ok(rect, 'both viewport corners must be covered after scrolling');
          if (style === 'color' || style === 'structure') {
            const shaft = columnEdges.findIndex(edge => edge > x) - 1;
            const pick = rowEdges.findIndex(edge => edge > y) - 1;
            const raised = shaft % 2 !== pick % 2;
            assert.equal(rect.color, style === 'color' ? (raised ? '#123456' : '#abcdef') : (raised ? '#000000' : '#ffffff'));
          }
        }
      }
    }
  }
});
