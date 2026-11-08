const assert = require("assert");
const S = require("./species.js");

const clown = [
  { id: "ex-1", speciesId: "red-amphiprion-bicinctus", date: "2026-06-12", lat: 29.5, lng: 34.9, demo: true, siteEnglish: "IUI" },
];
const sparus = [
  { id: "demo-mar", speciesId: "med-sparus-aurata", date: "2026-03-19", lat: 32.16, lng: 34.79, demo: true, siteEnglish: "Herzliya" },
  { id: "b", speciesId: "med-sparus-aurata", date: "2026-09-15", lat: 33.0485, lng: 35.102, demo: false, siteEnglish: "Achziv", diveId: "dive-b" },
  { id: "a", speciesId: "med-sparus-aurata", date: "2026-09-15", lat: 33.0485, lng: 35.102, demo: false, siteEnglish: "Achziv", diveId: "dive-a" },
];

const field = S.fieldRecords(sparus.concat(clown), "med-sparus-aurata");
assert.deepStrictEqual(field.map((row) => row.id), ["b", "a"]);
assert.strictEqual(S.fieldRecords(clown, "red-amphiprion-bicinctus").length, 0);
assert.strictEqual(S.hasExampleRows(clown, "red-amphiprion-bicinctus"), true);
assert.strictEqual(S.hasExampleRows(sparus, "med-sparus-aurata"), true);
assert.strictEqual(S.hasExampleRows([], "none"), false);

const placed = S.markerGroups(field);
assert.strictEqual(placed.groups.length, 1);
assert.strictEqual(placed.groups[0].lat, 33.0485);
assert.strictEqual(placed.groups[0].records.length, 2);
assert.strictEqual(placed.unlocated.length, 0);
assert.ok(!JSON.stringify(placed).includes("Herzliya"));

const missing = S.markerGroups([
  { id: "x", lat: null, lng: null, date: "2026-01-01" },
  { id: "y", lat: 91, lng: 10, date: "2026-01-02" },
  { id: "z", lat: "nope", lng: 34, date: "2026-01-03" },
]);
assert.strictEqual(missing.groups.length, 0);
assert.strictEqual(missing.unlocated.length, 3);
assert.strictEqual(S.validCoord(null, null), null);
assert.strictEqual(S.validCoord("", ""), null);
assert.deepStrictEqual(S.validCoord(0, 0), [0, 0]);

const thin = S.seasonSummary(field);
assert.strictEqual(thin.enough, false);
assert.strictEqual(thin.dated, 2);
assert.strictEqual(thin.used, 1);
assert.strictEqual(thin.months[8], 2);
assert.strictEqual(Object.prototype.hasOwnProperty.call(thin, "best"), false);
assert.strictEqual(S.seasonSummary(clown.filter((row) => row.demo !== true)).enough, false);

const spread = S.seasonSummary([
  { date: "2024-01-02" },
  { date: "2024-01-20" },
  { date: "2024-06-01" },
  { date: "2025-06-15" },
  { date: "not-a-date" },
]);
assert.strictEqual(spread.enough, true);
assert.strictEqual(spread.dated, 4);
assert.strictEqual(spread.months[0], 2);
assert.strictEqual(spread.months[5], 2);
assert.strictEqual(spread.best, undefined);

const dives = [
  { id: "dive-a", demo: false, startTime: "07:45" },
  { id: "dive-b", demo: true, startTime: "18:00" },
];
assert.strictEqual(S.whenLabel(field[1], dives), "2026-09-15 · 07:45");
assert.strictEqual(S.whenLabel(field[0], dives), "2026-09-15");
assert.deepStrictEqual(S.seaView("red").center, [29.54, 34.93]);
assert.strictEqual(S.seaView("unknown").zoom, 7);

console.log("species detail ok");
