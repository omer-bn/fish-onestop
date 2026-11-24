const assert = require("assert");
const G = require("./group.js");

const species = [
  { id: "b", latin: "Beta beta", sea: "red", family: { latin: "Balistidae", english: "Triggerfishes", hebrew: "נצרניים" } },
  { id: "a", latin: "Alpha alpha", sea: "red", family: { latin: "Balistidae", english: "Triggerfishes", hebrew: "נצרניים" } },
  { id: "c", latin: "Gamma gamma", sea: "mediterranean", family: { latin: "Atherinidae", english: "Silversides", hebrew: "אדרוניים" } },
  { id: "d", latin: "Delta delta", sea: "mediterranean", family: {} },
  { id: "e", latin: "Epsilon epsilon", sea: "black", family_latin: "Zeidae" },
];

const groups = G.groupByFamily(species);
assert.deepStrictEqual(groups.map((group) => group.latin), ["Atherinidae", "Balistidae", "Zeidae", ""]);
assert.deepStrictEqual(groups[1].species.map((row) => row.latin), ["Alpha alpha", "Beta beta"]);
assert.strictEqual(groups[3].species[0].id, "d");

const sites = [
  { id: "iui", sea: "red", english: "IUI" },
  { id: "achziv", sea: "mediterranean", english: "Achziv" },
  { id: "jaffa", sea: "mediterranean", english: "Jaffa" },
  { id: "other", sea: "black", english: "Other" },
];
assert.deepStrictEqual(G.seasPresent(sites, species), ["mediterranean", "red", "black"]);
assert.deepStrictEqual(G.sitesForSea(sites, "mediterranean").map((row) => row.id), ["achziv", "jaffa"]);
assert.deepStrictEqual(G.sitesForSea(sites, "red").map((row) => row.id), ["iui"]);
assert.deepStrictEqual(G.sitesForSea(sites, ""), []);
assert.deepStrictEqual(G.sitesForSea(sites, "nope"), []);

console.log("group ok");
