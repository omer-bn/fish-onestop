/* Shared ordering for the static catalog and the report form.

Families are sorted by Latin name. Species inside a family are sorted
by Latin name. A species with no family name is kept, in a final group,
rather than dropped. Sites are listed only for the sea the person chose.
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof root !== "undefined") root.FishGroup = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const SEA_ORDER = ["mediterranean", "red"];

  function familyOf(species) {
    const raw = species && species.family;
    if (raw && typeof raw === "object") {
      return {
        latin: String(raw.latin || "").trim(),
        english: String(raw.english || "").trim(),
        hebrew: String(raw.hebrew || "").trim(),
      };
    }
    return {
      latin: String((species && (species.family_latin || raw)) || "").trim(),
      english: String((species && species.family_english) || "").trim(),
      hebrew: String((species && species.family_hebrew) || "").trim(),
    };
  }

  function byLatin(a, b) {
    return String(a.latin || a.id || "").localeCompare(String(b.latin || b.id || ""), "en");
  }

  function groupByFamily(species) {
    const buckets = new Map();
    (species || []).forEach(function (row) {
      const family = familyOf(row);
      const key = family.latin || "";
      if (!buckets.has(key)) buckets.set(key, { latin: family.latin, english: family.english, hebrew: family.hebrew, species: [] });
      const bucket = buckets.get(key);
      if (!bucket.english && family.english) bucket.english = family.english;
      if (!bucket.hebrew && family.hebrew) bucket.hebrew = family.hebrew;
      bucket.species.push(row);
    });
    const groups = Array.from(buckets.values());
    groups.forEach(function (group) {
      group.species.sort(byLatin);
    });
    groups.sort(function (a, b) {
      if (!a.latin && b.latin) return 1;
      if (a.latin && !b.latin) return -1;
      return a.latin.localeCompare(b.latin, "en");
    });
    return groups;
  }

  function seasPresent(sites, species) {
    const found = new Set();
    (sites || []).forEach(function (row) { if (row && row.sea) found.add(row.sea); });
    (species || []).forEach(function (row) { if (row && row.sea) found.add(row.sea); });
    const ordered = SEA_ORDER.filter(function (sea) { return found.has(sea); });
    Array.from(found).filter(function (sea) { return SEA_ORDER.indexOf(sea) === -1; }).sort().forEach(function (sea) {
      ordered.push(sea);
    });
    return ordered;
  }

  function sitesForSea(sites, sea) {
    if (!sea) return [];
    return (sites || []).filter(function (row) { return row && row.sea === sea; }).slice().sort(function (a, b) {
      return String(a.english || a.id || "").localeCompare(String(b.english || b.id || ""), "en");
    });
  }

  return {
    familyOf: familyOf,
    groupByFamily: groupByFamily,
    seasPresent: seasPresent,
    sitesForSea: sitesForSea,
  };
});
