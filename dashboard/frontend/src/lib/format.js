// Every number on screen goes through here: null, undefined, NaN or a string becomes "N/A".
export const NA = "N/A";

export function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

export function fmt(v, digits = 2, unit = "") {
  if (!isNum(v)) return NA;
  return unit ? `${v.toFixed(digits)} ${unit}` : v.toFixed(digits);
}

export function fmtTime(iso) {
  if (!iso) return NA;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? NA : d.toLocaleTimeString();
}

export function fmtAge(ms) {
  if (!isNum(ms)) return NA;
  if (ms < 1000) return "just now";
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(0)} s ago` : `${(s / 60).toFixed(1)} min ago`;
}

export function onOff(v) {
  return v === true ? "ON" : v === false ? "OFF" : NA;
}
