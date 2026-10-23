/* Opaque tube surfaces with per-pixel depth: each centerline follows the
 * collision-tested physics segments without a spline's extra overshoot.
 * Shared same-family endpoints form one continuous tube through edge turns. */
(function (root) {
  'use strict';
  const SIDES = 12, SAMPLES = 2, STRIDE = 9;
  const palette = { warp: [.32, .45, .55], weft: [.77, .48, .30], binding: [.56, .48, .36] };
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = v => { const d = Math.hypot(...v) || 1; return v.map(x => x / d); };
  const rgb = (value, fallback) => Array.isArray(value) ? value : /^#[\da-f]{6}$/i.test(value || '')
    ? [1, 3, 5].map(offset => parseInt(value.slice(offset, offset + 2), 16) / 255) : fallback;

  class ClothRenderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: false });
      if (!this.gl) throw new Error('The cloth viewer needs WebGL support.');
      this.width = this.height = 1;
      this.lost = false;
      this._initialize();
      this._startWorker();
      canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); this.lost = true; });
      canvas.addEventListener('webglcontextrestored', () => {
        try {
          this._initialize(); this.lost = false;
          if (this.mesh) { this._upload(); this.draw(null, this.camera); }
        } catch (error) {
          if (this.onError) this.onError(error);
          else console.error(error);
        }
      });
    }

    _initialize() {
      const gl = this.gl;
      const shader = (type, source) => {
        const result = gl.createShader(type);
        gl.shaderSource(result, source); gl.compileShader(result);
        if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) {
          const message = gl.getShaderInfoLog(result); gl.deleteShader(result);
          throw new Error('Cloth renderer shader: ' + message);
        }
        return result;
      };
      const vertex = shader(gl.VERTEX_SHADER, `
        attribute vec3 position, normal, color;
        uniform vec3 right, down, front, center, scale;
        varying vec3 surfaceNormal, surfaceColor;
        void main() {
          vec3 p = vec3(dot(position, right), dot(position, down), dot(position, front)) - center;
          gl_Position = vec4(p.x * scale.x, -p.y * scale.y, -p.z * scale.z, 1.0);
          surfaceNormal = vec3(dot(normal, right), -dot(normal, down), dot(normal, front));
          surfaceColor = color;
        }`);
      const fragment = shader(gl.FRAGMENT_SHADER, `
        precision mediump float;
        varying vec3 surfaceNormal, surfaceColor;
        void main() {
          vec3 n = normalize(surfaceNormal);
          vec3 light = normalize(vec3(-0.45, 0.7, 1.4));
          float diffuse = max(0.0, dot(n, light));
          float sheen = pow(max(0.0, dot(n, normalize(light + vec3(0.0, 0.0, 1.0)))), 28.0);
          gl_FragColor = vec4(surfaceColor * (0.50 + 0.50 * diffuse) + 0.16 * sheen, 1.0);
        }`);
      const program = gl.createProgram();
      gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
      gl.deleteShader(vertex); gl.deleteShader(fragment);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Cloth renderer program: ' + gl.getProgramInfoLog(program));
      this.program = program;
      this.attributes = ['position', 'normal', 'color'].map(name => gl.getAttribLocation(program, name));
      this.uniforms = Object.fromEntries(['right', 'down', 'front', 'center', 'scale'].map(name => [name, gl.getUniformLocation(program, name)]));
      this.vertices = gl.createBuffer(); this.indices = gl.createBuffer();
      gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL);
      gl.disable(gl.BLEND); gl.disable(gl.CULL_FACE);
      gl.clearColor(0, 0, 0, 0);
    }

    resize(cssWidth, cssHeight, dpr = 1) {
      this.width = Math.max(1, cssWidth); this.height = Math.max(1, cssHeight);
      const width = Math.max(1, Math.round(this.width * dpr)), height = Math.max(1, Math.round(this.height * dpr));
      if (this.canvas.width !== width) this.canvas.width = width;
      if (this.canvas.height !== height) this.canvas.height = height;
    }

    _startWorker() {
      if (typeof Worker === 'undefined') { this.builder = new ClothMeshBuilder(); return; }
      this.worker = new Worker('assets/cloth-renderer-worker.js?v=wdi-yarns-1');
      this.worker.onmessage = ({ data }) => {
        this.busy = false;
        if (data.type === 'error') { this._fail(new Error(data.message)); return; }
        if (data.id === this.currentId) {
          this.mesh = data.mesh;
          if (!this.lost) { this._upload(); this.draw(null, this.camera); }
        }
        this._send();
      };
      this.worker.onerror = event => { event.preventDefault(); this._fail(new Error(event.message || 'The cloth renderer could not update.')); };
    }

    _fail(error) {
      this.worker?.terminate(); this.worker = null; this.busy = false;
      if (this.onError) this.onError(error); else console.error(error);
    }

    setState(result, camera) {
      this.camera = { ...camera }; this.currentId = result.id;
      if (result.render) { this.descriptor = result.render; this.topologyVersion = (this.topologyVersion || 0) + 1; }
      if (this.builder) {
        this.mesh = this.builder.setState({ positions: result.positions, render: result.render });
        if (!this.lost) { this._upload(); this.draw(null, this.camera); }
        return;
      }
      this.pending = { id: result.id, positions: result.positions, render: this.descriptor, topologyVersion: this.topologyVersion };
      this._send();
    }

    _send() {
      if (this.busy || !this.pending || !this.worker) return;
      const next = this.pending; this.pending = null; this.busy = true;
      const render = next.topologyVersion !== this.sentTopologyVersion ? next.render : undefined;
      this.sentTopologyVersion = next.topologyVersion;
      this.worker.postMessage({ id: next.id, positions: next.positions, render }, [next.positions.buffer]);
    }

    _upload() {
      const gl = this.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vertices); gl.bufferData(gl.ARRAY_BUFFER, this.mesh.vertices, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indices); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.mesh.indices, gl.DYNAMIC_DRAW);
    }

    draw(unused, camera) {
      this.camera = { ...camera };
      if (this.lost || !this.mesh) return;
      const gl = this.gl, mesh = this.mesh, cy = Math.cos(camera.yaw), sy = Math.sin(camera.yaw);
      const se = Math.sin(camera.elevation), ce = Math.cos(camera.elevation);
      const right = [cy, -sy, 0], down = [sy * se, cy * se, -ce], front = [sy * ce, cy * ce, se];
      const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
      for (let corner = 0; corner < 8; corner++) {
        const p = mesh.low.map((value, axis) => corner & (1 << axis) ? mesh.high[axis] : value);
        [right, down, front].forEach((axis, i) => { const value = dot(p, axis); low[i] = Math.min(low[i], value); high[i] = Math.max(high[i], value); });
      }
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      if (!mesh.meshes.length) return;
      gl.useProgram(this.program);
      let scale = Math.min(this.width / (mesh.cols + 4), this.height / (mesh.rows + 3));
      if (mesh.loom) scale = Math.min(scale, Math.max(1, this.width - 32) / (high[0] - low[0]), Math.max(1, this.height - 32) / (high[1] - low[1]));
      scale *= camera.zoom;
      const u = this.uniforms;
      gl.uniform3fv(u.right, right); gl.uniform3fv(u.down, down); gl.uniform3fv(u.front, front);
      gl.uniform3fv(u.center, low.map((value, i) => (value + high[i]) / 2));
      gl.uniform3f(u.scale, scale * 2 / this.width, scale * 2 / this.height, 2 / (high[2] - low[2] + 2));
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vertices); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indices);
      for (const part of mesh.meshes) {
        this.attributes.forEach((attribute, i) => {
          gl.enableVertexAttribArray(attribute);
          gl.vertexAttribPointer(attribute, 3, gl.FLOAT, false, STRIDE * 4, (part.vertexStart * STRIDE + i * 3) * 4);
        });
        gl.drawElements(gl.TRIANGLES, part.count, gl.UNSIGNED_SHORT, part.indexStart * 2);
      }
    }
  }
  class ClothMeshBuilder {
    _paths(simulation) {
      if (this.pathSource === simulation.yarns) return this.paths;
      const groups = new Map(), paths = [];
      for (const yarn of simulation.yarns) {
        if (yarn.nodes.length < 2) continue;
        const diameter = yarn.diameter || simulation.diameter, key = yarn.kind;
        if (!groups.has(key)) groups.set(key, { kind: yarn.kind, diameter, pieces: [], endpoints: new Map() });
        const group = groups.get(key);
        group.pieces.push(yarn);
        for (const node of [yarn.nodes[0], yarn.nodes[yarn.nodes.length - 1]]) {
          if (!group.endpoints.has(node)) group.endpoints.set(node, []);
          group.endpoints.get(node).push(yarn);
        }
      }
      for (const { kind, diameter, pieces, endpoints } of groups.values()) {
        const used = new Set();
        const trace = (piece, start) => {
          const nodes = [], nodeDiameters = [], nodeColors = [];
          let current = start;
          while (piece && !used.has(piece)) {
            used.add(piece);
            const source = piece.nodes, forward = source[0] === current;
            // Keep the exact particle references, with one ring at each join.
            for (let i = nodes.length ? 1 : 0; i < source.length; i++) {
              const index = forward ? i : source.length - 1 - i;
              nodes.push(source[index]);
              nodeDiameters.push(piece.nodeDiameters?.[index] ?? piece.diameter ?? simulation.diameter);
              nodeColors.push(rgb(piece.nodeColors?.[index] ?? piece.color, palette[kind] || palette.binding));
            }
            current = nodes[nodes.length - 1];
            const meeting = endpoints.get(current);
            piece = meeting.length === 2 ? meeting.find(next => !used.has(next)) : null;
          }
          paths.push({ kind, diameter, nodes, nodeDiameters, nodeColors, closed: current === start });
        };
        // Start at free ends so each connected open yarn becomes one path.
        for (const [node, meeting] of endpoints) if (meeting.length !== 2) {
          for (const piece of meeting) if (!used.has(piece)) trace(piece, node);
        }
        for (const piece of pieces) if (!used.has(piece)) trace(piece, piece.nodes[0]);
      }
      this.pathSource = simulation.yarns;
      return this.paths = paths;
    }

    _tube(yarn, diameter, vertices, indices) {
      const nodes = yarn.nodes, defaultDiameter = yarn.diameter || diameter;
      const color = rgb(yarn.color, palette[yarn.kind] || palette.binding), points = [], radii = [], colors = [];
      const nodeColor = index => rgb(yarn.nodeColors?.[index], color);
      for (let k = 0; k < nodes.length - 1; k++) {
        const a = nodes[k], b = nodes[k + 1];
        for (let j = 0; j < SAMPLES; j++) {
          const t = j / SAMPLES;
          points.push([a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t]);
          const da = yarn.nodeDiameters?.[k] ?? defaultDiameter, db = yarn.nodeDiameters?.[k + 1] ?? defaultDiameter;
          radii.push((da + (db - da) * t) / 2);
          const ca = nodeColor(k), cb = nodeColor(k + 1);
          colors.push(ca.map((value, axis) => value + (cb[axis] - value) * t));
        }
      }
      const last = nodes[nodes.length - 1];
      points.push([last.x, last.y, last.z]);
      radii.push((yarn.nodeDiameters?.[nodes.length - 1] ?? defaultDiameter) / 2);
      colors.push(nodeColor(nodes.length - 1));
      let previousTangent, normal, vertexStart = vertices.length / STRIDE, indexStart = indices.length, rings = 0;
      const tangents = [], frames = [], meshes = [];
      const addVertex = (p, n, c) => vertices.push(...p, ...n, ...c);
      const ring = (k) => {
        const [n, b] = frames[k];
        for (let side = 0; side < SIDES; side++) {
          const angle = side * 2 * Math.PI / SIDES, c = Math.cos(angle), s = Math.sin(angle);
          const direction = n.map((value, axis) => value * c + b[axis] * s);
          addVertex(points[k].map((value, axis) => value + radii[k] * direction[axis]), direction, colors[k]);
        }
      };
      const finish = () => meshes.push({ vertexStart, indexStart, count: indices.length - indexStart });
      for (let k = 0; k < points.length; k++) {
        const before = points[Math.max(0, k - 1)], after = points[Math.min(points.length - 1, k + 1)];
        let tangent = unit(after.map((value, axis) => value - before[axis]));
        if (dot(tangent, tangent) < .5) tangent = previousTangent || [0, 1, 0];
        if (!normal) {
          const reference = Math.abs(tangent[2]) < .9 ? [0, 0, 1] : [1, 0, 0];
          const along = dot(reference, tangent);
          normal = unit(reference.map((value, axis) => value - tangent[axis] * along));
        } else {
          const axis = cross(previousTangent, tangent), cosine = dot(previousTangent, tangent);
          if (cosine > -.9999) {
            const first = cross(axis, normal), second = cross(axis, first);
            normal = unit(normal.map((value, i) => value + first[i] + second[i] / (1 + cosine)));
          }
        }
        tangents.push(tangent); frames.push([normal, unit(cross(tangent, normal))]); previousTangent = tangent;
        // WebGL 1 indices address at most 65,536 local vertices. Repeat the
        // identical boundary ring to split long yarns without a visible seam.
        if (rings === 5000) {
          finish(); vertexStart = vertices.length / STRIDE; indexStart = indices.length;
          ring(k - 1); rings = 1;
        }
        ring(k);
        if (rings) for (let side = 0; side < SIDES; side++) {
          const a = (rings - 1) * SIDES + side, b = (rings - 1) * SIDES + (side + 1) % SIDES;
          indices.push(a, b, a + SIDES, b, b + SIDES, a + SIDES);
        }
        rings++;
      }
      finish();
      // Only genuine free ends are capped; chunk boundaries stay continuous.
      for (const end of yarn.closed ? [] : [0, points.length - 1]) {
        vertexStart = vertices.length / STRIDE; indexStart = indices.length;
        const p = points[end], n = tangents[end].map(value => value * (end ? 1 : -1));
        addVertex(p, n, colors[end]);
        for (let side = 0; side < SIDES; side++) {
          const angle = side * 2 * Math.PI / SIDES;
          addVertex(p.map((value, axis) => value + radii[end] * (frames[end][0][axis] * Math.cos(angle) + frames[end][1][axis] * Math.sin(angle))), n, colors[end]);
          indices.push(0, 1 + side, 1 + (side + 1) % SIDES);
        }
        finish();
      }
      return meshes;
    }

    build(simulation) {
      const vertices = [], indices = [], meshes = [];
      const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
      let paths = this._paths(simulation);
      if (simulation.loom) {
        const h = simulation.loom.halfSize;
        const nodes = [[0, -h], [h, -h], [h, h], [-h, h], [-h, -h], [0, -h]].map(([x, y]) => ({ x, y, z: 0 }));
        paths = [...paths, { kind: 'binding', diameter: .12, closed: true, nodes }];
      }
      for (const yarn of paths) {
        yarn.nodes.forEach((node, index) => {
          const radius = (yarn.nodeDiameters?.[index] ?? yarn.diameter ?? simulation.diameter) / 2;
          for (const [axis, key] of ['x', 'y', 'z'].entries()) {
            low[axis] = Math.min(low[axis], node[key] - radius); high[axis] = Math.max(high[axis], node[key] + radius);
          }
        });
        meshes.push(...this._tube(yarn, simulation.diameter, vertices, indices));
      }
      return { vertices: new Float32Array(vertices), indices: new Uint16Array(indices), meshes, low, high,
        rows: simulation.rows, cols: simulation.cols, loom: Boolean(simulation.loom) };
    }

    setState({ positions, render }) {
      if (render) {
        const nodes = Array.from({ length: positions.length / 3 }, () => ({ x: 0, y: 0, z: 0 }));
        this.simulation = { ...render, nodes, yarns: render.yarns.map(yarn => ({ ...yarn, nodes: yarn.nodes.map(index => nodes[index]) })) };
      }
      this.simulation.nodes.forEach((node, i) => { node.x = positions[i * 3]; node.y = positions[i * 3 + 1]; node.z = positions[i * 3 + 2]; });
      return this.build(this.simulation);
    }
  }
  root.ClothRenderer = ClothRenderer;
  root.ClothMeshBuilder = ClothMeshBuilder;
  if (typeof module !== 'undefined' && module.exports) module.exports = { ClothRenderer, ClothMeshBuilder };
})(typeof window !== 'undefined' ? window : globalThis);
