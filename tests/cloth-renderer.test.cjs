const { test } = require('node:test');
const assert = require('node:assert/strict');
const ClothSimulation = require('../assets/cloth-simulation.js');
const { ClothMeshBuilder } = require('../assets/cloth-renderer.js');

test('large connected weft meshes retain local triangles across 16-bit index boundaries', () => {
  const cloth = new ClothSimulation(Array.from({ length: 16 }, (_, row) => Array.from({ length: 30 }, (_, col) => (row + col) % 2 === 0)), {
    warpEnds: 'fixed', weftEnds: 'connected', diameter: .38
  });
  const builder = new ClothMeshBuilder(), weft = builder._paths(cloth).find(yarn => yarn.kind === 'weft');
  assert.ok(weft.nodes.length * 2 * 12 > 65535, 'exercise the reported long connected weft');
  const mesh = builder.build({ ...cloth, loom: null, yarns: [weft] });
  const [first, second] = mesh.meshes;
  const firstVertexEnd = second.vertexStart * 9;
  assert.deepEqual(mesh.vertices.slice(firstVertexEnd - 12 * 9, firstVertexEnd), mesh.vertices.slice(firstVertexEnd, firstVertexEnd + 12 * 9), 'chunk join repeats the exact surface ring');
  let longestEdge = 0;
  for (let i = 1; i < weft.nodes.length; i++) {
    const a = weft.nodes[i - 1], b = weft.nodes[i];
    longestEdge = Math.max(longestEdge, Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z));
  }
  const limit = longestEdge / 2 + cloth.diameter + 1e-5;
  for (const part of mesh.meshes) for (let i = part.indexStart; i < part.indexStart + part.count; i += 3) {
    const indices = [0, 1, 2].map(offset => mesh.indices[i + offset]);
    assert.ok(indices.every(index => index < 60000), 'indices stay within a safe local chunk');
    for (let corner = 0; corner < 3; corner++) {
      const a = (part.vertexStart + indices[corner]) * 9, b = (part.vertexStart + indices[(corner + 1) % 3]) * 9;
      assert.ok(Math.hypot(...[0, 1, 2].map(axis => mesh.vertices[a + axis] - mesh.vertices[b + axis])) <= limit, 'no wrapped index can create a diagonal triangle');
    }
  }
  assert.ok(first.count > 0 && second.count > 0);
});
