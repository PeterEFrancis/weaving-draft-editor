/* Read native WDD/WDI JSON or inert SVG metadata; never insert uploaded SVG. */
(function (root) {
  'use strict';

  function dimensions(rows, cols) {
    if (!Number.isInteger(rows) || !Number.isInteger(cols) || rows < 2 || cols < 2) {
      throw new Error('The WDD/WDI draft must have at least 2 ends and 2 picks.');
    }
    if (rows > 64 || cols > 64) throw new Error('Simulation supports up to 64 ends × 64 picks (4,096 crossings). Export a smaller WDD/WDI repeat.');
  }

  function yarnData(state, cols, rows) {
    if (!Array.isArray(state.patternColors)) return null;
    const palette = new Map(state.patternColors.map((entry, index) => {
      const thickness = Number.parseFloat(entry?.thickness);
      return [entry?.id || `pattern-color-${index + 1}`, {
        color: /^#[0-9a-f]{6}$/i.test(entry?.value || '') ? entry.value.toLowerCase() : null,
        thickness: Number.isFinite(thickness) && thickness > 0 ? Math.max(.1, Math.round(thickness * 10) / 10) : 1
      }];
    }));
    const warpAssignments = Array.from({ length: cols }, (_, col) => {
      const shaft = (state.threading || []).findIndex(line => Boolean(line?.[col]));
      return { shaft, colorId: state.threading?.[shaft]?.[col] };
    });
    const weftAssignments = Array.from({ length: rows }, (_, row) => state.treadling?.[row]?.find(Boolean));
    const resolve = id => {
      const yarn = palette.get(id);
      if (!yarn?.color) throw new Error('The WDD yarn assignments must reference valid palette colors.');
      return { ...yarn };
    };
    return { warpAssignments, yarns: {
      warp: warpAssignments.map(entry => resolve(entry.colorId)),
      weft: weftAssignments.map(resolve)
    } };
  }

  function parse(contents) {
    let text = String(contents ?? '').trim();
    if (text.startsWith('<')) {
      const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
      if (doc.querySelector('parsererror')) throw new Error('That SVG file could not be read.');
      const metadata = doc.querySelector('#wdi-data, #wdd-data, metadata[data-format="application/vnd.weaving-draft-inverse+json"], metadata[data-format="application/vnd.weaving-draft-document+json"]');
      if (!metadata) throw new Error('That SVG does not contain a WDD/WDI draft.');
      text = String(metadata.textContent || '').trim();
      if (String(metadata.getAttribute('data-encoding') || '').toLowerCase() === 'base64') {
        try {
          const binary = atob(text.replace(/\s+/g, ''));
          text = new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(binary, character => character.charCodeAt(0)));
        } catch {
          throw new Error('The embedded WDD/WDI draft could not be decoded.');
        }
      }
    }
    let data;
    try { data = JSON.parse(text); }
    catch { throw new Error('That file does not contain valid WDD/WDI draft data.'); }
    const forward = data?.format === 'weaving-draft-data';
    if (!data || typeof data !== 'object' || (!forward && data.meta?.kind && data.meta.kind !== 'weaving-inverse-draft')) {
      throw new Error('Choose a WDD or WDI draft file.');
    }
    const state = forward ? data.draft : data.state ?? data;
    let matrix = state?.targetDrawdown, yarns;
    if (forward) {
      const rows = Number(state?.picks), cols = Number(state?.warp);
      dimensions(rows, cols);
      const assignments = yarnData(state, cols, rows);
      if (!assignments) throw new Error('The WDD draft does not contain a yarn palette.');
      yarns = assignments.yarns;
      matrix = Array.from({ length: rows }, (_, row) => assignments.warpAssignments.map(({ shaft }) =>
        Boolean(state.treadling[row].some((colorId, treadle) => colorId && state.tieup?.[treadle]?.[shaft]))));
    }
    if (!Array.isArray(matrix) || matrix.length < 2 || !Array.isArray(matrix[0]) || matrix[0].length < 2) {
      throw new Error('The WDD/WDI draft must have at least 2 ends and 2 picks.');
    }
    const rows = matrix.length, cols = matrix[0].length;
    dimensions(rows, cols);
    if (matrix.some(row => !Array.isArray(row) || row.length !== cols || row.some(value => value !== 0 && value !== 1 && value !== false && value !== true))) {
      throw new Error('The WDI drawdown must be a rectangular grid of 0/1 cells.');
    }
    for (const [key, count] of [['warp', cols], ['picks', rows]]) {
      if (state[key] !== undefined && (!['number', 'string'].includes(typeof state[key]) || Number(state[key]) !== count)) {
        throw new Error('The WDI dimensions do not match its drawdown.');
      }
    }
    if (!forward) yarns = yarnData(state, cols, rows)?.yarns;
    const name = data.meta?.draftName ?? state.draftName;
    return { draft: matrix.map(row => row.map(Boolean)), name: typeof name === 'string' && name.trim() ? name.trim() : 'Custom draft', ...(yarns ? { yarns } : {}) };
  }

  const api = { parse };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.ClothDraftImport = api;
})(typeof window === 'undefined' ? null : window);
