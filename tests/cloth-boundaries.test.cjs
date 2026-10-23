const { test } = require('node:test');
const assert = require('node:assert/strict');
const ClothSimulation = require('../assets/cloth-simulation.js');
const solve = require('../assets/cloth-equilibrium.js');

test('warp and weft independently connect or remain anchored to the square loom', () => {
  for (const [rows, cols] of [[4, 4], [3, 5]]) {
    const draft = Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, (_, c) => (r + c) % 2 === 0));
    for (const warpEnds of ['connected', 'fixed']) for (const weftEnds of ['connected', 'fixed']) {
      const cloth = new ClothSimulation(draft, { warpEnds, weftEnds });
      const fixedFamilies = Number(warpEnds === 'fixed') + Number(weftEnds === 'fixed');
      const loomPresent = fixedFamilies > 0;
      const anchors = (warpEnds === 'fixed' ? cols * 2 : loomPresent ? 2 : 0)
        + (weftEnds === 'fixed' ? rows * 2 : loomPresent ? 2 : 0);
      assert.equal(cloth.fixedNodes.size, anchors);
      assert.equal(Boolean(cloth.loom), fixedFamilies > 0);
      for (const [kind, mode, count] of [['warp', warpEnds, cols], ['weft', weftEnds, rows]]) {
        assert.equal(cloth.yarns.filter(yarn => yarn.kind === kind).length, mode === 'fixed' ? count * 3 : count * 2 - 1 + (loomPresent ? 2 : 0));
        const degrees = new Map();
        for (const { a, b, yarn } of cloth.edges) if (yarn.kind === kind) {
          degrees.set(a, (degrees.get(a) || 0) + 1);
          degrees.set(b, (degrees.get(b) || 0) + 1);
        }
        const tips = [...degrees].filter(([, degree]) => degree === 1).map(([node]) => node);
        assert.equal(tips.length, mode === 'fixed' ? count * 2 : 2);
        for (const node of tips) assert.equal(cloth.fixedNodes.has(node), loomPresent, 'every loose tip must attach to the visible loom');
      }
      solve(cloth);
      assert(cloth.nodes.every(node => [node.x, node.y, node.z].every(Number.isFinite)));
      for (const node of cloth.fixedNodes) {
        assert(node.pinned);
        assert.deepEqual([node.x, node.y, node.z], [node.home.x, node.home.y, node.home.z]);
        assert.equal(node.z, 0);
        assert.equal(Math.max(Math.abs(node.x), Math.abs(node.y)), cloth.loom.halfSize);
      }
      for (const node of cloth.nodes) if (!cloth.fixedNodes.has(node)) assert.equal(node.pinned, false);
    }
  }
});
