/* Build yarn meshes away from the UI; buffers are transferred, never copied. */
'use strict';
importScripts('cloth-renderer.js?v=wdi-yarns-1');
const builder = new ClothMeshBuilder();
self.onmessage = ({ data }) => {
  try {
    const mesh = builder.setState(data);
    self.postMessage({ id: data.id, mesh }, [mesh.vertices.buffer, mesh.indices.buffer]);
  } catch (error) {
    self.postMessage({ type: 'error', id: data.id, message: error.message || 'The cloth mesh could not be built.' });
  }
};
