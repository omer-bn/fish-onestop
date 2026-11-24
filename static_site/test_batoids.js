const assert = require("assert");
const fs = require("fs");
const path = require("path");
const G = require("./group.js");

const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, "../docs/data/catalog.json"), "utf8"));
const observations = JSON.parse(fs.readFileSync(path.join(__dirname, "../docs/data/observations.json"), "utf8"));

const expected = [
  ["med-bathytoshia-lata", "mediterranean", "Bathytoshia lata", "Brown stingray", "Dasyatidae"],
  ["med-pteroplatytrygon-violacea", "mediterranean", "Pteroplatytrygon violacea", "Pelagic stingray", "Dasyatidae"],
  ["med-dasyatis-marmorata", "mediterranean", "Dasyatis marmorata", "Marbled stingray", "Dasyatidae"],
  ["med-himantura-uarnak", "mediterranean", "Himantura uarnak", "Honeycomb stingray", "Dasyatidae"],
  ["red-himantura-uarnak", "red", "Himantura uarnak", "Honeycomb stingray", "Dasyatidae"],
  ["red-pastinachus-sephen", "red", "Pastinachus sephen", "Cowtail stingray", "Dasyatidae"],
  ["red-taeniurops-meyeni", "red", "Taeniurops meyeni", "Round ribbontail ray", "Dasyatidae"],
  ["med-myliobatis-aquila", "mediterranean", "Myliobatis aquila", "Common eagle ray", "Myliobatidae"],
  ["med-aetomylaeus-bovinus", "mediterranean", "Aetomylaeus bovinus", "Bull ray", "Myliobatidae"],
  ["med-rhinoptera-marginata", "mediterranean", "Rhinoptera marginata", "Lusitanian cownose ray", "Rhinopteridae"],
  ["med-mobula-mobular", "mediterranean", "Mobula mobular", "Spinetail devil ray", "Mobulidae"],
  ["med-gymnura-altavela", "mediterranean", "Gymnura altavela", "Spiny butterfly ray", "Gymnuridae"],
  ["med-rhinobatos-rhinobatos", "mediterranean", "Rhinobatos rhinobatos", "Common guitarfish", "Rhinobatidae"],
  ["med-glaucostegus-cemiculus", "mediterranean", "Glaucostegus cemiculus", "Blackchin guitarfish", "Glaucostegidae"],
  ["med-torpedo-marmorata", "mediterranean", "Torpedo marmorata", "Marbled electric ray", "Torpedinidae"],
  ["med-torpedo-torpedo", "mediterranean", "Torpedo torpedo", "Common torpedo", "Torpedinidae"],
  ["med-torpedo-sinuspersici", "mediterranean", "Torpedo sinuspersici", "Variable torpedo ray", "Torpedinidae"],
  ["red-torpedo-sinuspersici", "red", "Torpedo sinuspersici", "Variable torpedo ray", "Torpedinidae"],
  ["med-raja-clavata", "mediterranean", "Raja clavata", "Thornback ray", "Rajidae"],
  ["med-raja-asterias", "mediterranean", "Raja asterias", "Mediterranean starry ray", "Rajidae"],
  ["med-raja-miraletus", "mediterranean", "Raja miraletus", "Brown ray", "Rajidae"],
  ["red-aetobatus-ocellatus", "red", "Aetobatus ocellatus", "Ocellated eagle ray", "Aetobatidae"],
];

const byId = new Map(catalog.species.map((row) => [row.id, row]));
for (const [id, sea, latin, english, family] of expected) {
  const row = byId.get(id);
  assert.ok(row, id);
  assert.strictEqual(row.sea, sea);
  assert.strictEqual(row.latin, latin);
  assert.strictEqual(row.english, english);
  assert.strictEqual(row.family.latin, family);
  assert.strictEqual(row.hebrew, "");
  assert.strictEqual(row.description, "");
  assert.strictEqual(row.image, "");
  assert.strictEqual(row.slide, null);
  assert.deepStrictEqual(row.tags, []);
  assert.strictEqual(row.provenance.english, "fishbase");
}

const med = expected.filter((row) => row[1] === "mediterranean").length;
const red = expected.filter((row) => row[1] === "red").length;
assert.strictEqual(med, 17);
assert.strictEqual(red, 5);
assert.strictEqual(catalog.counts.mediterranean, catalog.species.filter((row) => row.sea === "mediterranean").length);
assert.strictEqual(catalog.counts.red, catalog.species.filter((row) => row.sea === "red").length);
assert.strictEqual(catalog.counts.total, catalog.species.length);

// Already in the catalog under these names. A second row must not be added.
assert.strictEqual([...byId.keys()].filter((id) => id.includes("pastinaca")).join(), "med-dasyatis-pastinaca");
assert.strictEqual([...byId.keys()].filter((id) => id.includes("grabat")).join(), "med-taeniura-grabata");
assert.strictEqual([...byId.keys()].filter((id) => id.includes("lymma")).join(), "red-taeniura-lymma");
assert.strictEqual([...byId.keys()].filter((id) => id.includes("panthera")).join(), "red-torpedo-panthera");
assert.ok(![...byId.keys()].some((id) => id.includes("kuhlii") || id.includes("gerrardi") || id.includes("imbricata")));
assert.ok(!byId.has("red-mobula-mobular"));

const blob = JSON.stringify(observations);
for (const [id] of expected) assert.ok(!blob.includes(id), id);

const groups = G.groupByFamily(catalog.species);
const names = groups.map((group) => group.latin);
assert.deepStrictEqual(names, [...names].sort((a, b) => a.localeCompare(b)));
for (const group of groups) {
  const latin = group.species.map((row) => row.latin);
  assert.deepStrictEqual(latin, [...latin].sort((a, b) => a.localeCompare(b)), group.latin);
}
const rajidae = groups.find((group) => group.latin === "Rajidae");
assert.deepStrictEqual(rajidae.species.map((row) => row.latin), ["Raja asterias", "Raja clavata", "Raja miraletus"]);

console.log("batoids ok", med, "mediterranean", red, "red");
