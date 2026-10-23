const { test } = require('node:test');
const assert = require('node:assert/strict');
const ClothSimulation = require('../assets/cloth-simulation.js');
const draft = [[true, false], [false, true]];
const yarns = {
  warp: [{ color: '#ff0000', thickness: 1 }, { color: '#0000ff', thickness: .5 }],
  weft: [{ color: '#00ff00', thickness: .25 }, { color: '#ffff00', thickness: .75 }]
};
const positions = cloth => cloth.nodes.map(node => [node.x, node.y, node.z]);

test('imported widths determine contact radii, while edge returns taper into both neighbors', () => {
  const cloth = new ClothSimulation(draft, { diameter: .4, yarns, warpEnds: 'fixed', weftEnds: 'connected' });
  assert.deepEqual(cloth.mainYarns.map(yarn => yarn.diameter), [.4, .2, .1, .30000000000000004]);
  assert.deepEqual(cloth.mainYarns.map(yarn => yarn.color), ['#ff0000', '#0000ff', '#00ff00', '#ffff00']);
  for (const yarn of cloth.mainYarns) {
    assert(yarn.edges.every(edge => edge.radius === yarn.diameter / 2));
  }
  const turn = cloth.yarns.find(yarn => yarn.nodeDiameters);
  assert.equal(turn.nodeDiameters[0], cloth.weftYarns[0].diameter);
  assert.equal(turn.nodeDiameters.at(-1), cloth.weftYarns[1].diameter);
  assert.deepEqual(turn.nodeColors[0], [0, 1, 0]);
  assert.deepEqual(turn.nodeColors.at(-1), [1, 1, 0]);
  const main = new Set(cloth.mainYarns);
  const tails = cloth.yarns.filter(yarn => !main.has(yarn) && !yarn.nodeDiameters);
  assert(tails.every(yarn => cloth.mainYarns.some(source => source.diameter === yarn.diameter && source.color === yarn.color && source.nodes.some(node => yarn.nodes.includes(node)))));
  cloth.release();
  for (let i = 0; i < 8; i++) cloth.step();
  assert(positions(cloth).flat().every(Number.isFinite));
});

test('capsule clearance uses the actual opposing yarn sizes', () => {
  const cloth = new ClothSimulation(draft, { diameter: .4, yarns });
  const first = cloth.warpYarns[0].edges[0], second = cloth.weftYarns[0].edges[0];
  cloth.edges = [first, second];
  const place = (node, x, y, z) => Object.assign(node, { x, y, z, px: x, py: y, pz: z });
  place(first.a, -.5, 0, 0); place(first.b, .5, 0, 0);
  place(second.a, 0, -.5, .2); place(second.b, 0, .5, .2);
  cloth.release(); cloth.contactsDirty = true;
  for (let i = 0; i < 16; i++) cloth._contact();
  assert(cloth._closest(first, second, {}) >= ((first.radius + second.radius) * .999) ** 2);
});

test('colors and unit thickness preserve existing mechanics exactly', () => {
  const plain = new ClothSimulation(draft);
  const colored = new ClothSimulation(draft, { yarns: Object.fromEntries(Object.entries(yarns).map(([kind, threads]) => [kind, threads.map(yarn => ({ ...yarn, thickness: 1 }))])) });
  assert.deepEqual(positions(colored), positions(plain));
  plain.release(); colored.release();
  for (let i = 0; i < 3; i++) { plain.step(); colored.step(); }
  assert.deepEqual(positions(colored), positions(plain));
});
