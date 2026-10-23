'use strict';

(() => {
  const $ = id => document.getElementById(id);
  const canvas = $('cloth'), renderer = new ClothRenderer(canvas);
  const controls = ['diameter', 'warpTension', 'weftTension', 'bending', 'friction'];
  const endControls = ['warpEnds', 'weftEnds'];
  const viewButtons = [...document.querySelectorAll('[data-view]')];
  const camera = { yaw: 0, elevation: Math.PI / 2, zoom: 1 };
  const cells = [];
  let draft, sourceDraft, sourceYarns = null, yarnScale = 1, simulation = null, drag = null, worker = null, timer = null;
  let revision = 0, framePending = false, workerBusy = false, uploadRevision = 0, sizeEdited = false;
  let renderedRows = 0, renderedCols = 0;
  let uploadedDraft = false;

  function resizedDraft(rows, cols) {
    return Array.from({ length: rows }, (_, row) => Array.from({ length: cols }, (_, col) =>
      sourceDraft[row % sourceDraft.length][col % sourceDraft[0].length]));
  }

  function resizedYarns(rows, cols) {
    if (!sourceYarns) return null;
    return Object.fromEntries([['warp', cols], ['weft', rows]].map(([kind, count]) =>
      [kind, Array.from({ length: count }, (_, i) => sourceYarns[kind][i % sourceYarns[kind].length])]));
  }

  function selectPattern(name) {
    uploadedDraft = false;
    const rows = sizeEdited && $('weft-count').checkValidity() ? Number($('weft-count').value) : draft?.length;
    const cols = sizeEdited && $('warp-count').checkValidity() ? Number($('warp-count').value) : draft?.[0].length;
    uploadRevision++;
    $('upload-error').hidden = true;
    $('pattern').querySelector('[value="custom"]').textContent = 'Custom drawdown';
    sourceYarns = null; yarnScale = 1;
    if (name === 'double-cloth') {
      draft = ClothWeavePresets.doubleCloth();
    } else if (name === 'deflected-double-cloth') {
      draft = ClothWeavePresets.deflectedDoubleCloth();
    } else if (name === 'huck') {
      // User's Huck Lace Pattern Draft reference: plain weave and float blocks.
      // Keep the complete five-end/five-pick checkerboard intact.
      const threading = [1, 3, 1, 3, 1, 2, 4, 2, 4, 2];
      const lifts = [[1, 4], [2, 3, 4], [1, 4], [2, 3, 4], [1, 4], [2, 3], [1, 3, 4], [2, 3], [1, 3, 4], [2, 3]];
      draft = Array.from({ length: 20 }, (_, row) => Array.from({ length: 20 }, (_, col) => lifts[row % lifts.length].includes(threading[col % threading.length])));
    } else {
      draft = Array.from({ length: 16 }, (_, row) => Array.from({ length: 16 }, (_, col) =>
        name === 'twill' ? (col - row + 16) % 4 < 2 :
        name === 'basket' ? (Math.floor(col / 2) + Math.floor(row / 2)) % 2 === 0 : (row + col) % 2 === 0));
    }
    sourceDraft = draft;
    draft = resizedDraft(sizeEdited ? rows : draft.length, sizeEdited ? cols : draft[0].length);
    refreshDraft();
    requestResult();
  }

  function refreshDraft() {
    const rows = draft.length, cols = draft[0].length;
    document.querySelector('.draft-counts').hidden = uploadedDraft;
    $('draft').hidden = uploadedDraft;
    document.querySelector('.legend').hidden = uploadedDraft;
    $('warp-count').value = cols;
    $('weft-count').value = rows;
    $('draft-size').textContent = `${cols} ends × ${rows} picks`;
    $('draft').style.setProperty('--draft-columns', cols);
    if (renderedRows !== rows || renderedCols !== cols) {
      $('draft').replaceChildren(); cells.length = 0;
      renderedRows = rows; renderedCols = cols;
    }
    if (!cells.length) {
      for (let row = 0; row < rows; row++) for (let col = 0; col < cols; col++) {
        const cell = document.createElement('button');
        cell.type = 'button';
        cell.addEventListener('click', () => {
          uploadRevision++;
          $('upload-error').hidden = true;
          draft[row][col] = !draft[row][col];
          sourceDraft = draft.map(line => line.slice());
          sourceYarns = resizedYarns(rows, cols);
          $('pattern').value = 'custom';
          refreshDraft();
          requestResult();
        });
        $('draft').append(cell);
        cells.push(cell);
      }
    }
    const yarns = resizedYarns(rows, cols);
    $('diameter-label').textContent = yarns ? 'Yarn scale' : 'Yarn diameter';
    for (const kind of ['warp', 'weft']) {
      const colors = [...new Set(yarns?.[kind].map(yarn => yarn.color) || [])];
      document.querySelector(kind === 'warp' ? '.swatch' : '.swatch.weft').style.background =
        colors.length > 1 ? `linear-gradient(90deg, ${colors.map((color, i) => `${color} ${i * 100 / colors.length}% ${(i + 1) * 100 / colors.length}%`).join(',')})` : colors[0] || '';
    }
    cells.forEach((cell, i) => {
      const row = Math.floor(i / cols), col = i % cols, above = draft[row][col];
      for (const [kind, index] of [['warp', col], ['weft', row]]) {
        if (yarns) cell.style.setProperty('--' + kind, yarns[kind][index].color);
        else cell.style.removeProperty('--' + kind);
      }
      cell.setAttribute('aria-pressed', String(above));
      cell.setAttribute('aria-label', `Pick ${row + 1}, warp ${col + 1}: ${above ? 'warp' : 'weft'} on top`);
    });
  }

  function readOptions() {
    const options = Object.fromEntries(controls.map(id => [id, Number($(id).value)]));
    const yarns = resizedYarns(draft.length, draft[0].length);
    if (yarns) options.yarns = Object.fromEntries(Object.entries(yarns).map(([kind, threads]) =>
      [kind, threads.map(yarn => ({ color: yarn.color, thickness: yarn.thickness / yarnScale }))]));
    endControls.forEach(id => {
      options[id] = $(id).checked ? 'fixed' : 'connected';
      $(id + '-value').value = $(id).checked ? 'Fixed' : 'Connected';
    });
    $('diameter-value').value = options.diameter.toFixed(2) + ' × spacing';
    $('warpTension-value').value = options.warpTension.toFixed(2) + '×';
    $('weftTension-value').value = options.weftTension.toFixed(2) + '×';
    $('bending-value').value = options.bending.toFixed(2);
    $('friction-value').value = options.friction.toFixed(2);
    return options;
  }

  function setState(text, pending = false) {
    $('state').textContent = text;
    $('state').dataset.pending = String(pending);
    $('state').dataset.released = String(Boolean(simulation));
    $('viewer').setAttribute('aria-busy', String(pending));
  }

  function showResult(result, timing, finished = true) {
    const { metrics } = result;
    simulation = true;
    // Transfer the solver snapshot directly to the mesh worker; the page only
    // updates controls and metrics while geometry is prepared in the background.
    renderer.setState(result, camera);
    const percent = value => (Math.abs(value) < .0005 ? '0.0' : (value * 100).toFixed(1)) + '%';
    $('warp-metric').textContent = percent(metrics.warpContraction);
    $('weft-metric').textContent = percent(metrics.weftContraction);
    $('update-timing').textContent = timing;
    if (finished) {
      $('state').dataset.converged = String(result.converged);
      $('state').dataset.visuallySettled = String(result.visuallySettled);
      setState(result.converged ? 'Settled preview' : result.visuallySettled ? 'Visually settled' : 'Preview ready');
    } else {
      setState('Settling cloth…', true);
    }
  }

  function requestResult() {
    const requestedAt = performance.now();
    const id = ++revision, options = readOptions();
    const snapshot = draft.map(row => row.slice());
    clearTimeout(timer);
    if (workerBusy) { worker.terminate(); worker = null; workerBusy = false; }
    setState('Updating cloth…', true);
    $('update-timing').textContent = 'Calculating…';
    // Coalesce slider events, then animate real states from the worker.
    timer = setTimeout(() => {
      // Retain an idle worker so its solver stays compiled between adjustments.
      const current = worker || new Worker('assets/cloth-relaxation-worker.js?v=wdi-yarns-1');
      worker = current;
      workerBusy = true;
      const fail = () => {
        if (id !== revision || worker !== current) return;
        current.terminate(); worker = null; workerBusy = false;
        setState('Could not update cloth. Change a setting to try again.');
        $('update-timing').textContent = '';
      };
      current.onerror = event => { event.preventDefault(); fail(); };
      current.onmessage = ({ data }) => {
        if (id !== revision || worker !== current || data.id !== id) return;
        if (data.type === 'frame') {
          showResult(data, ((performance.now() - requestedAt) / 1000).toFixed(1) + ' s', false);
          return;
        }
        if (data.type !== 'result') { fail(); return; }
        workerBusy = false;
        showResult(data, 'Updated in ' + ((performance.now() - requestedAt) / 1000).toFixed(1) + ' s');
      };
      current.postMessage({ id, draft: snapshot, options });
    }, 60);
  }

  function invalidate() {
    if (framePending) return;
    framePending = true;
    requestAnimationFrame(() => {
      framePending = false;
      if (simulation) renderer.draw(null, camera);
    });
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    renderer.resize(rect.width, rect.height, window.devicePixelRatio || 1);
    invalidate();
  }

  $('pattern').addEventListener('change', () => selectPattern($('pattern').value));
  for (const id of ['warp-count', 'weft-count']) {
    $(id).addEventListener('input', () => {
      if (!$('warp-count').checkValidity() || !$('weft-count').checkValidity()) return;
      const rows = Number($('weft-count').value), cols = Number($('warp-count').value);
      if (rows === draft.length && cols === draft[0].length) return;
      uploadRevision++;
      $('upload-error').hidden = true;
      sizeEdited = true;
      draft = resizedDraft(rows, cols);
      refreshDraft();
      requestResult();
    });
    $(id).addEventListener('change', () => $(id).reportValidity());
  }
  function applyImportedDraft(imported, fallbackName) {
    uploadedDraft = true;
    sourceDraft = imported.draft;
    sourceYarns = imported.yarns || null;
    yarnScale = sourceYarns ? Math.max(...sourceYarns.warp.concat(sourceYarns.weft).map(yarn => yarn.thickness)) : 1;
    draft = resizedDraft(sourceDraft.length, sourceDraft[0].length);
    sizeEdited = true;
    $('pattern').querySelector('[value="custom"]').textContent = 'Custom · ' + (imported.name || fallbackName);
    $('pattern').value = 'custom';
    refreshDraft();
    requestResult();
  }

  function consumeDraftTransfer() {
    const url = new URL(window.location.href), token = url.searchParams.get('transfer');
    if (!token) return;
    try {
      const key = 'weaving-cross-editor-transfer.v1.' + token;
      const raw = window.localStorage.getItem(key);
      if (!raw) throw new Error('The transferred draft is unavailable. Send it from the Drafter again.');
      const entry = JSON.parse(raw);
      if (entry?.payload && (!Number.isFinite(entry.createdAt) || Date.now() - entry.createdAt > 60 * 60 * 1000)) {
        throw new Error('The draft transfer has expired. Send it from the Drafter again.');
      }
      applyImportedDraft(ClothDraftImport.parse(JSON.stringify(entry?.payload ?? entry)), 'Drafter draft');
      window.localStorage.removeItem(key);
      url.searchParams.delete('transfer');
      window.history.replaceState({}, '', url.pathname + url.search + url.hash);
    } catch (error) {
      $('upload-error').textContent = error.message || 'Could not open the transferred draft.';
      $('upload-error').hidden = false;
    }
  }

  $('upload-draft').addEventListener('click', () => $('draft-upload').click());
  $('draft-upload').addEventListener('change', async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = '';
    const id = ++uploadRevision;
    $('upload-error').hidden = true;
    try {
      const imported = ClothDraftImport.parse(await file.text());
      if (id !== uploadRevision) return;
      applyImportedDraft(imported, file.name);
    } catch (error) {
      if (id !== uploadRevision) return;
      $('upload-error').textContent = error.message || 'Could not read that draft.';
      $('upload-error').hidden = false;
    }
  });
  controls.forEach(id => $(id).addEventListener('input', requestResult));
  endControls.forEach(id => $(id).addEventListener('change', requestResult));
  renderer.onError = () => setState('Could not draw cloth.');

  function cameraChanged() { viewButtons.forEach(button => button.setAttribute('aria-pressed', 'false')); invalidate(); }
  viewButtons.forEach(button => button.addEventListener('click', () => {
    const name = button.dataset.view;
    camera.yaw = name === 'oblique' ? -0.22 : 0;
    camera.elevation = name === 'top' ? Math.PI / 2 : name === 'edge' ? 0.12 : 0.87;
    camera.zoom = 1;
    cameraChanged(); button.setAttribute('aria-pressed', 'true');
  }));
  canvas.addEventListener('pointerdown', event => {
    drag = { x: event.clientX, y: event.clientY }; canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag) return;
    camera.yaw += (event.clientX - drag.x) * 0.008;
    camera.elevation = Math.max(0.06, Math.min(Math.PI / 2, camera.elevation + (event.clientY - drag.y) * 0.008));
    drag = { x: event.clientX, y: event.clientY }; cameraChanged();
  });
  canvas.addEventListener('pointerup', () => { drag = null; });
  canvas.addEventListener('pointercancel', () => { drag = null; });
  canvas.addEventListener('lostpointercapture', () => { drag = null; });
  canvas.addEventListener('wheel', event => {
    event.preventDefault(); camera.zoom = Math.max(0.65, Math.min(2.3, camera.zoom * Math.exp(-event.deltaY * 0.001))); invalidate();
  }, { passive: false });
  canvas.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowLeft') camera.yaw -= 0.1;
    if (event.key === 'ArrowRight') camera.yaw += 0.1;
    if (event.key === 'ArrowUp') camera.elevation += 0.08;
    if (event.key === 'ArrowDown') camera.elevation -= 0.08;
    if (['+', '='].includes(event.key)) camera.zoom *= 1.1;
    if (event.key === '-') camera.zoom /= 1.1;
    camera.elevation = Math.max(0.06, Math.min(Math.PI / 2, camera.elevation));
    camera.zoom = Math.max(0.65, Math.min(2.3, camera.zoom)); cameraChanged();
  });

  new ResizeObserver(resize).observe(canvas);
  resize();
  selectPattern('plain');
  consumeDraftTransfer();
})();
