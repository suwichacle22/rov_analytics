/* Heroes page: review hero id/name against the art files and learned crops. */
const state = { heroes: [], map: {}, files: { ban: [], pick: [] }, crops: { ban: {}, pick: {} }, dirty: false, hover: null };
const $ = (s, el = document) => el.querySelector(s);

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toast.h);
  toast.h = setTimeout(() => (t.hidden = true), 2600);
}

function setDirty(v) {
  state.dirty = v;
  $("#status-save span").textContent = v ? "Unsaved changes" : "Saved";
  $("#status-save").className = "state " + (v ? "warn" : "ok");
}

async function load() {
  const d = await api("/api/heroes");
  Object.assign(state, d);
  render();
  setDirty(false);
}

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function artCell(h, kind) {
  const entry = state.map[h.id] || (state.map[h.id] = { ban: null, pick: null, checked: false });
  const wrap = document.createElement("div");
  wrap.className = "art";
  const file = entry[kind];
  if (file) {
    const img = document.createElement("img");
    img.className = kind;
    img.src = `/api/art/${kind}/${encodeURIComponent(file)}`;
    img.loading = "lazy";
    img.alt = file;
    img.title = file;
    wrap.appendChild(img);
  } else {
    const none = document.createElement("div");
    none.className = "none " + kind;
    none.textContent = "no file";
    wrap.appendChild(none);
  }
  const sel = document.createElement("select");
  sel.innerHTML = `<option value="">— none —</option>` + state.files[kind].map((f) => `<option value="${f}" ${f === file ? "selected" : ""}>${f}</option>`).join("");
  sel.onchange = () => {
    entry[kind] = sel.value || null;
    entry.checked = false;
    setDirty(true);
    render();
  };
  wrap.appendChild(sel);

  const what = kind === "ban" ? "ban icon" : "pick art";
  const up = document.createElement("label");
  up.className = "add";
  up.textContent = "Upload";
  up.title = `Set the ${what} of ${h.name} from any image. It is cut around the middle and resized to fit.`;
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = "image/*";
  inp.hidden = true;
  inp.onchange = () => { if (inp.files[0]) uploadArt(h, kind, inp.files[0]); };
  up.appendChild(inp);
  wrap.appendChild(up);

  // Reading the clipboard from a button needs a secure page, so this only shows on localhost.
  if (navigator.clipboard?.read) {
    const paste = document.createElement("button");
    paste.type = "button";
    paste.className = "add";
    paste.textContent = "Paste";
    paste.title = `Use the image on the clipboard as the ${what} of ${h.name}. Ctrl+V does the same while the pointer is over this image.`;
    paste.onclick = () => pasteArt(h, kind);
    wrap.appendChild(paste);
  }
  // Ctrl+V goes to the cell the pointer is over.
  wrap.onmouseenter = () => { state.hover = { id: h.id, kind }; };
  wrap.onmouseleave = () => { state.hover = null; };

  // An image dropped here becomes the art itself. Anywhere else on the row it is a learned crop.
  wrap.ondragover = (e) => {
    e.preventDefault();
    e.stopPropagation();
    wrap.closest("tr")?.classList.remove("dragover");
    wrap.classList.add("dragover");
  };
  wrap.ondragleave = () => wrap.classList.remove("dragover");
  wrap.ondrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    wrap.classList.remove("dragover");
    const f = [...e.dataTransfer.files].find((x) => x.type.startsWith("image/"));
    if (f) uploadArt(h, kind, f);
  };
  return wrap;
}

async function pasteArt(h, kind) {
  try {
    for (const item of await navigator.clipboard.read()) {
      const type = item.types.find((t) => t.startsWith("image/"));
      if (type) return uploadArt(h, kind, new File([await item.getType(type)], "clipboard.png", { type }));
    }
    toast("There is no image on the clipboard", true);
  } catch (e) {
    toast(e.name === "NotAllowedError" ? "The browser did not allow reading the clipboard. Press Ctrl+V over the image instead." : e.message, true);
  }
}

async function uploadArt(h, kind, file) {
  const what = kind === "ban" ? "ban icon" : "pick art";
  const fd = new FormData();
  fd.append("file", file);
  try {
    const d = await api(`/api/heroes/${encodeURIComponent(h.id)}/art/${kind}`, { method: "POST", body: fd });
    // The server saved the pairing already. Other unsaved edits on the page stay as they are.
    const entry = state.map[h.id];
    entry[kind] = d.file;
    if (d.entry[`${kind}Storage`]) entry[`${kind}Storage`] = d.entry[`${kind}Storage`];
    state.files = d.files;
    render();
    if (d.cloud && !d.cloud.ok) toast(`${h.name}: ${what} saved locally. Convex sync failed: ${d.cloud.error}`, true);
    else toast(`${h.name}: ${what} set${d.cloud ? " and synced to Convex" : ""}`);
  } catch (e) {
    toast(e.message, true);
  }
}

function cropsCell(h) {
  const wrap = document.createElement("div");
  wrap.className = "crops";
  for (const kind of ["ban", "pick"]) {
    const files = (state.crops[kind] || {})[h.id] || [];
    for (const f of files) {
      const c = document.createElement("span");
      c.className = "crop";
      const img = document.createElement("img");
      img.className = kind;
      img.src = `/api/crops/${kind}/${h.id}/${encodeURIComponent(f)}`;
      img.loading = "lazy";
      img.title = f;
      const x = document.createElement("button");
      x.className = "x";
      x.textContent = "×";
      x.title = "Delete this crop";
      x.onclick = async () => {
        await api(`/api/heroes/${h.id}/crops/${kind}/${encodeURIComponent(f)}`, { method: "DELETE" });
        state.crops[kind][h.id] = files.filter((y) => y !== f);
        render();
      };
      c.append(img, x);
      wrap.appendChild(c);
    }
    const add = document.createElement("label");
    add.className = "add";
    add.textContent = `+ ${kind}`;
    add.title = `Upload a broadcast ${kind === "ban" ? "ban icon" : "pick splash"} crop of ${h.name}`;
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = "image/*";
    inp.hidden = true;
    inp.multiple = true;
    inp.onchange = () => uploadCrops(h.id, kind, inp.files);
    add.appendChild(inp);
    wrap.appendChild(add);
    if (kind === "ban") {
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = "·";
      wrap.appendChild(sep);
    }
  }
  return wrap;
}

async function uploadCrops(heroId, kind, files) {
  let n = 0;
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    try {
      await api(`/api/heroes/${heroId}/crops/${kind}`, { method: "POST", body: fd });
      n++;
    } catch (e) {
      toast(e.message, true);
    }
  }
  if (n) {
    toast(`${n} crop${n > 1 ? "s" : ""} added to ${heroId}`);
    const d = await api("/api/heroes");
    state.crops = d.crops;
    render();
  }
}

function render() {
  const filter = $("#filter").value.trim().toLowerCase();
  const onlyUnchecked = $("#only-unchecked").checked;
  const tbody = $("#rows");
  tbody.innerHTML = "";
  let shown = 0, checked = 0, missing = 0;
  for (const h of state.heroes) {
    const entry = state.map[h.id] || (state.map[h.id] = { ban: null, pick: null, checked: false });
    const isMissing = !entry.ban || !entry.pick;
    if (entry.checked) checked++;
    if (isMissing) missing++;
    if (filter && !(h.name.toLowerCase().includes(filter) || h.id.includes(filter))) continue;
    if (onlyUnchecked && entry.checked) continue;
    shown++;
    const tr = document.createElement("tr");
    tr.className = (entry.checked ? "checked" : "") + (isMissing ? " missing" : "");
    tr.dataset.id = h.id;

    const tdBan = document.createElement("td");
    tdBan.appendChild(artCell(h, "ban"));
    const tdPick = document.createElement("td");
    tdPick.appendChild(artCell(h, "pick"));

    const tdId = document.createElement("td");
    tdId.className = "id";
    const idIn = document.createElement("input");
    idIn.value = h.id;
    idIn.onchange = () => {
      const nid = slug(idIn.value);
      if (!nid || (nid !== h.id && state.heroes.some((x) => x.id === nid))) {
        toast("Id must be unique", true);
        idIn.value = h.id;
        return;
      }
      state.map[nid] = state.map[h.id];
      if (nid !== h.id) delete state.map[h.id];
      h.id = nid;
      setDirty(true);
      render();
    };
    tdId.appendChild(idIn);

    const tdName = document.createElement("td");
    tdName.className = "name";
    const nameIn = document.createElement("input");
    nameIn.value = h.name;
    nameIn.onchange = () => { h.name = nameIn.value.trim(); setDirty(true); };
    tdName.appendChild(nameIn);


    const tdCrops = document.createElement("td");
    tdCrops.appendChild(cropsCell(h));

    const tdCheck = document.createElement("td");
    tdCheck.className = "check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!entry.checked;
    const setChecked = (v) => { entry.checked = v; cb.checked = v; setDirty(true); tr.classList.toggle("checked", v); renderStats(); };
    cb.onchange = () => setChecked(cb.checked);
    tdCheck.appendChild(cb);
    // Two taps or clicks on the same row within 400 ms toggle Checked. Phones never send a real
    // dblclick for a double-tap, so this counts click events itself and works everywhere.
    tr.title = "Double-click or double-tap to toggle Checked";
    let lastTap = 0, lastX = 0, lastY = 0;
    tr.addEventListener("click", (e) => {
      // Buttons, dropdowns, the checkbox and the crop controls keep their own behaviour.
      if (e.target.closest("select, button, a, input[type=checkbox], input[type=file], .art .add, .crops .add, .crops .x")) return;
      const now = Date.now();
      const near = Math.abs(e.clientX - lastX) < 40 && Math.abs(e.clientY - lastY) < 40;
      if (now - lastTap < 400 && near) {
        lastTap = 0;
        e.preventDefault();
        window.getSelection()?.removeAllRanges();
        if (e.target.tagName === "INPUT") e.target.blur();
        setChecked(!entry.checked);
        toast(`${h.name}: ${entry.checked ? "checked" : "unchecked"}`);
      } else {
        lastTap = now; lastX = e.clientX; lastY = e.clientY;
      }
    });
    tr.ondblclick = (e) => { if (!e.target.closest("select, button, a, input[type=checkbox]")) e.preventDefault(); };

    const tdDel = document.createElement("td");
    const del = document.createElement("button");
    del.className = "btn small";
    del.textContent = "Remove";
    del.onclick = () => {
      if (!confirm(`Remove ${h.name} from the hero list?`)) return;
      state.heroes = state.heroes.filter((x) => x !== h);
      delete state.map[h.id];
      setDirty(true);
      render();
    };
    tdDel.appendChild(del);

    // Drop an image on the row to add it as a pick crop (or ban crop if it is roughly square).
    tr.ondragover = (e) => { e.preventDefault(); tr.classList.add("dragover"); };
    tr.ondragleave = () => tr.classList.remove("dragover");
    tr.ondrop = async (e) => {
      e.preventDefault();
      tr.classList.remove("dragover");
      const files = [...e.dataTransfer.files].filter((f) => f.type.startsWith("image/"));
      if (!files.length) return;
      const groups = { ban: [], pick: [] };
      for (const f of files) {
        const kind = await guessKind(f);
        groups[kind].push(f);
      }
      if (groups.ban.length) await uploadCrops(h.id, "ban", groups.ban);
      if (groups.pick.length) await uploadCrops(h.id, "pick", groups.pick);
    };

    tr.append(tdBan, tdPick, tdId, tdName, tdCrops, tdCheck, tdDel);
    tbody.appendChild(tr);
  }
  renderStats(shown, checked, missing);
  renderUnused();
}

function guessKind(file) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(img.src); resolve(img.height / img.width > 1.25 ? "pick" : "ban"); };
    img.onerror = () => resolve("pick");
    img.src = URL.createObjectURL(file);
  });
}

function renderStats(shown, checked, missing) {
  if (shown === undefined) {
    checked = state.heroes.filter((h) => state.map[h.id]?.checked).length;
    missing = state.heroes.filter((h) => !state.map[h.id]?.ban || !state.map[h.id]?.pick).length;
    shown = $("#rows").children.length;
  }
  const crops = ["ban", "pick"].reduce((n, k) => n + Object.values(state.crops[k] || {}).reduce((m, a) => m + a.length, 0), 0);
  $("#stats").innerHTML = `<span><b>${state.heroes.length}</b> heroes</span><span><b>${checked}</b> checked</span><span><b>${missing}</b> missing art</span><span><b>${crops}</b> learned crops</span><span>showing <b>${shown}</b></span>`;
}

function renderUnused() {
  const used = { ban: new Set(), pick: new Set() };
  for (const e of Object.values(state.map)) { if (e.ban) used.ban.add(e.ban); if (e.pick) used.pick.add(e.pick); }
  const box = $("#unused");
  box.innerHTML = "";
  let n = 0;
  for (const kind of ["ban", "pick"]) {
    for (const f of state.files[kind]) {
      if (used[kind].has(f)) continue;
      n++;
      const u = document.createElement("div");
      u.className = "u";
      u.innerHTML = `<img src="/api/art/${kind}/${encodeURIComponent(f)}" loading="lazy"><span>${kind} · ${f}</span>`;
      box.appendChild(u);
    }
  }
  if (!n) box.innerHTML = `<div class="u empty">Every art file is assigned.</div>`;
}

async function save() {
  try {
    const d = await api("/api/heroes", { method: "PUT", body: JSON.stringify({ heroes: state.heroes, map: state.map }) });
    Object.assign(state, d);
    render();
    setDirty(false);
    if (d.cloud && d.cloud.ok) toast(`Heroes saved and synced to Convex (${d.cloud.count} heroes${d.cloud.uploaded ? `, ${d.cloud.uploaded} art files uploaded` : ""})`);
    else if (d.cloud) toast(`Heroes saved locally. Convex sync failed: ${d.cloud.error}`, true);
    else toast("Heroes saved");
  } catch (e) {
    toast(e.message, true);
  }
}

// Ctrl+V with an image on the clipboard sets the art under the pointer. Pasted text is left alone.
document.addEventListener("paste", (e) => {
  const file = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
  if (!file) return;
  e.preventDefault();
  const h = state.hover && state.heroes.find((x) => x.id === state.hover.id);
  if (!h) return toast("Move the pointer over a ban icon or a pick art, then paste", true);
  uploadArt(h, state.hover.kind, file);
});

$("#btn-save").onclick = save;
$("#filter").oninput = render;
$("#only-unchecked").onchange = render;
$("#btn-add").onclick = () => {
  const name = prompt("Hero name");
  if (!name) return;
  const id = slug(name);
  if (state.heroes.some((h) => h.id === id)) { toast("Hero already exists", true); return; }
  state.heroes.push({ id, name: name.trim() });
  state.heroes.sort((a, b) => a.name.localeCompare(b.name));
  state.map[id] = { ban: null, pick: null, checked: false };
  setDirty(true);
  $("#filter").value = name;
  render();
};
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
});
window.addEventListener("beforeunload", (e) => { if (state.dirty) { e.preventDefault(); e.returnValue = ""; } });

load().catch((e) => toast(e.message, true));
