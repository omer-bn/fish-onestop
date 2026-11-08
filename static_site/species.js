/* Species detail helpers for the static GitHub Pages catalog.

Field records are published sightings that are not marked demo.
Demo rows stay on the observations atlas and are not plotted here.
A marker is created only from a record's own coordinates.
Season text is reporting frequency, and only after records fall in
at least two months with at least four dated records. Otherwise the
page says the evidence is not enough. There is no "best season".
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof root !== "undefined") root.SpeciesDetail = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const MIN_DATED = 4;
  const MIN_MONTHS = 2;

  function validCoord(lat, lng) {
    if (lat === null || lat === undefined || lng === null || lng === undefined) return null;
    if (typeof lat === "string" && lat.trim() === "") return null;
    if (typeof lng === "string" && lng.trim() === "") return null;
    const a = typeof lat === "string" ? Number(lat.trim()) : Number(lat);
    const b = typeof lng === "string" ? Number(lng.trim()) : Number(lng);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
    if (a < -90 || a > 90 || b < -180 || b > 180) return null;
    return [a, b];
  }

  function fieldRecords(sightings, speciesId) {
    return (sightings || [])
      .filter(function (row) {
        return row && row.speciesId === speciesId && row.demo !== true;
      })
      .slice()
      .sort(function (a, b) {
        const byDate = String(b.date || "").localeCompare(String(a.date || ""));
        if (byDate) return byDate;
        return String(b.id || "").localeCompare(String(a.id || ""));
      });
  }

  function hasExampleRows(sightings, speciesId) {
    return (sightings || []).some(function (row) {
      return row && row.speciesId === speciesId && row.demo === true;
    });
  }

  function markerGroups(records) {
    const groups = [];
    const index = new Map();
    const unlocated = [];
    (records || []).forEach(function (row) {
      const coord = validCoord(row.lat, row.lng);
      if (!coord) {
        unlocated.push(row);
        return;
      }
      const key = coord[0].toFixed(5) + "," + coord[1].toFixed(5);
      let group = index.get(key);
      if (!group) {
        group = { lat: coord[0], lng: coord[1], records: [] };
        index.set(key, group);
        groups.push(group);
      }
      group.records.push(row);
    });
    return { groups: groups, unlocated: unlocated };
  }

  function seasonSummary(records) {
    const months = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    let dated = 0;
    (records || []).forEach(function (row) {
      const match = String(row.date || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!match) return;
      const month = Number(match[2]);
      if (month < 1 || month > 12) return;
      months[month - 1] += 1;
      dated += 1;
    });
    const used = months.filter(function (count) { return count > 0; }).length;
    return {
      enough: dated >= MIN_DATED && used >= MIN_MONTHS,
      months: months,
      dated: dated,
      used: used,
    };
  }

  function whenLabel(record, dives) {
    const date = String((record && record.date) || "");
    const dive = (dives || []).find(function (row) {
      return row && record && row.id && row.id === record.diveId;
    });
    if (!dive || dive.demo === true) return date;
    const match = String(dive.startTime || "").trim().match(/^(\d{1,2}):(\d{2})/);
    if (!match) return date;
    return date + " · " + String(match[1]).padStart(2, "0") + ":" + match[2];
  }

  function seaView(sea) {
    if (sea === "red") return { center: [29.54, 34.93], zoom: 10 };
    if (sea === "mediterranean") return { center: [32.4, 34.85], zoom: 7 };
    return { center: [31.4, 34.8], zoom: 7 };
  }

  return {
    MIN_DATED: MIN_DATED,
    MIN_MONTHS: MIN_MONTHS,
    validCoord: validCoord,
    fieldRecords: fieldRecords,
    hasExampleRows: hasExampleRows,
    markerGroups: markerGroups,
    seasonSummary: seasonSummary,
    whenLabel: whenLabel,
    seaView: seaView,
  };
});
