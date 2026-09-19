/* renderPatternSearchPreview(canvas, pattern) draws the draft's front fabric.
 * Small drafts tile in both directions; complete large motifs fit without
 * stretching the yarn proportions. Rendering always uses a 240 × 176 bitmap.
 * dataset.repeatX / repeatY include any partial repeat at the right/bottom edge.
 */
function renderPatternSearchPreview(canvas, pattern) {
  "use strict";

  const WIDTH = 240;
  const HEIGHT = 176;

  function colorChannels(value, context) {
    context.fillStyle = "#ffffff";
    context.fillStyle = value;
    const normalized = context.fillStyle;
    if (/^#[\da-f]{6}$/i.test(normalized)) {
      return [1, 3, 5].map(offset => parseInt(normalized.slice(offset, offset + 2), 16));
    }
    const channels = normalized.match(/[\d.]+/g);
    return channels && channels.length >= 3 ? channels.slice(0, 3).map(Number) : [255, 255, 255];
  }

  function trackMap(weights, pixels, scale) {
    const edges = [0];
    weights.forEach(weight => edges.push(edges[edges.length - 1] + weight));
    const total = edges[edges.length - 1];
    const indices = new Int32Array(pixels);
    const shading = new Float32Array(pixels);
    for (let pixel = 0; pixel < pixels; pixel++) {
      const position = ((pixel + 0.5) / scale) % total;
      let left = 0;
      let right = weights.length;
      while (left + 1 < right) {
        const middle = (left + right) >> 1;
        if (edges[middle] <= position) left = middle;
        else right = middle;
      }
      indices[pixel] = left;
      const fraction = (position - edges[left]) / weights[left];
      shading[pixel] = weights[left] * scale >= 2
        ? 0.91 + 0.12 * Math.sin(fraction * Math.PI)
        : 1;
    }
    return { indices, shading, total };
  }

  const draft = pattern.draft;
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const context = canvas.getContext("2d", { alpha: false });
  if (!context || !draft.warp || !draft.picks) return;

  const fallback = { rgb: [255, 255, 255], weight: 1 };
  const yarns = new Map(draft.patternColors.map(yarn => [yarn.id, {
    rgb: colorChannels(yarn.value, context),
    weight: Math.max(0.01, Number(yarn.thickness) || 1)
  }]));
  const warp = Array.from({ length: draft.warp }, (_, end) => {
    for (let shaft = 0; shaft < draft.shafts; shaft++) {
      const id = draft.threading[shaft]?.[end];
      if (id) return { shaft, yarn: yarns.get(id) || fallback };
    }
    return { shaft: -1, yarn: fallback };
  });
  const weft = Array.from({ length: draft.picks }, (_, pick) => {
    const treadling = draft.treadling[pick] || [];
    const lifted = new Uint8Array(draft.shafts);
    treadling.forEach((id, treadle) => {
      if (!id) return;
      for (let shaft = 0; shaft < draft.shafts; shaft++) {
        if (draft.tieup[treadle]?.[shaft]) lifted[shaft] = 1;
      }
    });
    return { yarn: yarns.get(treadling.find(Boolean)) || fallback, lifted };
  });
  const warpWeights = warp.map(end => end.yarn.weight);
  const weftWeights = weft.map(pick => pick.yarn.weight);
  const warpSize = warpWeights.reduce((sum, weight) => sum + weight, 0);
  const weftSize = weftWeights.reduce((sum, weight) => sum + weight, 0);
  // At most five pixels per unit yarn; fit one whole motif on each axis.
  const scale = Math.min(5, WIDTH / warpSize, HEIGHT / weftSize);
  const columns = trackMap(warpWeights, WIDTH, scale);
  const rows = trackMap(weftWeights, HEIGHT, scale);
  canvas.dataset.repeatX = String(Math.ceil(WIDTH / scale / warpSize - 1e-8));
  canvas.dataset.repeatY = String(Math.ceil(HEIGHT / scale / weftSize - 1e-8));

  const bitmap = context.createImageData(WIDTH, HEIGHT);
  for (let y = 0; y < HEIGHT; y++) {
    const pick = weft[rows.indices[y]];
    for (let x = 0; x < WIDTH; x++) {
      const end = warp[columns.indices[x]];
      const warpVisible = end.shaft >= 0 && pick.lifted[end.shaft];
      const color = (warpVisible ? end.yarn : pick.yarn).rgb;
      const shade = warpVisible ? columns.shading[x] : rows.shading[y];
      const offset = (y * WIDTH + x) * 4;
      bitmap.data[offset] = color[0] * shade;
      bitmap.data[offset + 1] = color[1] * shade;
      bitmap.data[offset + 2] = color[2] * shade;
      bitmap.data[offset + 3] = 255;
    }
  }
  context.putImageData(bitmap, 0, 0);
}
