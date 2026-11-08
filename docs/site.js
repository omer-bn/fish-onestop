/* Site history for the static GitHub Pages catalog.

Field records are published sightings at that site that are not marked demo.
Demo rows stay on the observations atlas and are not counted here.

Seasons are the meteorological seasons used for Israel:
  winter  December–February
  spring  March–May
  summer  June–August
  autumn  September–November
December belongs with the following January and February.
A seasonal year runs from that December through the next November
and is labeled by the calendar year of its January.

Fish figures add the counts written on the rows. A missing count is
unknown, not zero. A season with no rows is "no reports," which is
not zero fish. Distinct species is the set of species ids in that
season, so the same species on several rows counts once.

Rows that share a date, species, and written count are flagged.
Reporter strings are not merged, even when they look like translations
of one name. The summed count stays the sum of the rows and is marked
uncertain.
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof root !== "undefined") root.SiteDetail = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const SEASON_ORDER = ["winter", "spring", "summer", "autumn"];

  function knownCount(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "string" && value.trim() === "") return null;
    const number = typeof value === "string" ? Number(value.trim()) : Number(value);
    if (!Number.isFinite(number) || number < 0) return null;
    return number;
  }

  function parseDate(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    return { year: year, month: month, day: day };
  }

  function seasonOf(value) {
    const date = parseDate(value);
    if (!date) return null;
    let id;
    let seasonalYear;
    if (date.month === 12) {
      id = "winter";
      seasonalYear = date.year + 1;
    } else if (date.month <= 2) {
      id = "winter";
      seasonalYear = date.year;
    } else if (date.month <= 5) {
      id = "spring";
      seasonalYear = date.year;
    } else if (date.month <= 8) {
      id = "summer";
      seasonalYear = date.year;
    } else {
      id = "autumn";
      seasonalYear = date.year;
    }
    return { id: id, seasonalYear: seasonalYear, key: seasonalYear + "-" + id };
  }

  function fieldRecordsForSite(sightings, siteId) {
    return (sightings || [])
      .filter(function (row) {
        return row && row.siteId === siteId && row.demo !== true;
      })
      .slice()
      .sort(function (a, b) {
        const byDate = String(b.date || "").localeCompare(String(a.date || ""));
        if (byDate) return byDate;
        return String(b.id || "").localeCompare(String(a.id || ""));
      });
  }

  function hasExampleRowsAtSite(sightings, siteId) {
    return (sightings || []).some(function (row) {
      return row && row.siteId === siteId && row.demo === true;
    });
  }

  function duplicateGroups(records) {
    const buckets = new Map();
    (records || []).forEach(function (row) {
      const count = knownCount(row.count);
      const speciesId = String(row.speciesId || "");
      const date = parseDate(row.date);
      if (!date || !speciesId || count === null) return;
      const key = date.year + "-" + String(date.month).padStart(2, "0") + "-" + String(date.day).padStart(2, "0") + "|" + speciesId + "|" + count;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(row);
    });
    const groups = [];
    buckets.forEach(function (rows) {
      if (rows.length < 2) return;
      groups.push({
        date: String(rows[0].date),
        speciesId: rows[0].speciesId,
        count: knownCount(rows[0].count),
        reporters: rows.map(function (row) { return String(row.observer || "").trim(); }),
        ids: rows.map(function (row) { return row.id; }),
      });
    });
    return groups;
  }

  function summarizeSeason(records) {
    const species = new Set();
    let knownSum = 0;
    let knownRows = 0;
    let unknownRows = 0;
    let explicitZero = 0;
    records.forEach(function (row) {
      const speciesId = String(row.speciesId || "").trim();
      if (speciesId) species.add(speciesId);
      const count = knownCount(row.count);
      if (count === null) unknownRows += 1;
      else {
        knownRows += 1;
        knownSum += count;
        if (count === 0) explicitZero += 1;
      }
    });
    const dupes = duplicateGroups(records);
    return {
      reports: records.length,
      speciesCount: species.size,
      fish: knownRows === 0
        ? { known: false, sum: null, unknownRows: unknownRows, knownRows: 0 }
        : { known: true, sum: knownSum, unknownRows: unknownRows, knownRows: knownRows, explicitZero: explicitZero },
      uncertain: dupes.length > 0,
      duplicateGroups: dupes,
    };
  }

  function siteSeasons(records) {
    const dated = [];
    let undated = 0;
    (records || []).forEach(function (row) {
      const season = seasonOf(row && row.date);
      if (!season) {
        undated += 1;
        return;
      }
      dated.push({ row: row, season: season });
    });
    const years = [];
    const byYear = new Map();
    dated.forEach(function (item) {
      const year = item.season.seasonalYear;
      if (!byYear.has(year)) {
        const block = { seasonalYear: year, seasons: [] };
        byYear.set(year, block);
        years.push(block);
      }
    });
    years.sort(function (a, b) { return b.seasonalYear - a.seasonalYear; });
    years.forEach(function (block) {
      block.seasons = SEASON_ORDER.map(function (id) {
        const rows = dated
          .filter(function (item) {
            return item.season.seasonalYear === block.seasonalYear && item.season.id === id;
          })
          .map(function (item) { return item.row; });
        if (!rows.length) {
          return { id: id, seasonalYear: block.seasonalYear, reports: 0, status: "no-reports", speciesCount: null, fish: null, uncertain: false, duplicateGroups: [] };
        }
        const summary = summarizeSeason(rows);
        return {
          id: id,
          seasonalYear: block.seasonalYear,
          reports: summary.reports,
          status: "reported",
          speciesCount: summary.speciesCount,
          fish: summary.fish,
          uncertain: summary.uncertain,
          duplicateGroups: summary.duplicateGroups,
        };
      });
    });
    return { years: years, undated: undated };
  }

  return {
    SEASON_ORDER: SEASON_ORDER,
    knownCount: knownCount,
    parseDate: parseDate,
    seasonOf: seasonOf,
    fieldRecordsForSite: fieldRecordsForSite,
    hasExampleRowsAtSite: hasExampleRowsAtSite,
    duplicateGroups: duplicateGroups,
    siteSeasons: siteSeasons,
  };
});
