const { test } = require('node:test');
const assert = require('node:assert/strict');
const ClothSimulation = require('../assets/cloth-simulation.js');
const draft = Array.from({ length: 4 }, (_, row) => Array.from({ length: 4 }, (_, col) => (row + col) % 2 === 0));
const positions = cloth => cloth.nodes.map(node => [node.x, node.y, node.z, node.px, node.py, node.pz]);

test('warp and weft tensions independently set their own loom prestrain', () => {
  const balanced = new ClothSimulation(draft, { warpTension: 1, weftTension: 1 });
  const warp = new ClothSimulation(draft, { warpTension: 4 });
  const weft = new ClothSimulation(draft, { weftTension: .5 });
  assert.equal(warp.warpStretch, .2);
  assert.equal(warp.weftStretch, balanced.weftStretch);
  assert.equal(weft.weftStretch, .025);
  assert.equal(weft.warpStretch, balanced.warpStretch);
});

test('balanced direct tensions preserve default geometry and relaxation', () => {
  const legacy = new ClothSimulation(draft);
  const direct = new ClothSimulation(draft, { warpTension: 1, weftTension: 1 });
  assert.deepEqual(positions(direct), positions(legacy));
  legacy.release(); direct.release();
  for (let i = 0; i < 3; i++) { legacy.step(); direct.step(); }
  assert.deepEqual(positions(direct), positions(legacy));
  assert.deepEqual(direct.getMetrics(), legacy.getMetrics());
});

test('tension does not prescribe the initial crimp shape', () => {
  const warp = new ClothSimulation(draft, { warpTension: 4, weftTension: 1 });
  const weft = new ClothSimulation(draft, { warpTension: 1, weftTension: 4 });
  assert.deepEqual(positions(warp), positions(weft));
  assert.notEqual(warp.warpStretch, weft.warpStretch);
  assert.notEqual(warp.weftStretch, weft.weftStretch);
});

test('zero tension in either or both families remains finite', () => {
  for (const [warpTension, weftTension] of [[0, 1], [1, 0], [0, 0]]) {
    const cloth = new ClothSimulation(draft, { warpTension, weftTension });
    assert.equal(cloth.warpStretch, .05 * warpTension);
    assert.equal(cloth.weftStretch, .05 * weftTension);
    cloth.release();
    for (let i = 0; i < 3; i++) cloth.step();
    assert(positions(cloth).flat().every(Number.isFinite));
    assert(Object.values(cloth.getMetrics()).every(Number.isFinite));
  }
});
