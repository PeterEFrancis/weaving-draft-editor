import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const magazineDir = "/Users/peterfrancis/Library/Mobile Documents/com~apple~CloudDocs/Books/Handwoven Magazine";
const inputs = process.argv.slice(2);

if (!inputs.length) throw new Error("Pass one or more extracted Handwoven JSON files.");

const monthNames = {
  "01-02": "January/February",
  "03-04": "March/April",
  "05-06": "May/June",
  "09-10": "September/October",
  "10-11": "October/November",
  "11-12": "November/December"
};
const expected = fs.readdirSync(magazineDir)
  .filter(name => name.endsWith(".pdf"))
  .sort()
  .map(name => {
    const stem = path.basename(name, ".pdf");
    const [year, months] = stem.split(" ");
    return { id: `handwoven-${year}-${months}`, title: `${monthNames[months]} ${year}`, year, months };
  });
const supplied = inputs.flatMap(file => JSON.parse(fs.readFileSync(file, "utf8")));
const byId = new Map(supplied.map(issue => [issue.id, issue]));
const included = expected.filter(issue => byId.has(issue.id));
if (!included.length) throw new Error("No recognized Handwoven issues supplied.");
const omitted = expected.filter(issue => !byId.has(issue.id));
const coverageNote = omitted.length
  ? ` Issues not yet included: ${omitted.map(issue => issue.title).join(", ")}.`
  : "";

const groups = [];
const patterns = [];
const ids = new Set();
for (const expectedIssue of included) {
  const issue = byId.get(expectedIssue.id);
  if (!Array.isArray(issue.patterns) || !issue.patterns.length) throw new Error(`${issue.id}: no patterns`);
  groups.push({ id: issue.id, title: expectedIssue.title, year: Number(expectedIssue.year) });
  const issuePatterns = issue.patterns.slice().sort((a, b) =>
    (Number.parseInt(a.pages, 10) || 0) - (Number.parseInt(b.pages, 10) || 0) || String(a.id).localeCompare(String(b.id))
  );
  for (const original of issuePatterns) {
    const entry = { ...original, groupId: issue.id };
    ["referenceImage", "referenceOnly", "sourcePage", "file"].forEach(key => delete entry[key]);
    Object.keys(entry).filter(key => key.startsWith("_")).forEach(key => delete entry[key]);
    if (!entry.id || ids.has(entry.id)) throw new Error(`${issue.id}: duplicate or missing id ${entry.id}`);
    ids.add(entry.id);
    if (!entry.title || !entry.pages || !entry.description) throw new Error(`${entry.id}: missing source context`);
    if (!Number.isInteger(entry.shafts) || entry.shafts < 2) throw new Error(`${entry.id}: invalid shaft count`);
    if (!Array.isArray(entry.threading) || !entry.threading.length || entry.threading.some(shaft => !Number.isInteger(shaft) || shaft < 1 || shaft > entry.shafts)) throw new Error(`${entry.id}: invalid threading`);
    if (!Array.isArray(entry.lifts) || !entry.lifts.length || entry.lifts.some(lift => !Array.isArray(lift) || lift.some(shaft => !Number.isInteger(shaft) || shaft < 1 || shaft > entry.shafts))) throw new Error(`${entry.id}: invalid lifts`);
    patterns.push(entry);
  }
}

const catalog = {
  source: {
    id: "handwoven",
    title: "Handwoven",
    author: "Handwoven editors and contributors",
    edition: "Selected issues",
    publisher: "Interweave / Long Thread Media",
    year: "2015–2023",
    groupLabel: "issue",
    notesPath: "assets/patterns/handwoven.md",
    note: `${patterns.length} editable drafts from ${groups.length} supplied issues. Each issue is a separate section; more source material can be added later.${coverageNote}`,
    transcriptionNote: "Drafts follow the threading, tie-up or liftplan, treadling, and color information printed with each project. Repeated structures are represented by an editable design unit or the published full-width expansion. Project notes identify manual steps and source ambiguities. Colors approximate the published yarns."
  },
  groups,
  patterns
};

const js = `// Handwoven magazine project drafts, 2015–2023.\nconst handwovenCatalog = ${JSON.stringify(catalog, null, 2)};\n`;
fs.writeFileSync(path.join(root, "assets/patterns/handwoven.js"), js);

const counts = new Map(groups.map(group => [group.id, 0]));
patterns.forEach(pattern => counts.set(pattern.groupId, counts.get(pattern.groupId) + 1));
const addedPatternNotes = groups.map(group => {
  const issuePatterns = patterns.filter(pattern => pattern.groupId === group.id);
  return `### ${group.title}\n${issuePatterns.map(pattern => `- ${pattern.title} — ${pattern.designer || "Handwoven contributor"}, pp. ${pattern.pages}`).join("\n")}`;
}).join("\n\n");
const notes = `# Handwoven\n\nThis catalog transcribes ${patterns.length} project drafts from ${groups.length} supplied issues of *Handwoven* magazine. It contains patterns only: no magazine PDFs, page images, advertisements, or photo-only references.\n\nThreading and treadling follow each issue's printed reading direction. Repeats are stored as an editable design unit or as the published full-width expansion. Colors approximate the project yarns; sett, finishing, supplementary techniques, and manual manipulation remain important parts of the published instructions. Entries that need hand work say so directly.${coverageNote}\n\n| Issue | Patterns |\n| --- | ---: |\n${groups.map(group => `| ${group.title} | ${counts.get(group.id)} |`).join("\n")}\n\n## Added patterns\n\n${addedPatternNotes}\n`;
fs.writeFileSync(path.join(root, "assets/patterns/handwoven.md"), notes);
console.log(JSON.stringify({ issues: groups.length, patterns: patterns.length }));
