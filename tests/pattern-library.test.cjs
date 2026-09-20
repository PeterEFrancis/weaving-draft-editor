const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const context = vm.createContext({});
const html = fs.readFileSync(path.join(root, 'pattern-library.html'), 'utf8');
const catalogScripts = [...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"[^>]*>/g)]
  .map(match => match[1]).filter(source => source.startsWith('assets/patterns/'));
for (const source of catalogScripts) {
  vm.runInContext(fs.readFileSync(path.join(root, source), 'utf8'), context, { filename: source });
}
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
vm.runInContext(script.slice(0, script.indexOf('    buildPatternList();')), context);
const get = expression => JSON.parse(JSON.stringify(vm.runInContext(expression, context)));
const patterns = get('patterns');
const catalog = get('learningToWeaveCatalog');
const dixonCatalog = get('handweaversPatternDirectoryCatalog');
const handwovenCatalog = get('handwovenCatalog');
const families = get('patternFamilies');
const byId = id => patterns.find(p => p.id === `chandler-${id}`);
const raised = (draft, pick) => draft.tieup.flatMap((shed, treadle) =>
  draft.treadling[pick][treadle] ? shed.flatMap((active, shaft) => active ? [shaft + 1] : []) : []
).sort((a, b) => a - b);
const warpShafts = draft => Array.from({ length: draft.warp }, (_, i) =>
  draft.threading.findIndex(row => row[i]) + 1);

test('every Chandler entry is reachable exactly once and all IDs remain unique', () => {
  assert.equal(new Set(patterns.map(p => p.id)).size, patterns.length);
  const bookFamilies = families.filter(f => f.publicationId === 'learning-to-weave');
  assert.equal(bookFamilies.length, 11);
  assert.equal(catalog.patterns.length, 108);
  assert.equal(bookFamilies.flatMap(f => f.memberIds).length, catalog.patterns.length);
  for (const entry of catalog.patterns) {
    assert.equal(bookFamilies.filter(f => f.memberIds.includes(entry.id)).length, 1);
    assert.ok(entry.pages && entry.description);
  }
  assert.equal(get('resolveFamilyRoute("chandler-overshot-198-bottom").focusPattern.id'), 'chandler-overshot-198-bottom');
  assert.equal(get('resolveFamilyRoute("chandler-lesson-15").family.id'), 'chandler-lesson-15');
  assert.equal(get('resolveFamilyRoute("unknown").family.id'), 'plain-weave');
});

test('Chandler drafts have complete assignments and faithfully preserve source lift plans', () => {
  for (const entry of catalog.patterns) {
    const draft = patterns.find(p => p.id === entry.id).draft;
    const label = entry.id;
    const colors = new Set(draft.patternColors.map(c => c.id));
    assert.equal(draft.warp, entry.threading.length, label);
    assert.equal(draft.picks, entry.lifts.length * (entry.tabby ? 2 : 1), label);
    assert.deepEqual(warpShafts(draft), entry.threading, label);
    for (let col = 0; col < draft.warp; col++) {
      const active = draft.threading.map(row => row[col]).filter(Boolean);
      assert.equal(active.length, 1, label);
      assert.ok(colors.has(active[0]), label);
    }
    for (let pick = 0; pick < draft.picks; pick++) {
      const active = draft.treadling[pick].filter(Boolean);
      assert.equal(active.length, 1, label);
      assert.ok(colors.has(active[0]), label);
      const sourceIndex = entry.tabby ? Math.floor(pick / 2) : pick;
      const expected = entry.tabby && pick % 2 ? entry.tabby[sourceIndex % 2] : entry.lifts[sourceIndex];
      assert.deepEqual(raised(draft, pick), [...expected].sort((a, b) => a - b), `${label}, pick ${pick + 1}`);
      assert.ok(expected.length > 0 && expected.length < draft.shafts, `${label}: valid shed`);
    }
  }
});

test('tabby alone interlaces every other end in all overshot and summer/winter drafts', () => {
  for (const entry of catalog.patterns.filter(e => e.tabby)) {
    const first = entry.threading.map(s => entry.tabby[0].includes(s));
    const second = entry.threading.map(s => entry.tabby[1].includes(s));
    first.forEach((v, i) => {
      assert.notEqual(v, second[i], entry.id);
      if (i) assert.notEqual(v, first[i - 1], entry.id);
    });
  }
});

test('source spot checks: waffle, honeycomb, overshot and color ordering', () => {
  assert.deepEqual(raised(byId('waffle-four').draft, 3), [1, 2, 4]);
  const honey = byId('honeycomb').draft;
  assert.deepEqual(warpShafts(honey), [1,2,1,2,1,2,3,4,3,4,3,4]);
  assert.deepEqual(raised(honey, 6), [1,3]);
  assert.deepEqual(raised(honey, 13), [2,4]);
  assert.deepEqual(warpShafts(byId('overshot-blocks').draft), [1,2,1,2,3,2,3,4,3,4,1,2,3,4,3,2,1,4,3,4,3,2,3,2,1,2,1]);
  const log = byId('log-cabin').draft;
  assert.deepEqual(Array.from({length: 8}, (_, i) => log.threading.map(row => row[i]).find(Boolean)),
    [0,1,0,1,1,0,1,0].map(i => log.patternColors[i].id));
  assert.deepEqual(warpShafts(byId('twill-tabby').draft).slice(10,22), [3,4,5,6,3,4,5,6,3,4,5,6]);
});

test('double-weave bottom picks hold up the complete top layer', () => {
  const draft = byId('separate').draft;
  assert.deepEqual([0,1,2,3].map(p => raised(draft,p)), [[1],[3],[1,2,3],[1,3,4]]);
  assert.deepEqual([0,1,2,3].map(p => raised(byId('doublewidth').draft,p)), [[1],[1,2,3],[1,3,4],[3]]);
});

test('editor transfer preserves Chandler drafts and avoids repeating edge-balanced excerpts', () => {
  for (const entry of catalog.patterns) {
    const payload = get(`buildTransferPayload(getPatternById(${JSON.stringify(entry.id)}))`);
    assert.equal(payload.format, 'weaving-draft-data');
    assert.equal(payload.version, 3);
    assert.equal(payload.preview.repeatX, 1);
    assert.equal(payload.preview.repeatY, 1);
    assert.match(payload.meta.source, /Learning to Weave/);
    assert.deepEqual(payload.draft, patterns.find(p => p.id === entry.id).draft);
  }
  assert.equal(get('buildTransferPayload(getPatternById("plain-weave")).preview.repeatX'), 4);
});

test('library sections separate basic categories from publications without losing families', () => {
  const sections = get('buildLibrarySections()');
  const basic = sections.filter(section => section.collection === 'basic');
  const published = sections.filter(section => section.collection === 'published');
  assert.equal(basic.length, new Set(families.filter(family => !family.book).map(family => family.category)).size);
  assert.equal(published.length, 3);
  const chandler = published.find(section => section.id === 'published-learning-to-weave');
  const dixon = published.find(section => section.id === 'published-handweavers-pattern-directory');
  const handwoven = published.find(section => section.id === 'published-handwoven');
  assert.equal(chandler.title, 'Learning to Weave');
  assert.equal(chandler.families.length, 11);
  assert.equal(dixon.title, dixonCatalog.source.title);
  assert.equal(dixon.families.length, dixonCatalog.groups.length);
  assert.equal(handwoven.title, 'Handwoven');
  assert.equal(handwoven.families.length, 39);
  assert.equal(new Set(sections.map(section => section.id)).size, sections.length);
  const sectionFamilies = sections.flatMap(section => section.families);
  assert.deepEqual(sectionFamilies.map(family => family.id).sort(), families.map(family => family.id).sort());
  for (const section of sections) {
    assert.ok(section.families.every(family => Boolean(family.book) === (section.collection === 'published')));
  }
});

test('separate publications retain separate sections even when their category labels match', () => {
  const sections = get(`(() => {
    const original = patternFamilies.find(family => family.book);
    const other = {
      ...original,
      id: 'other-publication-lesson',
      publicationId: 'weaving-quarterly',
      patterns: [],
      memberIds: []
    };
    return buildLibrarySections([original, other]).map(section => ({
      id: section.id,
      collection: section.collection,
      familyIds: section.families.map(family => family.id)
    }));
  })()`);
  assert.equal(sections.length, 2);
  assert.deepEqual(sections.map(section => section.id).sort(), ['published-learning-to-weave', 'published-weaving-quarterly']);
  assert.ok(sections.every(section => section.collection === 'published' && section.familyIds.length === 1));
});


test('every Dixon entry has a source and belongs to exactly one section of its publication', () => {
  const dixonFamilies = families.filter(family => family.publicationId === 'handweavers-pattern-directory');
  assert.ok(dixonCatalog.patterns.length > 0);
  assert.ok(dixonCatalog.groups.length > 0);
  assert.equal(dixonFamilies.length, dixonCatalog.groups.length);
  assert.equal(dixonFamilies.flatMap(family => family.memberIds).length, dixonCatalog.patterns.length);
  const groupIds = new Set(dixonCatalog.groups.map(group => group.id));
  assert.equal(groupIds.size, dixonCatalog.groups.length);
  for (const entry of dixonCatalog.patterns) {
    assert.ok(entry.title && entry.pages && entry.description, `${entry.id}: source context`);
    assert.ok(groupIds.has(entry.groupId), `${entry.id}: known group`);
    assert.equal(families.filter(family => family.memberIds.includes(entry.id)).length, 1, entry.id);
    const family = dixonFamilies.find(candidate => candidate.memberIds.includes(entry.id));
    assert.ok(family, `${entry.id}: belongs to Dixon`);
    const pattern = patterns.find(candidate => candidate.id === entry.id);
    assert.equal(pattern.publicationId, 'handweavers-pattern-directory');
    assert.match(pattern.source, /Anne Dixon/);
    assert.ok(pattern.source.includes(dixonCatalog.source.title));
    assert.equal(get(`resolveFamilyRoute(${JSON.stringify(entry.id)}).focusPattern.id`), entry.id);
    assert.equal(get(`resolveFamilyRoute(${JSON.stringify(entry.id)}).family.id`), family.id);
  }
});

test('Dixon contains patterns only, without PDF or source-image entries', () => {
  assert.equal(dixonCatalog.patterns.length, 571);
  assert.ok(!fs.existsSync(path.join(root, 'assets/patterns/dixon-pages')));
  for (const entry of dixonCatalog.patterns) {
    assert.ok(!entry.referenceOnly && !entry.referenceImage, entry.id);
    assert.ok(entry.threading.length && entry.lifts.length, entry.id);
    assert.ok(!entry.id.startsWith('dixon-page-'), entry.id);
  }
});

test('editable Dixon drafts preserve every source threading, lift, and color assignment through transfer', () => {
  const editable = dixonCatalog.patterns.filter(entry => !entry.referenceOnly);
  assert.ok(editable.length > 0);
  for (const entry of editable) {
    const pattern = patterns.find(candidate => candidate.id === entry.id);
    const draft = pattern.draft;
    const label = entry.id;
    assert.ok(Number.isInteger(entry.shafts) && entry.shafts > 0, label);
    assert.ok(entry.threading.length > 0 && entry.lifts.length > 0, label);
    assert.equal(draft.shafts, entry.shafts, label);
    assert.equal(draft.warp, entry.threading.length, label);
    assert.equal(draft.picks, entry.lifts.length * (entry.tabby ? 2 : 1), label);
    assert.deepEqual(warpShafts(draft), entry.threading, label);
    const palette = draft.patternColors;
    for (let warp = 0; warp < draft.warp; warp++) {
      assert.ok(Number.isInteger(entry.threading[warp]) && entry.threading[warp] >= 1 && entry.threading[warp] <= entry.shafts, label);
      const assigned = draft.threading.map(row => row[warp]).filter(Boolean);
      assert.equal(assigned.length, 1, label);
      const colorIndex = entry.warpColors?.[warp % entry.warpColors.length] ?? 0;
      assert.equal(assigned[0], palette[colorIndex].id, label);
    }
    for (let pick = 0; pick < draft.picks; pick++) {
      const sourceIndex = entry.tabby ? Math.floor(pick / 2) : pick;
      const isTabby = entry.tabby && pick % 2;
      const expected = isTabby ? entry.tabby[sourceIndex % entry.tabby.length] : entry.lifts[sourceIndex];
      assert.ok(expected.length <= entry.shafts && (expected.length > 0 || entry.manualTechnique), `${label}: valid shed`);
      assert.equal(new Set(expected).size, expected.length, `${label}: duplicate lifted shaft`);
      assert.ok(expected.every(shaft => Number.isInteger(shaft) && shaft >= 1 && shaft <= entry.shafts), label);
      assert.deepEqual(raised(draft, pick), [...expected].sort((a, b) => a - b), `${label}, pick ${pick + 1}`);
      const assigned = draft.treadling[pick].filter(Boolean);
      assert.equal(assigned.length, 1, label);
      const colorIndex = isTabby ? 0 : entry.weftColors?.[sourceIndex % entry.weftColors.length] ?? 1;
      assert.equal(assigned[0], palette[colorIndex].id, label);
    }
    if (entry.colors) assert.deepEqual(palette.map(color => color.value), entry.colors, label);
    const payload = get(`buildTransferPayload(getPatternById(${JSON.stringify(entry.id)}))`);
    assert.equal(payload.format, 'weaving-draft-data');
    assert.equal(payload.version, 3);
    assert.equal(payload.preview.repeatX, 1);
    assert.equal(payload.preview.repeatY, 1);
    assert.equal(payload.meta.source, pattern.source);
    assert.deepEqual(payload.draft, draft, label);
  }
});

test('Dixon retains source exceptions and expanded repeats', () => {
  const entry = id => dixonCatalog.patterns.find(pattern => pattern.id === id);
  assert.deepEqual(entry('dixon-p029-s01').lifts, [[1, 3], [2, 4]]);
  assert.equal(entry('dixon-p169-s01').threading.length, 42);
  assert.equal(entry('dixon-p185-s01').threading.length, 56);
  assert.equal(entry('dixon-p188-s03').lifts.length, 17);
  assert.equal(entry('dixon-p189-s03').lifts.length, 14);
  assert.match(entry('dixon-p189-s03').description, /caption/);
  assert.ok(entry('dixon-p037-s02'));
  assert.equal(entry('dixon-p153-s01'), undefined);
  assert.equal(entry('dixon-p155-s06'), undefined);
  assert.equal(entry('dixon-p176-s03').lifts.length, 46);
});

test('search covers every draft and finds matching weaves across all collections', () => {
  const ids = get('buildPatternSearchIndex().map(entry => entry.pattern.id)');
  assert.deepEqual(ids.sort(), patterns.map(pattern => pattern.id).sort());
  assert.equal(new Set(ids).size, patterns.length);
  const results = query => get(`filterPatternSearchEntries(buildPatternSearchIndex(), ${JSON.stringify(query)}).map(entry => ({id: entry.pattern.id, collection: entry.collectionId}))`);
  assert.equal(results('   ').length, patterns.length);
  const twills = results('twill');
  const twillCollections = new Set(twills.map(entry => entry.collection));
  ['basic', 'handweavers-pattern-directory', 'learning-to-weave', 'handwoven'].forEach(collection =>
    assert.ok(twillCollections.has(collection), collection)
  );
  assert.deepEqual(results('TWÍLL'), twills);
  const dixonTwills = results('Dixon twill');
  assert.ok(dixonTwills.length > 0 && dixonTwills.length < twills.length);
  assert.ok(dixonTwills.every(entry => entry.collection === 'handweavers-pattern-directory'));
  assert.ok(results("monk's belt").length > 0);
  assert.deepEqual(results('unfindableweavexyz'), []);
});

test('Handwoven is organized by issue and every entry is an editable credited draft', () => {
  assert.equal(handwovenCatalog.groups.length, 39);
  assert.ok(handwovenCatalog.patterns.length > 0);
  const correctedIssueCounts = {
    'handwoven-2023-05-06': 15,
    'handwoven-2024-i-winter': 19,
    'handwoven-2024-ii-spring': 14,
    'handwoven-2024-iii-summer': 9,
    'handwoven-2025-iii-summer': 19,
    'handwoven-2026-iii-summer': 26
  };
  for (const [groupId, count] of Object.entries(correctedIssueCounts)) {
    const entries = handwovenCatalog.patterns.filter(entry => entry.groupId === groupId);
    assert.equal(entries.length, count, groupId);
    assert.ok(entries.every(entry => entry.threading.length > 32), `${groupId}: full-width threading`);
  }
  for (const [id, ends, picks] of [
    ['hw-2023-05-06-p48-s01', 527, 821],
    ['hw-2023-05-06-p51-s01', 505, 579],
    ['hw-2023-05-06-p54-s01', 255, 1657],
    ['hw-2024-i-winter-p22-s01', 399, 895],
    ['hw-2024-i-winter-p60-s06', 432, 1512],
    ['hw-2024-ii-spring-p38-s01', 951, 2713],
    ['hw-2024-iii-summer-p24-s01', 121, 2049],
    ['hw-2025-iii-summer-p18-s01', 660, 852],
    ['hw-2026-iii-summer-p42-s01', 395, 910]
  ]) {
    const entry = handwovenCatalog.patterns.find(candidate => candidate.id === id);
    assert.deepEqual([entry.threading.length, entry.lifts.length], [ends, picks], id);
  }
  assert.equal(new Set(handwovenCatalog.patterns.map(entry => entry.id)).size, handwovenCatalog.patterns.length);
  const groupIds = new Set(handwovenCatalog.groups.map(group => group.id));
  for (const group of handwovenCatalog.groups) {
    assert.match(group.title, /20\d{2}$/);
    assert.ok(handwovenCatalog.patterns.some(entry => entry.groupId === group.id), group.id);
  }
  for (const entry of handwovenCatalog.patterns) {
    assert.ok(groupIds.has(entry.groupId), entry.id);
    assert.ok(entry.title && entry.pages && entry.description && entry.designer, `${entry.id}: context`);
    assert.ok(entry.threading.length && entry.lifts.length, entry.id);
    assert.ok(!entry.referenceOnly && !entry.referenceImage, entry.id);
    const pattern = patterns.find(candidate => candidate.id === entry.id);
    assert.match(pattern.source, /Handwoven/);
    assert.match(pattern.source, new RegExp(entry.designer.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.equal(get(`resolveFamilyRoute(${JSON.stringify(entry.id)}).focusPattern.id`), entry.id);
    const payload = get(`buildTransferPayload(getPatternById(${JSON.stringify(entry.id)}))`);
    assert.equal(payload.format, 'weaving-draft-data');
    assert.deepEqual(payload.draft, pattern.draft);
  }
  assert.equal(get(`filterPatternSearchEntries(buildPatternSearchIndex(), 'Handwoven').length`), handwovenCatalog.patterns.length);
  assert.ok(handwovenCatalog.patterns.every(entry => !entry.manualTechnique));
});
