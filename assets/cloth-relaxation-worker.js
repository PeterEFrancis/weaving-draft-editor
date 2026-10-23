/* Stream actual relaxation states off the UI thread, then stop at the result. */
'use strict';

// The simulation also runs as a classic browser script.
self.window = self;
importScripts('cloth-simulation.js?v=wdi-yarns-1', 'cloth-equilibrium.js?v=visual-settling-1');

self.onmessage = ({ data: { id, draft, options } }) => {
  try {
    const simulation = new ClothSimulation(draft, options);
    const indices = new Map(simulation.nodes.map((node, index) => [node, index]));
    const render = {
      rows: simulation.rows, cols: simulation.cols, diameter: simulation.diameter, loom: simulation.loom,
      yarns: simulation.yarns.map(({ kind, diameter, color, nodeDiameters, nodeColors, nodes }) =>
        ({ kind, diameter, color, nodeDiameters, nodeColors, nodes: nodes.map(node => indices.get(node)) }))
    };
    const snapshot = () => {
      // Transfer a copy, never a buffer owned by the live simulation.
      const positions = new Float64Array(simulation.nodes.length * 3);
      simulation.nodes.forEach((node, index) => {
        if (![node.x, node.y, node.z].every(Number.isFinite)) throw new Error('The cloth preview could not be calculated.');
        positions.set([node.x, node.y, node.z], index * 3);
      });
      return positions;
    };
    let lastFrame = -Infinity, renderSent = false;
    const relaxation = solveClothEquilibrium(simulation, { onProgress: (_, { iterations }) => {
      const now = performance.now();
      if (now - lastFrame < 1000 / 30) return;
      lastFrame = now;
      const positions = snapshot();
      self.postMessage({ type: 'frame', id, positions, metrics: simulation.getMetrics(), iterations, ...(renderSent ? {} : { render }) }, [positions.buffer]);
      renderSent = true;
    } });
    const positions = snapshot();
    self.postMessage({
      type: 'result', id, positions,
      metrics: simulation.getMetrics(),
      converged: relaxation.converged,
      visuallySettled: relaxation.visuallySettled,
      iterations: relaxation.iterations,
      residual: relaxation.residual,
      penetration: relaxation.penetration,
      render
    }, [positions.buffer]);
  } catch (error) {
    self.postMessage({ type: 'error', id, message: error.message || 'The cloth preview could not be calculated.' });
  }
};
