# Published pattern catalogs

Load each publication’s JavaScript catalog before the inline script in `pattern-library.html`, then register it in `bookCatalogs`. Its metadata supplies attribution, sections, and the nested sidebar. The search modal indexes every draft across publications and renders fabric previews lazily. Small drafts repeat within their previews.

A catalog contains:

- `source`: stable `id`, `title`, `author`, `edition`, `publisher`, `year`, `groupLabel`, and optional `note`, `transcriptionNote`, `notesPath`.
- `groups`: stable `id`, `title`, and optional chapter/page metadata. Chandler’s original `lesson` field remains supported.
- `patterns`: unique `id`, matching `groupId`, `title`, printed `pages`, `description`, `shafts`, one-based `threading`, and `lifts` (raised shafts for every pick). Periodicals may add a per-pattern `designer` credit.

Expand numbered picks and brackets before adding an entry. Optional `tabby` inserts alternating ground sheds after each pattern pick, using palette color 0. Encode all picks explicitly instead when tabby precedes the pattern, changes color, or appears only at specified positions. Never insert tabby twice.

Optional `colors`, `thickness`, `warpColors`, and `weftColors` specify the palette and zero-based color sequences. The renderer consolidates identical sheds into treadles without changing the lift plan.

Hand-worked entries use `manualTechnique: true`, a descriptive `kind`, the supporting numeric draft, and manual instructions in `description`. Empty lifts can indicate closed-shed hand work. State which effects the drawdown cannot depict. Document source ambiguities without inventing missing data.

Catalogs contain patterns, not PDF or page-image references. Omit groups that contain only introductory text. Keep stable pattern IDs when extending a publication.

Run `node --test tests/pattern-library.test.cjs` to check membership, numeric assignments, and editor transfer. Check the nested sidebar and representative draft opening in the browser after UI changes.
