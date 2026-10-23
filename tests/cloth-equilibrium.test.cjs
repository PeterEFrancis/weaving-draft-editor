const { test } = require('node:test');
const assert = require('node:assert/strict');
const ClothSimulation = require('../assets/cloth-simulation.js');
const solve = require('../assets/cloth-equilibrium.js');

test('the displayed equilibrium permits an unbound edge to detach under fixed pretension', () => {
  const draft = Array.from({ length: 8 }, (_, row) => Array.from({ length: 8 }, (_, col) => col === 7 ? false : (row + col) % 2 === 0));
  const cloth = new ClothSimulation(draft, { diameter: .38, warpEnds: 'fixed', weftEnds: 'connected', warpTension: 4, weftTension: 4, friction: 0 });
  const result = solve(cloth);
  assert(Number.isFinite(result.residual));
  assert(result.penetration < cloth.diameter * .015, 'final output must resolve yarn collisions');
  for (let row = 0; row < 8; row++) assert.equal(cloth.getCrossing(row, 7), null);
  assert(Math.max(...cloth.warpYarns.at(-1).nodes.map(node => Math.hypot(node.x - 3.5, node.z))) < .03);
  for (const node of cloth.fixedNodes) assert.deepEqual([node.x, node.y, node.z], [node.home.x, node.home.y, node.home.z]);
});

test('a calculation limit is reported without claiming convergence', () => {
  const cloth = new ClothSimulation([[true, false], [false, true]], { warpEnds: 'fixed' });
  const result = solve(cloth, { maxIterations: 1 });
  assert.equal(result.iterations, 1);
  assert.equal(result.converged, false);
  assert.equal(result.visuallySettled, false);
  assert(Number.isFinite(result.penetration));
});

function movingSample(position, penetration = 0) {
  let step = 0;
  const node = { x: 0, y: 0, z: 0 };
  return {
    nodes: [node], diameter: .4, motion: 0,
    contactPairs: penetration ? [[{ radius: .2 }, { radius: .2 }]] : [],
    release() {}, _refreshContacts() {}, _closest() { return (.4 - penetration) ** 2; },
    step() {
      const next = position(++step);
      this.motion = Math.abs(next - node.x) * 120;
      node.x = next;
    }
  };
}

test('subpixel contact jitter can settle visually without claiming numerical convergence', () => {
  const result = solve(movingSample(step => step % 2 ? .0005 : -.0005));
  assert.equal(result.visuallySettled, true);
  assert.equal(result.converged, false);
  assert.equal(result.iterations, 256);
});

test('persistent drift and oscillations are not mistaken for visual rest', () => {
  for (const position of [step => step * .0003, step => .04 * Math.sin(step * Math.PI / 64)]) {
    const result = solve(movingSample(position), { maxIterations: 384 });
    assert.equal(result.visuallySettled, false);
    assert.equal(result.converged, false);
    assert.equal(result.iterations, 384);
  }
});

test('a stable shape still has to resolve its yarn contacts', () => {
  const result = solve(movingSample(() => 0, .004), { maxIterations: 384 });
  assert.equal(result.visuallySettled, false);
  assert.equal(result.converged, false);
});
