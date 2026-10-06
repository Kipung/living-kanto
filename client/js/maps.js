// maps.js — load original map PNGs + JSON metadata, draw with pan/zoom.
// No generated or redrawn art: only original PNGs served at /content/maps/.
(function () {
  "use strict";

  const KNOWN_MAPS = [
    "PalletTown", "Route1", "ViridianCity",
    "PalletTown_PlayersHouse_1F", "PalletTown_PlayersHouse_2F",
    "PalletTown_ProfessorOaksLab", "PalletTown_RivalsHouse",
    "ViridianCity_Mart", "ViridianCity_PokemonCenter_1F"
  ];

  const state = {
    name: null,
    json: null,
    img: null,
    cell: 16,
    view: { x: 0, y: 0, zoom: 1 },
    onReady: null
  };

  let generation = 0;
  async function loadMap(name) {
    const gen = ++generation;
    const {cachedJSON,cachedImage}=await import('/client/js/artwork-cache.mjs');
    const [jsonRes, img] = await Promise.all([
      cachedJSON('/content/maps/' + encodeURIComponent(name) + '.json'),
      cachedImage('/content/maps/' + encodeURIComponent(name) + '.png')
    ]);
    if (gen !== generation) return;
    const w = jsonRes.width || 0, h = jsonRes.height || 0;
    let cell = 16;
    if (w > 0 && h > 0) {
      const cw = img.naturalWidth / w, ch = img.naturalHeight / h;
      if (cw === Math.floor(cw) && ch === Math.floor(ch)) cell = Math.max(cw, ch);
    }
    state.name = name;
    state.json = jsonRes;
    state.img = img;
    state.cell = cell;
    state.view = { x: 0, y: 0, zoom: 1 };
    if (state.onReady) state.onReady();
  }

  function draw(canvas) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!state.img) {
      ctx.fillStyle = "#888";
      ctx.font = "14px system-ui";
      ctx.fillText("no map loaded", 16, 24);
      return;
    }
    const v = state.view;
    ctx.imageSmoothingEnabled = false;
    ctx.setTransform(v.zoom, 0, 0, v.zoom, v.x, v.y);
    ctx.drawImage(state.img, 0, 0);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  function screenToCell(px, py) {
    const v = state.view;
    const mx = (px - v.x) / v.zoom, my = (py - v.y) / v.zoom;
    return { x: Math.floor(mx / state.cell), y: Math.floor(my / state.cell) };
  }

  function cellAt(cx, cy) {
    const cells = state.json && state.json.cells;
    if (!cells) return null;
    for (const c of cells) if (c.x === cx && c.y === cy) return c;
    return null;
  }

  function pan(dx, dy) { state.view.x += dx; state.view.y += dy; }
  function zoomAt(px, py, factor) {
    const v = state.view;
    const nz = Math.min(8, Math.max(0.25, v.zoom * factor));
    const k = nz / v.zoom;
    v.x = px - (px - v.x) * k;
    v.y = py - (py - v.y) * k;
    v.zoom = nz;
  }

  window.Maps = {
    KNOWN_MAPS, loadMap, draw, screenToCell, cellAt, pan, zoomAt,
    get state() { return state; },
    set onReady(fn) { state.onReady = fn; }
  };
})();
