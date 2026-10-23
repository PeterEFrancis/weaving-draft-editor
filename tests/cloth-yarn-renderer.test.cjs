const { test } = require('node:test');
const assert = require('node:assert/strict');
const { ClothMeshBuilder } = require('../assets/cloth-renderer.js');

test('joined yarn materials render their widths and colors without a capped seam', () => {
  const nodes = [0, 1, 2, 3].map(y => ({ x: 0, y, z: 0 }));
  const builder = new ClothMeshBuilder();
  const simulation = { rows: 4, cols: 2, diameter: .38, yarns: [
    { kind: 'weft', diameter: .2, color: '#ff0000', nodes: nodes.slice(0, 2) },
    { kind: 'weft', diameter: .8, nodeDiameters: [.2, .8], nodeColors: [[1, 0, 0], [0, 0, 1]], nodes: nodes.slice(1, 3) },
    { kind: 'weft', diameter: .8, color: '#0000ff', nodes: nodes.slice(2) }
  ] };
  const mesh = builder.build(simulation);
  assert.equal(mesh.meshes.length, 3, 'one continuous tube has only its two genuine end caps');
  const ring = y => {
    const result = [];
    for (let i = 0; i < mesh.vertices.length; i += 9) if (mesh.vertices[i + 1] === y) result.push(mesh.vertices.slice(i, i + 9));
    return result;
  };
  for (const [y, radius, color] of [[0, .1, [1, 0, 0]], [3, .4, [0, 0, 1]]]) {
    const vertices = ring(y);
    assert(Math.abs(Math.max(...vertices.map(v => Math.hypot(v[0], v[2]))) - radius) < 1e-6);
    assert(vertices.every(v => color.every((value, axis) => v[axis + 6] === value)));
  }
  assert(ring(1.5).every(v => v[6] === .5 && v[8] === .5), 'edge turns interpolate the neighboring colors');
});
