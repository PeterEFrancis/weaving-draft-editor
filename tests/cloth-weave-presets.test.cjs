const { test } = require('node:test');
const assert = require('node:assert/strict');
const presets = require('../assets/cloth-weave-presets.js');

test('double cloth has two alternating plain-weave layers in a 16 by 16 sample', () => {
  const draft = presets.doubleCloth();
  assert.equal(draft.length, 16);
  assert(draft.every(row => row.length === 16));
  for (let row = 0; row < 16; row++) for (let col = 0; col < 16; col++) {
    if (row % 2 !== col % 2) assert.equal(draft[row][col], col % 2 === 0, 'front yarns must stay above back yarns');
    else {
      if (row + 2 < 16) assert.notEqual(draft[row][col], draft[row + 2][col]);
      if (col + 2 < 16) assert.notEqual(draft[row][col], draft[row][col + 2]);
    }
  }
});

test('deflected double cloth interlocks paired plain-weave systems with reversing floats', () => {
  const draft = presets.deflectedDoubleCloth();
  assert.equal(draft.length, 16);
  assert(draft.every(row => row.length === 16));
  for (let br = 0; br < 4; br++) for (let bc = 0; bc < 4; bc++) {
    const block = draft.slice(br * 4, br * 4 + 4).map(row => row.slice(bc * 4, bc * 4 + 4));
    if (br % 2 === bc % 2) {
      for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) assert.equal(block[r][c], (r + c) % 2 === 0);
    } else assert(block.flat().every(value => value === block[0][0]), 'cross-system blocks must float');
  }
  for (const row of [0, 4, 8, 12]) {
    const floats = [0, 4, 8, 12].filter(col => (col / 4) % 2 !== (row / 4) % 2);
    assert.notEqual(draft[row][floats[0]], draft[row][floats[1]], 'systems must exchange above/below rather than remain separate layers');
  }
});
