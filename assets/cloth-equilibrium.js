/* Contact-based relaxation with optional intermediate snapshots. */
(function (root) {
  'use strict';

  function solveClothEquilibrium(simulation, { maxIterations = 720, tolerance = .0001, settlingTolerance = .02, onProgress } = {}) {
    simulation.release();
    let iterations = 0, residual = Infinity, penetration = Infinity, stable = 0, visualStable = 0, excursion = 0, shapeChange = Infinity;
    const nodes = simulation.nodes;
    const reference = new Float64Array(nodes.length * 3);
    const saveShape = () => nodes.forEach((node, i) => reference.set([node.x, node.y, node.z], i * 3));
    saveShape();
    if (onProgress) onProgress(simulation, { iterations: 0 });
    for (; iterations < maxIterations; iterations++) {
      simulation.step(1 / 120);
      residual = simulation.motion / 120;
      for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        if (![node.x, node.y, node.z].every(Number.isFinite)) throw new Error('Yarn relaxation became unstable.');
        excursion = Math.max(excursion, Math.hypot(node.x - reference[i * 3], node.y - reference[i * 3 + 1], node.z - reference[i * 3 + 2]));
      }
      if (onProgress && (iterations + 1) % 4 === 0) onProgress(simulation, { iterations: iterations + 1 });
      if ((iterations + 1) % 16 && iterations + 1 < maxIterations) continue;
      // Separation is legitimate: neither draft crossings nor flat spacing
      // are acceptance criteria. Fixed yarns may retain tensile strain.
      simulation._refreshContacts();
      penetration = 0;
      for (const [a, b] of simulation.contactPairs) {
        penetration = Math.max(penetration, a.radius + b.radius - Math.sqrt(simulation._closest(a, b, {})));
      }
      stable = residual < tolerance && penetration < simulation.diameter * .005 ? stable + 1 : 0;
      if ((iterations + 1) % 128 === 0) {
        // Two one-second windows of subpixel shape change are sufficient for
        // a preview. Track the whole excursion, not just the final position,
        // so oscillation and persistent drift cannot masquerade as rest.
        shapeChange = excursion;
        visualStable = shapeChange < settlingTolerance && penetration < simulation.diameter * .005 ? visualStable + 1 : 0;
        saveShape();
        excursion = 0;
      }
      if (stable >= 3 || visualStable >= 2) { iterations++; break; }
    }
    simulation.motion = residual * 120;
    return { iterations, converged: stable >= 3, visuallySettled: visualStable >= 2, residual, penetration, shapeChange };
  }

  root.solveClothEquilibrium = solveClothEquilibrium;
  if (typeof module !== 'undefined' && module.exports) module.exports = solveClothEquilibrium;
})(typeof self === 'undefined' ? globalThis : self);
