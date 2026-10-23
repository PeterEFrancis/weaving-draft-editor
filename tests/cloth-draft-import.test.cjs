const { test } = require('node:test');
const assert = require('node:assert/strict');
const { parse } = require('../assets/cloth-draft-import.js');
const targetDrawdown = [[1, 0, 1], [0, 1, 0]];
const state = { warp: 3, picks: 2, targetDrawdown };
const coloredDraft = {
  format: 'weaving-draft-data', version: 3, meta: { draftName: 'Colored yarn sizes' },
  draft: {
    shafts: 2, treadles: 2, warp: 3, picks: 2,
    patternColors: [{ id: 'red', value: '#CC2233', thickness: 2 }, { id: 'blue', value: '#2255cc', thickness: .5 }, { id: 'gold', value: '#ddb122', thickness: 1 }],
    threading: [['red', 0, 'blue'], [0, 'blue', 0]],
    treadling: [['gold', 0], ['red', 'red']], tieup: [[1, 0], [0, 1]]
  }
};

test('WDD uses structural lift plan and per-thread colors and thicknesses', () => {
  const result = parse(JSON.stringify(coloredDraft));
  assert.equal(result.name, 'Colored yarn sizes');
  assert.deepEqual(result.draft, [[true, false, true], [true, true, true]], 'all pressed treadles contribute to the shed');
  assert.deepEqual(result.yarns, {
    warp: [{ color: '#cc2233', thickness: 2 }, { color: '#2255cc', thickness: .5 }, { color: '#2255cc', thickness: .5 }],
    weft: [{ color: '#ddb122', thickness: 1 }, { color: '#cc2233', thickness: 2 }]
  });
});

test('WDD rejects missing yarn assignments and invalid palette references', () => {
  for (const value of [0, 'missing']) {
    const data = structuredClone(coloredDraft);
    data.draft.threading[0][0] = value;
    assert.throws(() => parse(JSON.stringify(data)), /yarn assignments/);
  }
});

test('native WDI imports the current drawdown without reversing ends or picks', () => {
  const result = parse(JSON.stringify({ meta: { kind: 'weaving-inverse-draft', version: 1, draftName: 'Fíl d’été' }, state, history: { stack: [{ targetDrawdown: [[0, 0], [0, 0]] }] } }));
  assert.equal(result.name, 'Fíl d’été');
  assert.deepEqual(result.draft, [[true, false, true], [false, true, false]]);
  assert.deepEqual(targetDrawdown, [[1, 0, 1], [0, 1, 0]]);
});

test('legacy raw states support boolean cells and absent dimensions', () => {
  assert.deepEqual(parse(JSON.stringify({ targetDrawdown: [[true, false], [false, true]] })), {
    name: 'Custom draft', draft: [[true, false], [false, true]]
  });
});

test('invalid or unrelated files are rejected', () => {
  for (const data of ['not json', 'null', '{}', JSON.stringify({ meta: { kind: 'another-format' }, state })]) {
    assert.throws(() => parse(data), /WDI/);
  }
});

test('ragged, nonbinary and undersized drawdowns are rejected', () => {
  for (const matrix of [[[1, 0], [1]], [[1, 2], [0, 1]], [[1, '0'], [0, 1]], [[1, null], [0, 1]], [[1, 0]], [[1], [0]]]) {
    assert.throws(() => parse(JSON.stringify({ targetDrawdown: matrix })), /WDI/);
  }
});

test('declared dimensions must match the actual grid', () => {
  for (const mismatch of [{ warp: 2 }, { picks: 3 }, { warp: true }]) {
    assert.throws(() => parse(JSON.stringify({ ...state, ...mismatch })), /dimensions/);
  }
});

test('large drafts are rejected without silently cropping their cells', () => {
  for (const [rows, cols] of [[2, 2049], [2, 65], [65, 2]]) {
    assert.throws(() => parse(JSON.stringify({ targetDrawdown: Array.from({ length: rows }, () => Array(cols).fill(0)) })), /64.*4,096/);
  }
});
