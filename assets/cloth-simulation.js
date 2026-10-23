/* Qualitative elastic yarns meet through unilateral capsule contact. Each yarn
 * family either returns through connected edge loops or stays anchored to a
 * square loom. No additional weave is added around the supplied draft.
 * Six straight physics segments per crossing interval resolve crimp/contact;
 * yarn lengths contract, with geometric bending and capsule yarn contact.
 * Contact friction resists material slip; gravity and calibrated fiber properties are omitted.
 */
(function (root) {
  'use strict';

  class ClothSimulation {
    constructor(draft, { diameter = .38, stretch = .05, bending = .2, friction = 0, tensionRatio = 1, warpTension, weftTension, warpEnds = 'connected', weftEnds = 'connected', yarns } = {}) {
      if (!draft.length || !draft[0].length || draft.some(row => row.length !== draft[0].length)) {
        throw new Error('The draft must be a nonempty rectangular array.');
      }
      this.coreRows = draft.length;
      this.coreCols = draft[0].length;
      this.border = 0;
      this.rows = this.coreRows;
      this.cols = this.coreCols;
      this.segmentsPerCrossing = 6;
      this.warpEnds = warpEnds === 'fixed' ? 'fixed' : 'connected';
      this.weftEnds = weftEnds === 'fixed' ? 'fixed' : 'connected';
      this.fixedNodes = new Set();
      this.loom = this.warpEnds === 'fixed' || this.weftEnds === 'fixed' ? { halfSize: Math.max(this.rows - 1, this.cols - 1) / 2 + 1.5 } : null;
      this.diameter = Math.max(.2, Math.min(.95, diameter));
      const materials = Object.fromEntries([['warp', this.cols], ['weft', this.rows]].map(([kind, count]) => [kind,
        Array.from({ length: count }, (_, index) => {
          const supplied = yarns?.[kind]?.[index], thickness = Number(supplied?.thickness ?? 1);
          return { diameter: this.diameter * (Number.isFinite(thickness) && thickness > 0 ? thickness : 1),
            ...(supplied?.color ? { color: supplied.color } : {}) };
        })]));
      this.minimumDiameter = Math.min(this.diameter, ...materials.warp.map(yarn => yarn.diameter), ...materials.weft.map(yarn => yarn.diameter));
      const uniformDiameter = [...materials.warp, ...materials.weft].every(yarn => yarn.diameter === this.diameter);
      this.stretch = Math.max(0, Math.min(.18, stretch));
      this.bending = Math.max(0, Math.min(1, bending));
      this.friction = Math.max(0, Math.min(1, friction));
      this.tensionRatio = Math.max(1 / 16, Math.min(16, tensionRatio));
      // Tension changes material prestrain, not a prescribed crimp shape.
      if (warpTension !== undefined || weftTension !== undefined) {
        // Each relative tension independently supplies 5% loom prestrain per
        // unit. Neither family's strain changes when the other is adjusted.
        this.warpTension = Math.max(0, Math.min(4, warpTension ?? 1));
        this.weftTension = Math.max(0, Math.min(4, weftTension ?? 1));
        this.warpStretch = .05 * this.warpTension;
        this.weftStretch = .05 * this.weftTension;
        this.stretch = (this.warpStretch + this.weftStretch) / 2;
        this.tensionRatio = this.weftTension ? this.warpTension / this.weftTension : this.warpTension ? Infinity : 1;
      } else {
        // Retain the legacy mean-prestrain/ratio API and its arithmetic.
        this.warpStretch = 2 * this.stretch * this.tensionRatio / (1 + this.tensionRatio);
        this.weftStretch = 2 * this.stretch / (1 + this.tensionRatio);
        this.warpTension = this.warpStretch / .05;
        this.weftTension = this.weftStretch / .05;
      }
      this.nodes = [];
      this.yarns = [];
      this.crossings = [];
      this.edges = [];
      this.contactPairs = [];
      this.contactSkin = .25;
      this.released = false;
      this.elapsed = 0;
      this.motion = 0;
      const sample = draft.map(row => row.map(Boolean));
      const warp = [], weft = [];
      const addNode = (x, y, z, pinned = false) => {
        const node = { x, y, z, px: x, py: y, pz: z, pinned, home: { x, y, z } };
        this.nodes.push(node);
        return node;
      };
      const addYarn = (kind, nodes, material = { diameter: this.diameter }) => {
        const yarn = { kind, nodes, ...material, stretch: kind === 'warp' ? this.warpStretch : this.weftStretch, id: this.yarns.length };
        this.yarns.push(yarn);
        for (let k = 1; k < nodes.length; k++) {
          const a = nodes[k - 1], b = nodes[k];
          const edgeDiameter = yarn.nodeDiameters ? Math.max(yarn.nodeDiameters[k - 1], yarn.nodeDiameters[k]) : yarn.diameter;
          this.edges.push({ a, b, yarn, index: k - 1, radius: edgeDiameter / 2, lambda: 0, length: Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z) / (1 + yarn.stretch) });
        }
        return yarn;
      };
      const addChain = (kind, index, count, signs) => {
        const nodes = [], crossings = [], segments = this.segmentsPerCrossing;
        const material = materials[kind][index], opposing = materials[kind === 'warp' ? 'weft' : 'warp'];
        for (let k = 0; k <= (count - 1) * segments; k++) {
          const coordinate = k / segments, cell = Math.min(count - 2, Math.floor(coordinate)), t = coordinate - cell;
          const x = (kind === 'warp' ? index : coordinate) - (this.cols - 1) / 2;
          const y = (kind === 'warp' ? coordinate : index) - (this.rows - 1) / 2;
          // Finite-radius yarn needs a rounded, deeper crimp than a triangle
          // whose centreline barely clears the opposing crossing particle.
          const blend = t * t * (3 - 2 * t);
          const z = uniformDiameter ? (signs[cell] * (1 - blend) + signs[cell + 1] * blend) * this.diameter * .65 :
            (signs[cell] * (material.diameter + opposing[cell].diameter) * (1 - blend) + signs[cell + 1] * (material.diameter + opposing[cell + 1].diameter) * blend) * .325;
          const node = addNode(x, y, z, k === 0 || k === (count - 1) * segments);
          nodes.push(node);
          if (k % segments === 0) crossings.push(node);
        }
        crossings.yarn = addYarn(kind, nodes, material);
        return crossings;
      };
      for (let col = 0; col < this.cols; col++) warp.push(addChain('warp', col, this.rows, sample.map(row => row[col] ? 1 : -1)));
      for (let row = 0; row < this.rows; row++) weft.push(addChain('weft', row, this.cols, sample[row].map(value => value ? -1 : 1)));
      for (let row = 0; row < this.rows; row++) {
        for (let col = 0; col < this.cols; col++) {
          const bound = row === 0 || col === 0 || row === this.rows - 1 || col === this.cols - 1;
          // Hold the initial draft only during construction. release() keeps
          // only real frame anchors; crossing particles are never welded.
          if (bound) { warp[col][row].pinned = true; weft[row][col].pinned = true; }
          this.crossings.push({ warp: warp[col][row], weft: weft[row][col], sign: sample[row][col] ? 1 : -1, bound, warpYarn: warp[col].yarn, weftYarn: weft[row].yarn, wi: row * this.segmentsPerCrossing, fi: col * this.segmentsPerCrossing });
        }
      }
      // Connected families turn around alternating ends into the next strand.
      // All loops and fixed-end tails share the real endpoint particles.
      const addTurns = (kind, chains, count) => {
        for (let index = 0; index < chains.length - 1; index++) {
          const side = index % 2 === 0 ? 1 : -1, end = side > 0 ? count - 1 : 0;
          const a = chains[index][end], b = chains[index + 1][end], nodes = [a];
          const first = chains[index].yarn, last = chains[index + 1].yarn;
          const turnDiameter = Math.max(first.diameter, last.diameter);
          for (let k = 1; k < 12; k++) {
            const t = k / 12, turn = side * (turnDiameter + .15) * Math.sin(Math.PI * t), across = .5 * (1 - Math.cos(Math.PI * t));
            nodes.push(addNode(a.x + (kind === 'warp' ? across : turn), a.y + (kind === 'warp' ? turn : across), a.z * (1 - t) + b.z * t));
          }
          nodes.push(b);
          const material = { diameter: turnDiameter, ...(first.color ? { color: first.color } : {}) };
          if (first.diameter !== last.diameter) material.nodeDiameters = nodes.map((_, k) => first.diameter + (last.diameter - first.diameter) * k / 12);
          if (first.color && last.color && first.color !== last.color) {
            const rgb = color => color.slice(1).match(/../g).map(channel => parseInt(channel, 16) / 255);
            const start = rgb(first.color), finish = rgb(last.color);
            material.nodeColors = nodes.map((_, k) => start.map((channel, axis) => channel + (finish[axis] - channel) * k / 12));
          }
          addYarn(kind, nodes, material);
        }
      };
      const addFixedEnd = (kind, chain, count, side) => {
        const end = chain[side < 0 ? 0 : count - 1];
        const x = kind === 'weft' ? side * this.loom.halfSize : end.x;
        const y = kind === 'warp' ? side * this.loom.halfSize : end.y;
        const segments = Math.ceil(Math.hypot(x - end.x, y - end.y, end.z) * this.segmentsPerCrossing);
        const nodes = [end];
        for (let k = 1; k <= segments; k++) {
          const t = k / segments;
          const node = k === segments ? addNode(x, y, 0, true) : addNode(end.x + (x - end.x) * t, end.y + (y - end.y) * t, end.z * (1 - t));
          nodes.push(node);
          if (k === segments) this.fixedNodes.add(node);
        }
        addYarn(kind, nodes, { diameter: chain.yarn.diameter, ...(chain.yarn.color ? { color: chain.yarn.color } : {}) });
      };
      const finishEnds = (kind, chains, count, mode) => {
        if (mode === 'fixed') {
          for (const chain of chains) for (const side of [-1, 1]) addFixedEnd(kind, chain, count, side);
        } else {
          addTurns(kind, chains, count);
          // The continuous yarn has two loose tips after its alternating turns.
          // Attach those tips whenever a loom is holding the sample.
          if (this.loom) {
            addFixedEnd(kind, chains[0], count, -1);
            addFixedEnd(kind, chains[chains.length - 1], count, chains.length % 2 ? 1 : -1);
          }
        }
      };
      finishEnds('weft', weft, this.cols, this.weftEnds);
      finishEnds('warp', warp, this.rows, this.warpEnds);
      this.contactPositions = new Float64Array(this.nodes.length * 3);
      this.contactBounds = new Float64Array(this.edges.length * 6);
      // Reuse a compact pair set for small samples; bound its storage to 8 MiB.
      this.contactSeen = this.edges.length <= 8192 ? new Uint32Array(Math.ceil(this.edges.length ** 2 / 32)) : null;
      this.contactsDirty = true;
      this.warpYarns = warp.map(chain => chain.yarn);
      this.weftYarns = weft.map(chain => chain.yarn);
      this.mainYarns = this.warpYarns.concat(this.weftYarns);
      this.warpCrossings = warp;
      this.weftCrossings = weft;
      // Equal material intervals let crimp migrate along a yarn instead of
      // recording every initial over/under bend as a permanently short segment.
      for (const yarn of this.yarns) {
        const positions = yarn.nodes.map(node => ({ x: node.x, y: node.y, z: node.z }));
        const cumulative = [0];
        for (let i = 1; i < positions.length; i++) cumulative.push(cumulative[i - 1] + Math.hypot(positions[i].x - positions[i - 1].x, positions[i].y - positions[i - 1].y, positions[i].z - positions[i - 1].z));
        const spacing = cumulative[cumulative.length - 1] / (positions.length - 1);
        let segment = 0;
        for (let i = 1; i < positions.length - 1; i++) {
          const distance = i * spacing;
          while (cumulative[segment + 1] < distance) segment++;
          const t = (distance - cumulative[segment]) / (cumulative[segment + 1] - cumulative[segment]);
          const a = positions[segment], b = positions[segment + 1], node = yarn.nodes[i];
          node.x = a.x + t * (b.x - a.x); node.y = a.y + t * (b.y - a.y); node.z = a.z + t * (b.z - a.z);
        }
        for (const edge of this.edges) if (edge.yarn === yarn) edge.length = spacing / (1 + yarn.stretch);
      }
      for (const yarn of this.mainYarns) {
        yarn.restLength = this.edges.reduce((sum, edge) => sum + (edge.yarn === yarn ? edge.length : 0), 0);
      }
      // Rendering keeps its pieces, but mechanics follows the whole continuous
      // yarn, including bending and tension across every shared seam.
      const ends = new Map(), unused = new Set(this.yarns);
      for (const yarn of this.yarns) {
        yarn.edges = this.edges.filter(edge => edge.yarn === yarn);
        for (const node of [yarn.nodes[0], yarn.nodes[yarn.nodes.length - 1]]) {
          if (!ends.has(node)) ends.set(node, []);
          ends.get(node).push(yarn);
        }
      }
      this.physicalYarns = [];
      while (unused.size) {
        let piece = unused.values().next().value;
        const free = [...ends].find(([, pieces]) => pieces.length === 1 && unused.has(pieces[0]));
        let cursor = free ? free[0] : piece.nodes[0];
        if (free) piece = free[1][0];
        const chain = { kind: piece.kind, nodes: [cursor], edges: [], restLength: 0, materialCoordinates: [0] };
        while (piece) {
          unused.delete(piece);
          const forward = piece.nodes[0] === cursor;
          const nodes = forward ? piece.nodes : [...piece.nodes].reverse();
          const edges = forward ? piece.edges : [...piece.edges].reverse();
          chain.nodes.push(...nodes.slice(1));
          for (const edge of edges) {
            edge.physicalYarn = chain;
            edge.s0 = chain.restLength;
            chain.restLength += edge.length;
            edge.s1 = chain.restLength;
            chain.materialCoordinates.push(chain.restLength);
            chain.edges.push(edge);
          }
          cursor = nodes[nodes.length - 1];
          piece = ends.get(cursor).find(yarn => unused.has(yarn));
        }
        chain.materialCoordinates = Float64Array.from(chain.materialCoordinates);
        this.physicalYarns.push(chain);
      }
      // Lump uniform yarn mass by material length, so finer discretization
      // does not add artificial inertia to the same continuous yarn.
      for (const node of this.nodes) node.mass = 0;
      for (const edge of this.edges) {
        edge.a.mass += edge.length / 2;
        edge.b.mass += edge.length / 2;
      }
      for (const node of this.nodes) node.inverseMass = 1 / Math.max(1e-9, node.mass);
      this.projectionPositions = new Float64Array(this.nodes.length * 3);
      this.contactsDirty = true;
      this._crossingOrder(true);
      this.center = this._center();
      this.reference = this._spans();
      for (const node of this.nodes) {
        node.px = node.x; node.py = node.y; node.pz = node.z;
      }
    }

    release() {
      this.released = true;
      for (const node of this.nodes) node.pinned = this.fixedNodes.has(node);
    }

    _center() {
      const center = { x: 0, y: 0, z: 0 };
      for (const node of this.nodes) {
        center.x += node.x; center.y += node.y; center.z += node.z;
      }
      center.x /= this.nodes.length; center.y /= this.nodes.length; center.z /= this.nodes.length;
      return center;
    }

    _spans() {
      const span = (chains, axis) => chains.reduce((sum, nodes) => sum + nodes[nodes.length - 1][axis] - nodes[0][axis], 0) / chains.length;
      return { warp: span(this.warpCrossings, 'y'), weft: span(this.weftCrossings, 'x') };
    }

    _joined(first, second) {
      if (first.physicalYarn !== second.physicalYarn) return false;
      // Neighboring sections of a continuous round yarn share volume. Remote
      // sections of that same yarn still collide, including around edge loops.
      const gap = Math.max(first.s0, second.s0) - Math.min(first.s1, second.s1);
      return gap < (first.radius + second.radius) * 1.25;
    }

    _closest(first, second, result) {
      const a = first.a, b = first.b, c = second.a, d = second.b;
      const ux = b.x - a.x, uy = b.y - a.y, uz = b.z - a.z;
      const vx = d.x - c.x, vy = d.y - c.y, vz = d.z - c.z;
      const wx = a.x - c.x, wy = a.y - c.y, wz = a.z - c.z;
      const uu = ux * ux + uy * uy + uz * uz, vv = vx * vx + vy * vy + vz * vz;
      const uv = ux * vx + uy * vy + uz * vz, uw = ux * wx + uy * wy + uz * wz, vw = vx * wx + vy * wy + vz * wz;
      const determinant = uu * vv - uv * uv;
      let s = determinant > 1e-14 ? Math.max(0, Math.min(1, (uv * vw - vv * uw) / determinant)) : 0;
      let t = vv > 1e-14 ? (uv * s + vw) / vv : 0;
      if (t < 0) { t = 0; s = uu > 1e-14 ? Math.max(0, Math.min(1, -uw / uu)) : 0; }
      else if (t > 1) { t = 1; s = uu > 1e-14 ? Math.max(0, Math.min(1, (uv - uw) / uu)) : 0; }
      result.s = s; result.t = t;
      result.x = wx + ux * s - vx * t;
      result.y = wy + uy * s - vy * t;
      result.z = wz + uz * s - vz * t;
      return result.x * result.x + result.y * result.y + result.z * result.z;
    }

    _refreshContacts() {
      const skin = this.contactSkin, size = this.diameter + skin, grid = new Map(), seen = this.contactSeen, count = this.edges.length;
      const seenPairs = seen ? null : new Set();
      if (seen) seen.fill(0);
      this.contactPairs.length = 0;
      const closest = {}, bounds = this.contactBounds;
      let lowX = Infinity, lowY = Infinity, lowZ = Infinity, highX = -Infinity, highY = -Infinity, highZ = -Infinity;
      for (let i = 0; i < count; i++) {
        const edge = this.edges[i], { a, b } = edge, radius = edge.radius + skin / 2, offset = i * 6;
        const minX = Math.floor((Math.min(a.x, b.x) - radius) / size), maxX = Math.floor((Math.max(a.x, b.x) + radius) / size);
        const minY = Math.floor((Math.min(a.y, b.y) - radius) / size), maxY = Math.floor((Math.max(a.y, b.y) + radius) / size);
        const minZ = Math.floor((Math.min(a.z, b.z) - radius) / size), maxZ = Math.floor((Math.max(a.z, b.z) + radius) / size);
        bounds[offset] = minX; bounds[offset + 1] = maxX;
        bounds[offset + 2] = minY; bounds[offset + 3] = maxY;
        bounds[offset + 4] = minZ; bounds[offset + 5] = maxZ;
        lowX = Math.min(lowX, minX); highX = Math.max(highX, maxX);
        lowY = Math.min(lowY, minY); highY = Math.max(highY, maxY);
        lowZ = Math.min(lowZ, minZ); highZ = Math.max(highZ, maxZ);
      }
      // Integer cell indices avoid allocating a string on every grid visit.
      // Keep a string fallback if an unusually large grid exceeds exact integers.
      const depth = highZ - lowZ + 1, plane = (highY - lowY + 1) * depth;
      const numericKeys = Number.isSafeInteger((highX - lowX + 1) * plane);
      for (let i = 0; i < count; i++) {
        const edge = this.edges[i], offset = i * 6;
        const minX = bounds[offset], maxX = bounds[offset + 1], minY = bounds[offset + 2], maxY = bounds[offset + 3], minZ = bounds[offset + 4], maxZ = bounds[offset + 5];
        for (let x = minX; x <= maxX; x++) for (let y = minY; y <= maxY; y++) for (let z = minZ; z <= maxZ; z++) {
          const key = numericKeys ? (x - lowX) * plane + (y - lowY) * depth + z - lowZ : `${x},${y},${z}`;
          let bucket = grid.get(key);
          if (!bucket) { bucket = []; grid.set(key, bucket); }
          for (const j of bucket) {
            const other = this.edges[j], pair = j * count + i;
            if (seen) {
              const word = pair >>> 5, mask = 1 << (pair & 31);
              if (seen[word] & mask) continue;
              seen[word] |= mask;
            } else {
              if (seenPairs.has(pair)) continue;
              seenPairs.add(pair);
            }
            if (this._joined(edge, other)) continue;
            const radiusSum = edge.radius + other.radius + skin;
            if (this._closest(edge, other, closest) < radiusSum * radiusSum) this.contactPairs.push([edge, other]);
          }
          bucket.push(i);
        }
      }
      for (let i = 0; i < this.nodes.length; i++) {
        const node = this.nodes[i];
        this.contactPositions[i * 3] = node.x; this.contactPositions[i * 3 + 1] = node.y; this.contactPositions[i * 3 + 2] = node.z;
      }
      this.contactsDirty = false;
    }

    _friction(a, b, c, d, s, t, nx, ny, nz, load) {
      if (!this.friction || !this.released || load <= 0) return;
      const u = 1 - s, v = 1 - t;
      const wa = (a.pinned ? 0 : a.inverseMass ?? 1), wb = (b.pinned ? 0 : b.inverseMass ?? 1), wc = (c.pinned ? 0 : c.inverseMass ?? 1), wd = (d.pinned ? 0 : d.inverseMass ?? 1);
      const weight = wa * u * u + wb * s * s + wc * v * v + wd * t * t;
      if (!weight) return;
      // Evaluate the same material points now and at the substep's start.
      // Their relative tangential motion is slip, even when the geometric
      // intersection moves to different segments. Common cloth motion cancels.
      let dx = (a.x - a.px) * u + (b.x - b.px) * s - (c.x - c.px) * v - (d.x - d.px) * t;
      let dy = (a.y - a.py) * u + (b.y - b.py) * s - (c.y - c.py) * v - (d.y - d.py) * t;
      let dz = (a.z - a.pz) * u + (b.z - b.pz) * s - (c.z - c.pz) * v - (d.z - d.pz) * t;
      const normal = dx * nx + dy * ny + dz * nz;
      dx -= normal * nx; dy -= normal * ny; dz -= normal * nz;
      const slip = Math.hypot(dx, dy, dz), limit = this.friction * load;
      if (slip < 1e-12) return;
      // Static contact cancels admissible slip; sliding uses a lower kinetic
      // coefficient. Resistance vanishes when the normal contact is unloaded.
      // Contact patches span several short capsules. Relax their coupled
      // tangential solve so overlapping patches do not overpower yarn length.
      const correction = .25 * (slip <= limit ? 1 : .8 * limit / slip) / weight;
      dx *= correction; dy *= correction; dz *= correction;
      if (wa) { a.x -= dx * u; a.y -= dy * u; a.z -= dz * u; }
      if (wb) { b.x -= dx * s; b.y -= dy * s; b.z -= dz * s; }
      if (wc) { c.x += dx * v; c.y += dy * v; c.z += dz * v; }
      if (wd) { d.x += dx * t; d.y += dy * t; d.z += dz * t; }
    }

    _contact() {
      const threshold = this.contactSkin * this.contactSkin / 4;
      let refresh = this.contactsDirty;
      for (let i = 0; !refresh && i < this.nodes.length; i++) {
        const node = this.nodes[i];
        const dx = node.x - this.contactPositions[i * 3], dy = node.y - this.contactPositions[i * 3 + 1], dz = node.z - this.contactPositions[i * 3 + 2];
        refresh = dx * dx + dy * dy + dz * dz > threshold;
      }
      if (refresh) this._refreshContacts();
      const closest = {};
      for (let i = 0; i < this.contactPairs.length; i++) {
        const pair = this.contactPairs[i], first = pair[0], second = pair[1];
        const diameter = first.radius + second.radius;
        const distance2 = this._closest(first, second, closest);
        if (distance2 >= diameter * diameter) continue;
        const a = first.a, b = first.b, c = second.a, d = second.b;
        const s = closest.s, t = closest.t, u = 1 - s, v = 1 - t;
        const wa = (a.pinned ? 0 : a.inverseMass ?? 1), wb = (b.pinned ? 0 : b.inverseMass ?? 1), wc = (c.pinned ? 0 : c.inverseMass ?? 1), wd = (d.pinned ? 0 : d.inverseMass ?? 1);
        const weight = wa * u * u + wb * s * s + wc * v * v + wd * t * t;
        if (!weight) continue;
        const distance = Math.sqrt(distance2);
        let normalLength = distance;
        if (normalLength < 1e-8) {
          // An exact intersection still needs a separating normal. The rest
          // geometry retains the intended side when the current gap vanishes.
          closest.x = a.home.x * u + b.home.x * s - c.home.x * v - d.home.x * t;
          closest.y = a.home.y * u + b.home.y * s - c.home.y * v - d.home.y * t;
          closest.z = a.home.z * u + b.home.z * s - c.home.z * v - d.home.z * t;
          normalLength = Math.hypot(closest.x, closest.y, closest.z);
          if (normalLength < 1e-8) { closest.x = 0; closest.y = 0; closest.z = 1; normalLength = 1; }
        }
        const maximumWeight = Math.max(wa * u, wb * s, wc * v, wd * t);
        const separation = Math.min(diameter - distance, this.minimumDiameter * .1 * weight / maximumWeight);
        const correction = separation / (normalLength * weight);
        const dx = closest.x * correction, dy = closest.y * correction, dz = closest.z * correction;
        if (wa) { a.x += dx * wa * u; a.y += dy * wa * u; a.z += dz * wa * u; }
        if (wb) { b.x += dx * wb * s; b.y += dy * wb * s; b.z += dz * wb * s; }
        if (wc) { c.x -= dx * wc * v; c.y -= dy * wc * v; c.z -= dz * wc * v; }
        if (wd) { d.x -= dx * wd * t; d.y -= dy * wd * t; d.z -= dz * wd * t; }
        this._friction(a, b, c, d, s, t, closest.x / normalLength, closest.y / normalLength, closest.z / normalLength, diameter - distance);
      }
    }

    _locateCrossing(crossing, full = false) {
      const last = full ? Math.max(this.rows, this.cols) * this.segmentsPerCrossing : 3;
      const wn = crossing.warpYarn.nodes, fn = crossing.weftYarn.nodes;
      let best = null, score = Infinity;
      const wi = Math.min(wn.length - 2, crossing.wi), fi = Math.min(fn.length - 2, crossing.fi);
      for (let i = Math.max(0, wi - last); i <= Math.min(wn.length - 2, wi + last); i++) {
        const a = wn[i], b = wn[i + 1], ux = b.x - a.x, uy = b.y - a.y;
        for (let j = Math.max(0, fi - last); j <= Math.min(fn.length - 2, fi + last); j++) {
          const c = fn[j], d = fn[j + 1], vx = d.x - c.x, vy = d.y - c.y;
          const determinant = ux * vy - uy * vx;
          if (Math.abs(determinant) < 1e-12) continue;
          const dx = c.x - a.x, dy = c.y - a.y;
          const s = (dx * vy - dy * vx) / determinant, t = (dx * uy - dy * ux) / determinant;
          if (s < -1e-6 || s > 1 + 1e-6 || t < -1e-6 || t > 1 + 1e-6) continue;
          const distance = Math.abs(i + s - crossing.wi) + Math.abs(j + t - crossing.fi);
          if (distance < score) { score = distance; best = { a, b, c, d, s: Math.max(0, Math.min(1, s)), t: Math.max(0, Math.min(1, t)), i, j }; }
        }
      }
      return best || (!full ? this._locateCrossing(crossing, true) : null);
    }

    // Core-draft coordinates, independent of material-particle indices.
    getCrossing(row, col) {
      if (row < 0 || row >= this.coreRows || col < 0 || col >= this.coreCols) return null;
      const crossing = this.crossings[(row + this.border) * this.cols + col + this.border];
      const hit = this._locateCrossing(crossing);
      if (!hit) return null;
      const { a, b, c, d, s, t } = hit;
      return { x: a.x + s * (b.x - a.x), y: a.y + s * (b.y - a.y), z: (a.z + s * (b.z - a.z) + c.z + t * (d.z - c.z)) / 2 };
    }

    _crossingOrder(full = false) {
      // Draft signs establish the initial weave only. Once released, actual
      // capsule contact determines whether yarns touch, slide, or disengage.
      if (this.released) return;
      for (const crossing of this.crossings) {
        const best = this._locateCrossing(crossing, full);
        if (!best) continue;
        const { a, b, c, d, s, t, i, j } = best, u = 1 - s, v = 1 - t;
        crossing.wi = i; crossing.fi = j;
        crossing.x = a.x * u + b.x * s; crossing.y = a.y * u + b.y * s;
        const gap = crossing.sign * (a.z * u + b.z * s - c.z * v - d.z * t);
        const penetration = (crossing.warpYarn.diameter + crossing.weftYarn.diameter) / 2 - gap;
        if (penetration <= 0) continue;
        const wa = (a.pinned ? 0 : a.inverseMass ?? 1), wb = (b.pinned ? 0 : b.inverseMass ?? 1), wc = (c.pinned ? 0 : c.inverseMass ?? 1), wd = (d.pinned ? 0 : d.inverseMass ?? 1);
        const weight = wa * u * u + wb * s * s + wc * v * v + wd * t * t;
        if (!weight) continue;
        const correction = crossing.sign * penetration / weight;
        a.z += correction * wa * u; b.z += correction * wb * s;
        c.z -= correction * wc * v; d.z -= correction * wd * t;
        this._friction(a, b, c, d, s, t, 0, 0, crossing.sign, penetration);
      }
    }

    _project(bend, timestep = 1 / 120) {
      const before = this.projectionPositions;
      for (let i = 0; i < this.nodes.length; i++) {
        const node = this.nodes[i];
        before[i * 3] = node.x; before[i * 3 + 1] = node.y; before[i * 3 + 2] = node.z;
      }
      // Half-cell bending retains its physical span as sampling is refined.
      // Adjacent-node bending removes tiny zigzags left between those stencils
      // without appreciably flattening the much longer physical crimp waves.
      // Both corrections preserve each triplet's center of mass.
      for (const stride of [this.segmentsPerCrossing / 2, 1]) {
        const strength = stride === 1 ? Math.min(.3, bend * 64) : bend;
        for (const yarn of this.physicalYarns) {
          for (let k = stride; k < yarn.nodes.length - stride; k++) {
            const a = yarn.nodes[k - stride], b = yarn.nodes[k], c = yarn.nodes[k + stride];
            const wa = (a.pinned ? 0 : a.inverseMass ?? 1), wb = (b.pinned ? 0 : b.inverseMass ?? 1), wc = (c.pinned ? 0 : c.inverseMass ?? 1);
            const material = yarn.materialCoordinates;
            const left = material[k] - material[k - stride], right = material[k + stride] - material[k];
            const t = left / (left + right), u = 1 - t;
            const weight = wa * u * u + wb + wc * t * t;
            if (!weight) continue;
            const amount = strength * (u * u + 1 + t * t) / weight;
            const dx = (a.x * u + c.x * t - b.x) * amount, dy = (a.y * u + c.y * t - b.y) * amount, dz = (a.z * u + c.z * t - b.z) * amount;
            if (wb) { b.x += dx * wb; b.y += dy * wb; b.z += dz * wb; }
            if (wa) { a.x -= dx * wa * u; a.y -= dy * wa * u; a.z -= dz * wa * u; }
            if (wc) { c.x -= dx * wc * t; c.y -= dy * wc * t; c.z -= dz * wc * t; }
          }
        }
      }
      // Limit bending updates relative to yarn thickness to reduce
      // tunneling before the capsule contacts are projected again.
      const limit = this.minimumDiameter * .1;
      for (let i = 0; i < this.nodes.length; i++) {
        const node = this.nodes[i];
        const dx = node.x - before[i * 3], dy = node.y - before[i * 3 + 1], dz = node.z - before[i * 3 + 2];
        const distance = Math.hypot(dx, dy, dz);
        if (distance > limit) {
          const scale = limit / distance;
          node.x = before[i * 3] + dx * scale;
          node.y = before[i * 3 + 1] + dy * scale;
          node.z = before[i * 3 + 2] + dz * scale;
        }
      }
      for (let sweep = 0; sweep < 2; sweep++) for (let index = 0; index < this.edges.length; index++) {
        const edge = this.edges[sweep % 2 ? this.edges.length - 1 - index : index];
        const { a, b, length } = edge;
        const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        const distance = Math.hypot(dx, dy, dz);
        const wa = a.pinned ? 0 : a.inverseMass ?? 1, wb = b.pinned ? 0 : b.inverseMass ?? 1;
        const weight = wa + wb;
        if (!weight || distance < 1e-9) continue;
        // XPBD: elastic energy EA/(2 L0) * (L - L0)^2. Finite
        // compliance permits strain under fixed-end tension instead of
        // demanding incompatible hard lengths. Lambda resets each substep.
        const alpha = length / (5000 * timestep * timestep);
        let delta = (-(distance - length) - alpha * edge.lambda) / (weight + alpha);
        const maximumMove = Math.abs(delta) * Math.max(wa, wb), limit = this.minimumDiameter * .04;
        if (maximumMove > limit) delta *= limit / maximumMove;
        edge.lambda += delta;
        const correction = delta / distance;
        if (wa) { a.x -= dx * correction * wa; a.y -= dy * correction * wa; a.z -= dz * correction * wa; }
        if (wb) { b.x += dx * correction * wb; b.y += dy * correction * wb; b.z += dz * correction * wb; }
      }
      this._contact();
      for (const node of this.nodes) {
        if (node.pinned) { node.x = node.home.x; node.y = node.home.y; node.z = node.home.z; }
      }
    }

    step(dt = 1 / 120) {
      if (!this.released || !(dt > 0)) return;
      const duration = Math.min(dt, .1), count = Math.ceil(duration * 120);
      const h = duration / count;
      let maximumMotion = 0;
      for (let substep = 0; substep < count; substep++) {
        const damping = Math.pow(.8, h * 120);
        for (const node of this.nodes) {
          const x = node.x, y = node.y, z = node.z;
          let vx = (x - node.px) * damping, vy = (y - node.py) * damping, vz = (z - node.pz) * damping;
          const motion = Math.hypot(vx, vy, vz), limit = this.minimumDiameter * .1;
          if (motion > limit) { const scale = limit / motion; vx *= scale; vy *= scale; vz *= scale; }
          if (!node.pinned) { node.x += vx; node.y += vy; node.z += vz; }
          node.px = x; node.py = y; node.pz = z;
        }
        for (const edge of this.edges) edge.lambda = 0;
        for (let k = 0; k < 8; k++) this._project(this.bending * .012 * h * 120, h);
        // Collision cleanup has no draft ties or planar ordering constraints.
        for (let k = 0; k < 16; k++) this._contact();
        // A world-fixed frame supplies the reference when any ends are held.
        // Recentring those samples would move the anchors off the loom.
        let dx = 0, dy = 0, dz = 0;
        if (!this.fixedNodes.size) {
          const center = this._center();
          dx = center.x - this.center.x; dy = center.y - this.center.y; dz = center.z - this.center.z;
        }
        for (const node of this.nodes) {
          node.x -= dx; node.y -= dy; node.z -= dz;
          node.px -= dx; node.py -= dy; node.pz -= dz;
          maximumMotion = Math.max(maximumMotion, Math.hypot(node.x - node.px, node.y - node.py, node.z - node.pz) / h);
        }
      }
      this.motion = maximumMotion;
      this.elapsed += duration;
    }

    getMetrics() {
      const spans = this._spans();
      let maxStrain = 0;
      for (const { a, b, length } of this.edges) {
        maxStrain = Math.max(maxStrain, Math.abs(Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z) / length - 1));
      }
      const crimp = family => family.reduce((sum, yarn) => {
        const nodes = yarn.nodes;
        let length = 0;
        for (let i = 1; i < nodes.length; i++) length += Math.hypot(nodes[i].x - nodes[i - 1].x, nodes[i].y - nodes[i - 1].y, nodes[i].z - nodes[i - 1].z);
        const first = nodes[0], last = nodes[nodes.length - 1];
        return sum + length / Math.max(1e-9, Math.hypot(last.x - first.x, last.y - first.y, last.z - first.z)) - 1;
      }, 0) / family.length;
      return {
        warpCrimp: crimp(this.warpYarns),
        weftCrimp: crimp(this.weftYarns),
        warpStretch: this.warpStretch,
        weftStretch: this.weftStretch,
        warpContraction: this.reference.warp ? 1 - spans.warp / this.reference.warp : 0,
        weftContraction: this.reference.weft ? 1 - spans.weft / this.reference.weft : 0,
        maxStrain,
        motion: this.motion
      };
    }
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = ClothSimulation;
  if (root) root.ClothSimulation = ClothSimulation;
})(typeof window === 'undefined' ? null : window);
