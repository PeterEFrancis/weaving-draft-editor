const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');

test('long runner thumbnails retain readable yarn proportions without repeating a shrunken width', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(root, 'assets/patterns/search-previews.js'), 'utf8'), context);
  let bitmap;
  const ctx = {
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
    putImageData: image => { bitmap = image; }
  };
  const canvas = { dataset: {}, getContext: () => ctx };
  // Journey Runner's dimensions; a short colored border precedes the long body.
  const draft = {
    warp: 272, picks: 1181, shafts: 1,
    patternColors: [
      { id: 'ground', value: '#eeeeee', thickness: 1 },
      { id: 'border', value: '#dd2244', thickness: 1 },
      { id: 'body', value: '#333333', thickness: 1 }
    ],
    threading: [Array(272).fill('ground')], tieup: [[false]],
    treadling: Array.from({ length: 1181 }, (_, pick) => [pick < 7 ? 'border' : 'body'])
  };
  context.renderPatternSearchPreview(canvas, { draft });
  const pixel = y => [...bitmap.data.slice(y * 240 * 4, y * 240 * 4 + 3)];
  assert.deepEqual(pixel(6), [221, 34, 68], 'the seven-pick border remains seven pixels tall');
  assert.deepEqual(pixel(7), [51, 51, 51]);
  assert.equal(canvas.dataset.repeatX, '1');
  assert.equal(canvas.dataset.repeatY, '1');

  draft.warp = draft.picks = 2;
  draft.threading = [['ground', 'ground']];
  draft.treadling = [['border'], ['body']];
  context.renderPatternSearchPreview(canvas, { draft });
  assert.ok(Number(canvas.dataset.repeatX) > 1, 'small swatches still repeat');
  assert.ok(Number(canvas.dataset.repeatY) > 1);
});

test('large library interlacement drafts use the same yarn renderer as small drafts', () => {
  const html = fs.readFileSync(path.join(root, 'pattern-library.html'), 'utf8');
  const start = html.indexOf('    function renderDrawdown(grid,');
  const end = html.indexOf('    function createVariantArticle(', start);
  let rendered;
  const context = vm.createContext({
    renderStyle: 'realistic', compactDrawdownCellThreshold: 60000,
    renderCompactDrawdown() { assert.fail('interlacement must retain its yarn renderer'); },
    renderRealisticDrawdown(...args) { rendered = args; }
  });
  vm.runInContext(html.slice(start, end), context);
  for (const draft of [{ warp: 8, picks: 8 }, { warp: 272, picks: 1181 }]) {
    const grid = {}, columns = [], rows = [];
    context.renderDrawdown(grid, draft, columns, rows);
    assert.deepEqual(rendered, [grid, draft, columns, rows]);
  }
});
