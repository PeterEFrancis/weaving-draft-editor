const { test } = require('node:test');
const assert = require('node:assert/strict');
const ClothSimulation = require('../assets/cloth-simulation.js');
const solve = require('../assets/cloth-equilibrium.js');

test('progress snapshots preserve the solver result and stop at its iteration limit', () => {
  const draft = [[true, false], [false, true]];
  const plain = new ClothSimulation(draft), animated = new ClothSimulation(draft);
  const frames = [];
  const expected = solve(plain, { maxIterations: 32 });
  const actual = solve(animated, { maxIterations: 32, onProgress: (cloth, { iterations }) => {
    frames.push({ iterations, positions: cloth.nodes.map(node => [node.x, node.y, node.z]) });
  } });
  assert.deepEqual(actual, expected);
  assert.deepEqual(animated.nodes, plain.nodes);
  assert.deepEqual(frames.map(frame => frame.iterations), [0, 4, 8, 12, 16, 20, 24, 28, 32]);
  assert.notDeepEqual(frames[0].positions, frames.at(-1).positions, 'snapshots must show actual physical motion');
});
