/* Inline icon set (Lucide-style: 24×24 grid, 1.5px round strokes).
   FR-052: status is always icon/dot + label — never color alone. */

const P = {
  overview: '<rect x="3" y="3" width="7.5" height="9" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="5" rx="1.5"/><rect x="13.5" y="11" width="7.5" height="10" rx="1.5"/><rect x="3" y="15" width="7.5" height="6" rx="1.5"/>',
  profiles: '<path d="M4 7a2 2 0 0 1 2-2h4l2 2.5h6a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/>',
  devices: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  acl: '<path d="M12 3 5 6v5c0 4.4 3 7.7 7 9 4-1.3 7-4.6 7-9V6Z"/><path d="m9.2 12 2 2 3.6-4"/>',
  node: '<rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M8 7.5h.01M8 16.5h.01"/>',
  exposures: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.8 2.6 4 5.6 4 9s-1.2 6.4-4 9c-2.8-2.6-4-5.6-4-9s1.2-6.4 4-9Z"/>',
  services: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  logs: '<path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
  audit: '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M12 8v4l3 2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.14-1.4l2-1.55-2-3.46-2.37.95a7 7 0 0 0-2.42-1.4L13.7 2.6h-3.4l-.37 2.54a7 7 0 0 0-2.42 1.4l-2.37-.95-2 3.46 2 1.55A7 7 0 0 0 5 12c0 .48.05.94.14 1.4l-2 1.55 2 3.46 2.37-.95a7 7 0 0 0 2.42 1.4l.37 2.54h3.4l.37-2.54a7 7 0 0 0 2.42-1.4l2.37.95 2-3.46-2-1.55c.09-.46.14-.92.14-1.4Z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 4 2.8 20h18.4Z"/><path d="M12 10v4M12 17.2h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.8h.01"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  download: '<path d="M12 4v11M7.5 11 12 15.5 16.5 11"/><path d="M4 19h16"/>',
  qr: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2.5v2.5H14zM20.5 14v.01M14 20.5v.01M17.5 17.5H20V20h-2.5zM20 20h.01"/>',
  link: '<path d="M10.5 13.5a4 4 0 0 0 5.7 0l3-3a4 4 0 1 0-5.7-5.7l-1.4 1.4"/><path d="M13.5 10.5a4 4 0 0 0-5.7 0l-3 3a4 4 0 1 0 5.7 5.7l1.4-1.4"/>',
  pencil: '<path d="M4 20h4L20 8l-4-4L4 16Z"/><path d="m13.5 6.5 4 4"/>',
  upload: '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6.5 7l1 13h9l1-13"/><path d="M10 11v5M14 11v5"/>',
  power: '<path d="M12 3v8"/><path d="M6.2 6.2a8 8 0 1 0 11.6 0"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 6.3"/><path d="M20 5v6h-6"/>',
  play: '<path d="M7 4.5v15l12-7.5Z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  wifioff: '<path d="m2 2 20 20"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M5 12.5a10 10 0 0 1 3-2M15.5 10.4a10 10 0 0 1 3.5 2.1"/><path d="M2 8.8A15 15 0 0 1 7 5.9M17.5 6.1a15 15 0 0 1 4.5 2.7"/><path d="M12 20h.01"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M19 14v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>',
  sun: '<circle cx="12" cy="12" r="4.5"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  logout: '<path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h3"/><path d="m15 8 4 4-4 4M19 12H9"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  key: '<circle cx="8" cy="15" r="4.5"/><path d="m11.5 11.5 8-8M17 6l2.5 2.5M14.5 8.5 17 11"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.8 2.6 4 5.6 4 9s-1.2 6.4-4 9c-2.8-2.6-4-5.6-4-9s1.2-6.4 4-9Z"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  lan: '<rect x="3" y="14" width="8" height="7" rx="1.5"/><rect x="13" y="3" width="8" height="7" rx="1.5"/><path d="M7 14v-3h10v3M17 10V7"/>',
  os_linux: '<path d="M12 3c-2 0-3 1.6-3 3.6 0 1.5-.5 2.5-1.4 3.9C6.5 12.2 6 13.6 6 15c0 3 2.7 5.5 6 5.5s6-2.5 6-5.5c0-1.4-.5-2.8-1.6-4.5C15.5 9.1 15 8.1 15 6.6c0-2-1-3.6-3-3.6Z"/><path d="M10.4 8.2h.01M13.6 8.2h.01"/>',
  os_apple: '<path d="M15.5 7.5c-1.8 0-2.3 1-3.5 1s-1.9-1-3.5-1C6.6 7.5 5 9 5 11.5c0 3.6 2.6 8 4.6 8 .9 0 1.4-.7 2.4-.7s1.4.7 2.4.7c2 0 4.6-4.4 4.6-8 0-2.5-1.6-4-3.5-4Z"/><path d="M12 7c0-2 1.5-3.5 3.5-3.5C15.5 5.5 14 7 12 7Z"/>',
  os_windows: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
  os_android: '<path d="M5 10a7 7 0 0 1 14 0v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2Z"/><path d="M8 7 6.5 4.5M16 7l1.5-2.5M9.5 13h.01M14.5 13h.01"/>',
  os_ios: '<rect x="6" y="3" width="12" height="18" rx="2.5"/><path d="M10.5 18h3"/>',
};

export function icon(name, size = 16) {
  const body = P[name] || P.info;
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

export function osIcon(os) {
  const o = (os || "").toLowerCase();
  if (o.includes("mac") || o.includes("darwin")) return "os_apple";
  if (o.includes("ios")) return "os_ios";
  if (o.includes("android")) return "os_android";
  if (o.includes("windows")) return "os_windows";
  if (o.includes("linux")) return "os_linux";
  return "devices";
}

export const NAMES = Object.keys(P);
