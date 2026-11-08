const assert = require("assert");
const Site = require("./site.js");

const achziv = [
  { id: "he", siteId: "achziv", speciesId: "med-sparus-aurata", date: "2026-09-15", count: 9, observer: "דנה לוי", demo: false },
  { id: "en", siteId: "achziv", speciesId: "med-sparus-aurata", date: "2026-09-15", count: 9, observer: "Dana Levi", demo: false },
  { id: "demo", siteId: "achziv", speciesId: "med-siganus-luridus", date: "2026-08-02", count: 12, observer: "עומר", demo: true },
];
const other = [
  { id: "x", siteId: "iui", speciesId: "red-amphiprion-bicinctus", date: "2026-06-12", count: 6, demo: true },
];

const field = Site.fieldRecordsForSite(achziv.concat(other), "achziv");
assert.deepStrictEqual(field.map((row) => row.id), ["he", "en"]);
assert.strictEqual(Site.fieldRecordsForSite(other, "iui").length, 0);
assert.strictEqual(Site.hasExampleRowsAtSite(achziv, "achziv"), true);
assert.strictEqual(Site.hasExampleRowsAtSite([], "dolphin-reef"), false);

const seasons = Site.siteSeasons(field);
assert.strictEqual(seasons.undated, 0);
assert.strictEqual(seasons.years.length, 1);
assert.strictEqual(seasons.years[0].seasonalYear, 2026);
assert.deepStrictEqual(seasons.years[0].seasons.map((item) => item.id), ["winter", "spring", "summer", "autumn"]);
const autumn = seasons.years[0].seasons[3];
const winter = seasons.years[0].seasons[0];
assert.strictEqual(winter.status, "no-reports");
assert.strictEqual(winter.fish, null);
assert.strictEqual(winter.speciesCount, null);
assert.strictEqual(autumn.status, "reported");
assert.strictEqual(autumn.speciesCount, 1);
assert.strictEqual(autumn.fish.sum, 18);
assert.strictEqual(autumn.uncertain, true);
assert.strictEqual(autumn.duplicateGroups.length, 1);
assert.deepStrictEqual(autumn.duplicateGroups[0].reporters, ["דנה לוי", "Dana Levi"]);

assert.deepStrictEqual(Site.seasonOf("2025-12-31"), { id: "winter", seasonalYear: 2026, key: "2026-winter" });
assert.strictEqual(Site.seasonOf("2026-01-02").id, "winter");
assert.strictEqual(Site.seasonOf("2026-02-28").seasonalYear, 2026);
assert.strictEqual(Site.seasonOf("2026-03-01").id, "spring");
assert.strictEqual(Site.seasonOf("2026-06-21").id, "summer");
assert.strictEqual(Site.seasonOf("2026-09-15").id, "autumn");
assert.strictEqual(Site.seasonOf("nope"), null);

const mixed = Site.siteSeasons([
  { id: "a", speciesId: "a", date: "2024-01-02", count: 0 },
  { id: "b", speciesId: "a", date: "2024-01-03", count: null },
  { id: "c", speciesId: "b", date: "2024-01-04", count: "" },
  { id: "d", speciesId: "b", date: "2024-07-01", count: 4 },
  { id: "e", speciesId: "", date: "2024-07-02", count: 1 },
  { id: "f", date: "", speciesId: "c", count: 5 },
]);
assert.strictEqual(mixed.undated, 1);
const year = mixed.years[0];
assert.strictEqual(year.seasonalYear, 2024);
const win = year.seasons[0];
assert.strictEqual(win.reports, 3);
assert.strictEqual(win.speciesCount, 2);
assert.strictEqual(win.fish.known, true);
assert.strictEqual(win.fish.sum, 0);
assert.strictEqual(win.fish.unknownRows, 2);
assert.strictEqual(win.uncertain, false);
const summer = year.seasons[2];
assert.strictEqual(summer.speciesCount, 1);
assert.strictEqual(summer.fish.sum, 5);
const spring = year.seasons[1];
assert.strictEqual(spring.status, "no-reports");

const unknownOnly = Site.siteSeasons([{ id: "u", speciesId: "a", date: "2023-05-01", count: null }]);
const may = unknownOnly.years[0].seasons[1];
assert.strictEqual(may.fish.known, false);
assert.strictEqual(may.fish.sum, null);
assert.strictEqual(may.speciesCount, 1);
assert.notStrictEqual(may.status, "no-reports");

assert.strictEqual(Site.knownCount(null), null);
assert.strictEqual(Site.knownCount(""), null);
assert.strictEqual(Site.knownCount("  "), null);
assert.strictEqual(Site.knownCount(-1), null);
assert.strictEqual(Site.knownCount("9"), 9);
assert.strictEqual(Site.knownCount(0), 0);

const notDupes = Site.duplicateGroups([
  { speciesId: "a", date: "2026-09-15", count: 9, observer: "A" },
  { speciesId: "a", date: "2026-09-15", count: 8, observer: "B" },
  { speciesId: "b", date: "2026-09-15", count: 9, observer: "C" },
]);
assert.strictEqual(notDupes.length, 0);

console.log("site detail ok");
