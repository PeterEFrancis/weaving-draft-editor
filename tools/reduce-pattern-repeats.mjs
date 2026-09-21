import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { pathToFileURL } from "node:url";

// Compare the weave AND yarn order. A structural repeat alone can erase stripes.
export function repeatKeys(entry) {
  return {
    warp: entry.threading.map((shaft, i) => JSON.stringify([
      shaft, entry.warpColors?.[i % entry.warpColors.length] ?? 0
    ])),
    picks: entry.lifts.map((lift, i) => JSON.stringify([
      [...lift].sort((a, b) => a - b), entry.weftColors?.[i % entry.weftColors.length] ?? 1,
      entry.tabby ? [...entry.tabby[i % entry.tabby.length]].sort((a, b) => a - b) : null
    ]))
  };
}

function sampleLength(keys, pickMultiplier = 1) {
  const prefix = new Uint32Array(keys.length);
  for (let i = 1; i < keys.length; i++) {
    let matched = prefix[i - 1];
    while (matched && keys[i] !== keys[matched]) matched = prefix[matched - 1];
    if (keys[i] === keys[matched]) matched++;
    prefix[i] = matched;
  }
  const period = keys.length - prefix[keys.length - 1];
  // Keep at least two motifs and about 96 threads/picks, rather than a tiny tile.
  const size = period * Math.max(2, Math.ceil(96 / (period * pickMultiplier)));
  return size <= keys.length * 2 / 3 ? size : keys.length;
}

export function reducePattern(entry) {
  if (entry.originalSize || entry.manualTechnique) return entry;
  const multiplier = entry.tabby ? 2 : 1;
  const originalSize = { warp: entry.threading.length, picks: entry.lifts.length * multiplier };
  if (Math.max(originalSize.warp, originalSize.picks) < 256 && originalSize.warp * originalSize.picks < 60000) return entry;
  const originalKeys = repeatKeys(entry);
  const warp = sampleLength(originalKeys.warp);
  const picks = sampleLength(originalKeys.picks, multiplier);
  if (warp === entry.threading.length && picks === entry.lifts.length) return entry;
  const reduced = {
    ...entry, originalSize,
    threading: entry.threading.slice(0, warp),
    lifts: entry.lifts.slice(0, picks)
  };
  if (entry.warpColors) reduced.warpColors = entry.warpColors.slice(0, warp);
  if (entry.weftColors) reduced.weftColors = entry.weftColors.slice(0, picks);
  const reducedKeys = repeatKeys(reduced);
  for (const axis of ["warp", "picks"]) {
    if (!originalKeys[axis].every((key, i) => key === reducedKeys[axis][i % reducedKeys[axis].length])) {
      throw new Error(`${entry.id}: ${axis} cannot be reconstructed exactly`);
    }
  }
  return reduced;
}

function main() {
  const root = path.resolve(import.meta.dirname, "..");
  const write = process.argv.includes("--write");
  const changed = [], inventory = [];
  for (const name of ["learning-to-weave", "handweavers-pattern-directory", "handwoven"]) {
    const file = path.join(root, "assets/patterns", `${name}.js`);
    const source = fs.readFileSync(file, "utf8");
    const declaration = /const (\w+Catalog) = /.exec(source);
    const catalog = vm.runInNewContext(`${source}\n${declaration[1]}`);
    catalog.patterns = catalog.patterns.map(entry => {
      const reduced = reducePattern(entry);
      if (reduced !== entry) changed.push(reduced.id);
      if (reduced.originalSize) inventory.push({ ...reduced, publication: catalog.source.title });
      return reduced;
    });
    if (write && catalog.patterns.some(entry => changed.includes(entry.id))) {
      fs.writeFileSync(file, `${source.slice(0, declaration.index)}const ${declaration[1]} = ${JSON.stringify(catalog, null, 2)};\n`);
    }
  }
  const rows = inventory.map(entry => `| ${entry.publication}: ${entry.title} (${entry.id}) | ${entry.originalSize.warp} × ${entry.originalSize.picks} | ${entry.threading.length} × ${entry.lifts.length * (entry.tabby ? 2 : 1)} |`);
  if (write) fs.writeFileSync(path.join(root, "assets/patterns/reduced-repeats.md"),
    `# Reduced repeating drafts\n\n${inventory.length} large drafts display several complete repeats instead of their expanded sequences. Repeating each displayed axis to its original count reconstructs every recorded shaft, lift, color, and tabby pick exactly. A final repeat may be partial. Nonrepeating borders and color sequences remain intact.\n\nCounts describe the original catalog draft, including inserted tabby picks. Source descriptions still specify any additional floating selvedges, hems, or weaving lengths.\n\n| Pattern | Original warp ends × picks | Displayed warp ends × picks |\n| --- | ---: | ---: |\n${rows.join("\n")}\n`);
  console.log(JSON.stringify({ changed: changed.length, reducedPatterns: inventory.length,
    examples: inventory.sort((a, b) => b.originalSize.warp * b.originalSize.picks - a.originalSize.warp * a.originalSize.picks)
      .slice(0, 5).map(e => ({ title: e.title, original: e.originalSize, displayed: [e.threading.length, e.lifts.length * (e.tabby ? 2 : 1)] })) }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) main();
