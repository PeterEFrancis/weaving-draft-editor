const { test } = require('node:test');
const assert = require('node:assert/strict');
const ClothSimulation = require('../assets/cloth-simulation.js');

// User's reference: plain upper-left/lower-right blocks, floats in the others.
const huck = [
  '1010101010', '0101011111', '1010101010', '0101011111', '1010101010',
  '0101010101', '1111101010', '0101010101', '1111101010', '0101010101'
].map(row => [...row].map(cell => cell === '1'));

function assertClearance(cloth) {
  cloth._refreshContacts();
  for (const [a, b] of cloth.contactPairs) {
    const diameter = a.radius + b.radius;
    assert(cloth._closest(a, b, {}) >= (diameter * .985) ** 2, 'nonadjacent yarn surfaces must not overlap');
  }
}

function assertAnchors(cloth) {
  for (const node of cloth.fixedNodes) {
    assert(node.pinned);
    assert.deepEqual([node.x, node.y, node.z], [node.home.x, node.home.y, node.home.z]);
  }
}

test('the draft has no added border and both yarn families are connected by edge returns', () => {
  const cloth = new ClothSimulation(huck);
  assert.equal(cloth.rows, huck.length);
  assert.equal(cloth.cols, huck[0].length);
  assert(cloth.yarns.every(yarn => yarn.kind === 'warp' || yarn.kind === 'weft'));
  for (const [kind, strands] of [['warp', cloth.warpYarns], ['weft', cloth.weftYarns]]) {
    const neighbors = new Map();
    for (const { a, b, yarn } of cloth.edges) if (yarn.kind === kind) {
      if (!neighbors.has(a)) neighbors.set(a, []);
      if (!neighbors.has(b)) neighbors.set(b, []);
      neighbors.get(a).push(b); neighbors.get(b).push(a);
    }
    const seen = new Set(), pending = [strands[0].nodes[0]];
    while (pending.length) {
      const node = pending.pop();
      if (seen.has(node)) continue;
      seen.add(node); pending.push(...neighbors.get(node));
    }
    assert(strands.every(yarn => yarn.nodes.every(node => seen.has(node))), `${kind} returns must physically connect every strand`);
  }
});

test('huck relaxes through yarn motion while preserving anchors and collision clearance', () => {
  const cloth = new ClothSimulation(huck, { diameter: .38, warpEnds: 'fixed', weftEnds: 'connected' });
  const initial = cloth.nodes.map(node => [node.x, node.y, node.z]);
  cloth.release();
  for (let step = 0; step < 120; step++) cloth.step(1 / 120);
  assert(cloth.nodes.every(node => [node.x, node.y, node.z].every(Number.isFinite)));
  assert(cloth.nodes.some((node, i) => Math.hypot(node.x - initial[i][0], node.y - initial[i][1], node.z - initial[i][2]) > .05), 'the cloth must relax visibly');
  assertAnchors(cloth);
  assertClearance(cloth);
});

test('an unbound outer warp disengages while an interlaced outer warp remains engaged', () => {
  const edgeState = interlaced => {
    const draft = Array.from({ length: 6 }, (_, row) => Array.from({ length: 6 }, (_, col) =>
      col === 5 && !interlaced ? false : (row + col) % 2 === 0));
    const cloth = new ClothSimulation(draft, { diameter: .38, warpEnds: 'fixed', weftEnds: 'connected', warpTension: 1, weftTension: 4, friction: 0 });
    cloth.release();
    for (let step = 0; step < 720; step++) cloth.step(1 / 120);
    assert(cloth.nodes.every(node => [node.x, node.y, node.z].every(Number.isFinite)));
    assertAnchors(cloth);
    assertClearance(cloth);
    const outer = cloth.warpYarns.at(-1).nodes;
    const projectedCrossings = Array.from({ length: 6 }, (_, row) => cloth.getCrossing(row, 5)).filter(Boolean).length;
    const deflection = Math.max(...outer.map(node => Math.hypot(node.x - 2.5, node.z)));
    return { projectedCrossings, deflection };
  };
  const free = edgeState(false), woven = edgeState(true);
  assert.equal(free.projectedCrossings, 0, 'all-orange edge must be allowed to lose contact');
  assert(free.deflection < .03, 'unsupported outer warp must straighten under its own tension');
  assert(woven.projectedCrossings > 0, 'alternating edge must retain actual interlacement');
  assert(woven.deflection > free.deflection + .1, 'interlaced edge must remain loaded by the weft');
});

test('straight yarn with unequal material intervals has no artificial bending force', () => {
  const cloth = new ClothSimulation([[true, false], [false, true]]);
  const nodes = cloth.nodes.slice(0, 3);
  const coordinates = [0, 1, 3];
  nodes.forEach((node, i) => Object.assign(node, { x: coordinates[i], y: 2, z: 1, px: coordinates[i], py: 2, pz: 1 }));
  cloth.nodes = nodes;
  cloth.edges = [];
  cloth.physicalYarns = [{ nodes, materialCoordinates: coordinates }];
  cloth.release();
  cloth.contactsDirty = true;
  for (let i = 0; i < 5; i++) cloth._project(.1);
  nodes.forEach((node, i) => assert(Math.hypot(node.x - coordinates[i], node.y - 2, node.z - 1) < 1e-12, 'a straight rod must remain straight without external loads'));
});

test('remote sections of one yarn collide without repelling adjacent sections', () => {
  const cloth = new ClothSimulation([[true, false], [false, true]], { diameter: .38 });
  const piece = cloth.warpYarns[0];
  const edges = cloth.edges.filter(edge => edge.yarn === piece);
  const [first, adjacent] = edges, remote = edges.at(-1);
  // Isolate a self-contact patch from the rest of the sample. The touching
  // capsules retain their original material adjacency on the same yarn.
  cloth.edges = [first, adjacent, remote];
  const place = (node, x, y, z) => Object.assign(node, { x, y, z, px: x, py: y, pz: z });
  place(first.a, -.5, 0, 0); place(first.b, .5, 0, 0);
  place(adjacent.b, 1.5, 0, 0);
  place(remote.a, 0, -.5, .1); place(remote.b, 0, .5, .1);
  cloth.release();
  cloth.contactsDirty = true;
  assert(cloth._closest(first, remote, {}) < cloth.diameter ** 2);
  for (let i = 0; i < 16; i++) cloth._contact();
  assert(cloth._closest(first, remote, {}) >= (cloth.diameter * .99) ** 2, 'distant sections of the same yarn must physically separate');
  assert.equal(cloth._closest(first, adjacent, {}), 0, 'neighboring capsules must retain their shared joint');
  assert.deepEqual([adjacent.b.x, adjacent.b.y, adjacent.b.z], [1.5, 0, 0], 'local adjacency must not generate spurious repulsion');
});

test('contact friction resists loaded slip while preserving common motion and momentum', () => {
  const cloth = new ClothSimulation([[true, false], [false, true]], { friction: 1 });
  cloth.release();
  const contact = common => [[0, -0.2, 0.4], [0, 0.2, 0.4], [-0.2, 0, -0.4], [0.2, 0, -0.4]]
    .map(([x, y, z], i) => ({ x: x + (common || i < 2 ? 0.1 : 0), y, z, px: x, py: y, pz: z, pinned: false }));
  const slip = nodes => (nodes[0].x + nodes[1].x - nodes[2].x - nodes[3].x) / 2;
  const center = nodes => nodes.reduce((sum, n) => sum + n.x, 0) / 4;
  const apply = (nodes, load) => cloth._friction(...nodes, 0.5, 0.5, 0, 0, 1, load);
  const translating = contact(true), original = translating.map(n => n.x);
  apply(translating, 0.05);
  assert.deepEqual(translating.map(n => n.x), original, 'friction must not oppose rigid cloth translation');
  const unloaded = contact(false);
  apply(unloaded, 0);
  assert(Math.abs(slip(unloaded) - 0.1) < 1e-10, 'unloaded contact must not stick');
  const loaded = contact(false), before = slip(loaded), massCenter = center(loaded);
  apply(loaded, 0.05);
  assert(slip(loaded) < before && slip(loaded) >= before - 0.05, 'loaded contact must resist slip within its load cap');
  assert(Math.abs(center(loaded) - massCenter) < 1e-10);
  cloth.friction = 0;
  const free = contact(false);
  apply(free, 0.05);
  assert(Math.abs(slip(free) - 0.1) < 1e-10, 'turning friction off must allow sliding immediately');
});
