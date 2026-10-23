/* Basic double-cloth structures; true means warp above weft.
 * Double cloth: alternating plain-weave layers (connected weft makes a tube).
 * https://weavingspace.co.uk/threading-double-weave-on-4-shafts/
 * Deflected double cloth: four paired-shaft blocks with plain/float tie-ups.
 * https://www.denisekovnat.com/2019/12/designing-deflected-double-weave-on-8.html
 */
(function (root) {
  'use strict';
  const grid = crossing => Array.from({ length: 16 }, (_, row) => Array.from({ length: 16 }, (_, col) => crossing(row, col)));
  const presets = {
    doubleCloth: () => grid((row, col) => row % 2 !== col % 2
      ? col % 2 === 0 : (Math.floor(row / 2) + Math.floor(col / 2)) % 2 === 0),
    deflectedDoubleCloth: () => grid((row, col) => {
      // A/C and B/D interlace in plain weave. Their float fields reverse
      // sides between blocks, interlocking the two systems.
      const delta = (Math.floor(col / 4) - Math.floor(row / 4) + 4) % 4;
      return delta % 2 === 0 ? (row + col) % 2 === 0 : delta === 1;
    })
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = presets;
  if (root) root.ClothWeavePresets = presets;
})(typeof window === 'undefined' ? null : window);
