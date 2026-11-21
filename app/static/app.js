// PlagCheck — frontend bez kroku budowania (ES modules, CSP-friendly: bez innerHTML z danymi).

const view = document.getElementById("view");
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* tryb prywatny */ } },
};

// Anonimowy identyfikator przeglądarki — historia sprawdzeń bez kont użytkowników.
function ownerToken() {
  let t = store.get("plagcheck.owner");
  if (!t || !/^[A-Za-z0-9_-]{16,64}$/.test(t)) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    t = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    store.set("plagcheck.owner", t);
  }
  return t;
}

// ------------------------------------------------------------------ DOM helper
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
// replaceChildren zamienia null na tekst "null" — filtrujemy puste dzieci.
const fill = (el, ...kids) => el.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
const shareText = (s) => (s.percent === 0 && s.matched_words > 0 ? "pokrywa się z innymi źródłami" : `${s.percent}%`);
// 72 → „3 dniach”, 8760 → „365 dniach”, 12 → „12 godzinach”
const ttlText = (h) => (h % 24 === 0 ? (h === 24 ? "1 dniu" : `${h / 24} dniach`) : `${h} godzinach`);
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" }) : "");
const SOURCE_NAMES = { brave: "Brave Search", serper: "Google (Serper)", serpapi: "Google (SerpAPI)", wikipedia: "Wikipedia", openalex: "OpenAlex (publikacje naukowe)" };
const KIND_LABELS = { web: "internet", wikipedia: "wikipedia", scholar: "publikacja naukowa", local: "baza lokalna" };
const level = (p) => (p === null || p === undefined ? "" : p >= 40 ? "high" : p >= 15 ? "mid" : "low");
const aiLevel = (p) => (p === null || p === undefined ? "" : p >= 65 ? "high" : p >= 35 ? "mid" : "low");

// ------------------------------------------------------------------------ API
let health = null;

async function api(path, opts = {}) {
  const headers = { "X-Owner-Token": ownerToken(), ...(opts.headers || {}) };
  const key = store.get("plagcheck.access");
  if (key) headers["X-Access-Key"] = key;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    await askAccessKey();
    return api(path, opts);
  }
  if (!res.ok) {
    let msg = `Błąd ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* brak JSON */ }
    throw new Error(msg);
  }
  return opts.raw ? res : res.json();
}

function askAccessKey() {
  return new Promise((resolve) => {
    const dlg = document.getElementById("access-dialog");
    const input = document.getElementById("access-input");
    dlg.addEventListener("close", () => { store.set("plagcheck.access", input.value.trim()); resolve(); }, { once: true });
    dlg.showModal();
  });
}

// --------------------------------------------------------------------- router
let pollTimer = null;
function route() {
  clearTimeout(pollTimer);
  const hash = location.hash || "#/";
  const [, page, id] = hash.split("/");
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.remove("active"));
  const nav = page === "history" || page === "job" ? "history" : page === "refs" ? "refs" : page === "settings" ? "settings" : "new";
  document.querySelector(`[data-nav="${nav}"]`)?.classList.add("active");
  view.replaceChildren();
  if (page === "job" && id) renderJob(id);
  else if (page === "history") renderHistory();
  else if (page === "refs") renderRefs();
  else if (page === "settings" && health?.mobile) renderSettings();
  else renderNew();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------ nowe sprawdzenie
const OPTIONS = [
  ["web", "Internet", "Wyszukiwanie fraz kontrolnych w sieci i porównanie ze stronami źródłowymi.", true],
  ["local", "Baza lokalna", "Porównanie z plikami dodanymi w zakładce „Baza lokalna”.", true],
  ["ai", "Detekcja treści AI", "Cechy stylometryczne i frazy typowe dla modeli językowych.", true],
  ["exclude_quotes", "Wyklucz cytaty", "Tekst w cudzysłowie „…” nie liczy się do podobieństwa.", true],
  ["exclude_bibliography", "Wyklucz bibliografię i spis treści", "Pomija sekcję „Bibliografia/Literatura” oraz opisy z ISBN/DOI.", true],
  ["exclude_legal", "Wyklucz odwołania do aktów prawnych", "Zdania z „Dz.U.”, „art. …” nie liczą się do podobieństwa.", false],
];

function renderNew() {
  let file = null;
  const fileInput = h("input", { type: "file", accept: ".docx,.pdf,.txt,.odt", class: "hidden", id: "file" });
  const chip = h("div", { class: "file-chip hidden" });
  const textArea = h("textarea", { placeholder: "…albo wklej tutaj tekst (min. 20 słów)", "aria-label": "Tekst do sprawdzenia" });
  const err = h("div", { class: "alert error hidden", role: "alert" });
  const submit = h("button", { class: "btn primary", type: "submit" }, "Sprawdź dokument");

  const setFile = (f) => {
    file = f;
    chip.replaceChildren(f ? `📄 ${f.name} · ${(f.size / 1024).toFixed(0)} KB` : "");
    chip.classList.toggle("hidden", !f);
  };
  fileInput.addEventListener("change", () => setFile(fileInput.files[0] || null));
  const drop = h("div", {
    class: "dropzone", tabindex: "0", role: "button", "aria-label": "Wybierz plik do sprawdzenia",
    onclick: () => fileInput.click(),
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } },
    ondragover: (e) => { e.preventDefault(); drop.classList.add("drag"); },
    ondragleave: () => drop.classList.remove("drag"),
    ondrop: (e) => { e.preventDefault(); drop.classList.remove("drag"); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); },
  },
    h("div", { class: "big" }, "Przeciągnij plik lub kliknij, aby wybrać"),
    h("div", { class: "muted small" }, `DOCX, PDF, ODT, TXT · do ${health?.max_upload_mb ?? 15} MB`),
  );

  const optionInputs = {};
  const saved = JSON.parse(store.get("plagcheck.options") || "{}");
  const opts = OPTIONS.map(([key, label, desc, def]) => {
    const input = h("input", { type: "checkbox", id: `opt-${key}` });
    input.checked = key in saved ? !!saved[key] : def;
    optionInputs[key] = input;
    return h("label", { class: "option", for: `opt-${key}` }, input, h("div", {}, h("b", {}, label), h("span", {}, desc)));
  });

  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      err.classList.add("hidden");
      const options = Object.fromEntries(Object.entries(optionInputs).map(([k, el]) => [k, el.checked]));
      store.set("plagcheck.options", JSON.stringify(options));
      const fd = new FormData();
      if (file) fd.append("file", file);
      else if (textArea.value.trim()) fd.append("text", textArea.value);
      else { err.textContent = "Wybierz plik albo wklej tekst."; err.classList.remove("hidden"); return; }
      fd.append("options", JSON.stringify(options));
      submit.disabled = true; submit.textContent = "Wysyłanie…";
      try {
        const job = await api("/api/check", { method: "POST", body: fd });
        location.hash = `#/job/${job.id}`;
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden");
        submit.disabled = false; submit.textContent = "Sprawdź dokument";
      }
    },
  },
    h("div", { class: "grid-2" },
      h("section", { class: "card" },
        h("h2", {}, "Dokument"),
        drop, fileInput, chip,
        h("div", { class: "divider" }, "lub"),
        textArea,
      ),
      h("section", { class: "card" },
        h("h2", {}, "Zakres analizy"),
        h("div", { class: "options" }, opts),
        err,
        h("div", { class: "row end", style: { marginTop: "16px" } }, submit),
      ),
    ),
  );

  const sources = (health?.search_sources || []).map((n) => SOURCE_NAMES[n] || n);
  const providerInfo = sources.length
    ? `Źródła: ${sources.join(", ")}${health.profile === "full" ? " · wykrywanie parafraz synonimicznych włączone" : ""}.`
    : "Wyszukiwanie w sieci jest wyłączone — raport zawiera frazy kontrolne z linkami do ręcznego sprawdzenia.";
  view.append(
    h("h1", {}, "Sprawdź pracę przed oddaniem"),
    h("p", { class: "muted" }, "Wykrywa jawne zapożyczenia, bliskie parafrazy i cechy typowe dla tekstów generowanych przez AI. ", providerInfo),
    form,
  );
}

// ------------------------------------------------------------- zadanie/raport
async function renderJob(id) {
  const box = h("section", { class: "card" }, h("p", { class: "muted" }, "Wczytywanie…"));
  view.append(box);
  let job;
  try { job = await api(`/api/jobs/${id}`); } catch (e) {
    box.replaceChildren(h("div", { class: "alert error" }, e.message), h("p", {}, h("a", { href: "#/history" }, "← Historia")));
    return;
  }
  if (job.status === "pending" || job.status === "running") {
    const bar = h("div", { style: { width: `${job.progress}%` } });
    box.replaceChildren(
      h("h1", {}, job.filename),
      h("div", { class: "progress", role: "progressbar", "aria-valuenow": job.progress, "aria-valuemin": 0, "aria-valuemax": 100 }, bar),
      h("p", { class: "muted" }, `${job.stage} · ${job.progress}%`),
      h("p", { class: "muted small" }, "Analiza dokumentu 20–40 stron trwa zwykle 1–5 minut. Możesz zamknąć tę kartę — wynik znajdziesz w historii."),
    );
    pollTimer = setTimeout(() => { if (location.hash === `#/job/${id}`) { view.replaceChildren(); renderJob(id); } }, 1500);
    return;
  }
  if (job.status === "error") {
    box.replaceChildren(h("h1", {}, job.filename), h("div", { class: "alert error" }, job.error || "Analiza nie powiodła się."),
      h("p", {}, h("a", { href: "#/" }, "Spróbuj ponownie")));
    return;
  }
  let report;
  try { report = await api(`/api/jobs/${id}/report`); } catch (e) {
    box.replaceChildren(h("div", { class: "alert error" }, e.message));
    return;
  }
  box.remove();
  renderReport(job, report);
}

function kpi(label, value, sub, lvl) {
  return h("div", { class: `kpi ${lvl ? "level-" + lvl : ""}` }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), h("div", { class: "sub" }, sub));
}

function renderReport(job, r) {
  const ai = r.ai || {};
  const sim = r.similarity;
  const sourcesById = Object.fromEntries(r.sources.map((s) => [s.id, s]));
  const header = h("div", { class: "row" },
    h("div", {}, h("h1", {}, r.filename), h("div", { class: "muted small" }, `Sprawdzono ${fmtDate(job.created_at)} · raport wygaśnie ${fmtDate(job.expires_at)}`)),
    h("div", { class: "spacer" }),
    h("div", { class: "row no-print" },
      h("button", { class: "btn sm", onclick: () => exportHtml(job) }, "Eksport HTML"),
      h("button", { class: "btn sm", onclick: () => (window.AndroidBridge ? window.AndroidBridge.printPage(r.filename) : window.print()) }, "Drukuj / PDF"),
      h("button", { class: "btn sm danger", onclick: async () => {
        if (!confirm("Usunąć ten raport?")) return;
        await api(`/api/jobs/${job.id}`, { method: "DELETE" });
        location.hash = "#/history";
      } }, "Usuń"),
    ),
  );
  const kpis = h("div", { class: "kpis" },
    kpi("Podobieństwo", `${sim.percent}%`, `dokładne ${sim.exact_percent}% · parafrazy ${sim.paraphrase_percent}%`, level(sim.percent)),
    kpi("Prawdopodobieństwo AI", ai.percent == null ? "—" : `${ai.percent}%`, ai.label ? `${ai.label} · pewność: ${ai.confidence}` : "wyłączone", aiLevel(ai.percent)),
    kpi("Źródła", String(r.sources.length), r.search?.providers?.length ? `${r.search.queries_sent + r.search.cache_hits} zapytań${r.search.cache_hits ? ` (${r.search.cache_hits} z pamięci)` : ""} · ${r.search.pages_fetched} stron` : "bez wyszukiwania w sieci"),
    kpi("Słowa", String(r.stats.words), `wyłączone z analizy: ${r.stats.excluded_words}`),
  );
  const warnings = (r.warnings || []).map((w) => h("div", { class: "alert warn" }, w));

  const tabs = [
    ["text", "Tekst"],
    ["sources", `Źródła (${r.sources.length})`],
    ["ai", "Detekcja AI"],
    ["phrases", `Frazy kontrolne (${r.phrases.length})`],
  ];
  const panel = h("div");
  const tabBar = h("div", { class: "tabs", role: "tablist" });
  const show = (key) => {
    tabBar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === key)));
    panel.replaceChildren(
      key === "text" ? textPanel(r, sourcesById)
        : key === "sources" ? sourcesPanel(r)
          : key === "ai" ? aiPanel(ai) : phrasesPanel(r),
    );
  };
  tabs.forEach(([key, label]) => tabBar.append(h("button", { role: "tab", dataset: { tab: key }, onclick: () => show(key) }, label)));
  view.append(header, kpis, ...warnings, tabBar, panel);
  show("text");
}

function textPanel(r, sourcesById) {
  let mode = "sim";
  const chunkPct = Object.fromEntries(((r.ai || {}).chunks || []).map((c) => [c.index, c.percent]));
  const docEl = h("div", { class: "doc-text", tabindex: "0", "aria-label": "Tekst dokumentu z podświetleniami" });
  const detail = h("div", { class: "detail-pop hidden", role: "status" });
  const legend = h("div", { class: "legend" });

  const draw = () => {
    detail.classList.add("hidden");
    legend.replaceChildren(...(mode === "sim"
      ? [
        h("span", {}, h("span", { class: "swatch", style: { background: "var(--exact)" } }), "dopasowanie dokładne / bliskie"),
        h("span", {}, h("span", { class: "swatch", style: { background: "var(--para)" } }), "parafraza"),
        h("span", {}, h("span", { class: "swatch", style: { background: "var(--surface-2)" } }), "przekreślone = wyłączone (cytat, bibliografia)"),
      ]
      : [h("span", {}, "Kolor fragmentu = szacowane prawdopodobieństwo AI (im cieplejszy, tym wyższe). Kliknij fragment, by zobaczyć uzasadnienie.")]));
    const frag = document.createDocumentFragment();
    const segs = r.segments;
    segs.forEach((seg, i) => {
      if (mode === "ai") {
        const p = seg.chunk != null ? chunkPct[seg.chunk] : null;
        if (p == null) { frag.append(seg.text); return; }
        const alpha = Math.max(0, (p - 20) / 80) * 0.45;
        frag.append(h("span", {
          class: "ai", style: { background: `rgba(217, 71, 58, ${alpha.toFixed(2)})` }, dataset: { chunk: seg.chunk },
          onclick: () => showChunk(seg.chunk),
        }, seg.text));
        return;
      }
      if (seg.type === "exact" || seg.type === "paraphrase") {
        const src = sourcesById[seg.source];
        frag.append(h("mark", {
          class: seg.type, dataset: { source: seg.source ?? "" },
          title: src ? `[${src.id}] ${src.title}` : "",
          onclick: () => showSource(seg.source, seg.type),
        }, seg.text));
        const next = segs[i + 1];
        if (src && (!next || next.source !== seg.source || next.type !== seg.type)) frag.append(h("sup", {}, `[${src.id}]`));
      } else if (seg.type === "excluded") {
        frag.append(h("span", { class: "excluded", title: `Wyłączone: ${seg.reason || ""}` }, seg.text));
      } else {
        frag.append(seg.text);
      }
    });
    docEl.replaceChildren(frag);
  };

  const showSource = (id, type) => {
    const src = sourcesById[id];
    docEl.querySelectorAll("mark.focus").forEach((m) => m.classList.remove("focus"));
    docEl.querySelectorAll(`mark[data-source="${id}"]`).forEach((m) => m.classList.add("focus"));
    if (!src) return;
    const para = (r.paraphrases || []).filter((p) => p.source === id).slice(0, 1)[0];
    fill(detail, 
      h("b", {}, `[${src.id}] ${src.title}`), " ",
      h("span", { class: "badge" }, type === "paraphrase" ? "parafraza" : "dopasowanie"), h("br"),
      src.url ? h("a", { href: src.url, target: "_blank", rel: "noopener noreferrer" }, src.url) : h("span", { class: "muted" }, "Plik z bazy lokalnej"),
      h("div", { class: "muted small" }, `Udział: ${shareText(src)} · wspólne słowa: ${src.matched_words} · parafrazy: ${src.paraphrases}`),
      para && type === "paraphrase" ? h("div", { class: "small", style: { marginTop: "6px" } }, "Fragment źródła: „", para.source_excerpt, "”") : null,
    );
    detail.classList.remove("hidden");
  };
  const showChunk = (idx) => {
    const c = (r.ai.chunks || []).find((x) => x.index === idx);
    if (!c) return;
    fill(detail, 
      h("b", {}, `Fragment ${idx + 1}: ${c.percent}% (${c.label})`),
      ...c.reasons.map((x) => h("div", { class: "small" }, `${x.direction === "ai" ? "▲" : "▼"} ${x.label}: ${x.description}`)),
      c.markers.length ? h("div", { class: "small muted" }, "Frazy-markery: ", c.markers.join(", ")) : null,
    );
    detail.classList.remove("hidden");
  };

  const modeSel = h("div", { class: "row", style: { marginBottom: "10px" } },
    h("span", { class: "muted small" }, "Widok:"),
    h("button", { class: "btn sm", "aria-pressed": "true", onclick: (e) => { mode = "sim"; setPressed(e.target); draw(); } }, "Podobieństwo"),
    r.ai && r.ai.chunks && r.ai.chunks.length
      ? h("button", { class: "btn sm", "aria-pressed": "false", onclick: (e) => { mode = "ai"; setPressed(e.target); draw(); } }, "Detekcja AI")
      : null,
  );
  const setPressed = (btn) => modeSel.querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b === btn));
    b.classList.toggle("primary", b === btn);
  });
  modeSel.querySelector("button").classList.add("primary");
  draw();
  return h("div", {}, modeSel, legend, docEl, detail);
}

function sourcesPanel(r) {
  if (!r.sources.length) {
    return h("div", { class: "card empty" }, "Nie znaleziono pasujących źródeł.",
      h("div", { class: "small" }, "Brak dopasowań nie gwarantuje braku plagiatu — wyszukiwanie obejmuje wybrane frazy i publiczne źródła."));
  }
  const list = h("div", { class: "source-list" }, r.sources.map((s) => h("div", { class: "source" },
    h("div", { class: "num" }, String(s.id)),
    h("div", { style: { minWidth: "0" } },
      h("div", { class: "title" }, s.title, " ", h("span", { class: "badge" }, KIND_LABELS[s.kind] || s.kind)),
      s.url ? h("a", { class: "url", href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.url) : h("div", { class: "url" }, "plik referencyjny"),
      h("div", { class: "small muted" }, `wspólne słowa: ${s.matched_words} · zdania-parafrazy: ${s.paraphrases}`),
    ),
    h("div", { class: s.percent === 0 && s.matched_words > 0 ? "pct small muted" : "pct", title: "Udział słów przypisanych tylko do tego źródła" }, shareText(s)),
  )));
  const paras = (r.paraphrases || []).slice(0, 30).map((p) => h("div", { class: "reason" },
    h("div", { class: "small muted" }, `Źródło [${p.source}] · podobieństwo ${(p.score * 100).toFixed(0)}% · ${p.method === "semantic" ? "znaczeniowe (synonimy)" : "leksykalne"}`),
    h("div", {}, "Twój tekst: „", p.sentence, "”"),
    h("div", { class: "muted" }, "Źródło: „", p.source_excerpt, "”"),
  ));
  return h("div", {}, list, paras.length ? h("section", { class: "card", style: { marginTop: "16px" } }, h("h3", {}, "Wykryte parafrazy"), paras) : null);
}

function aiPanel(ai) {
  if (!ai || ai.percent == null) {
    return h("div", { class: "card empty" }, ai ? `Za mało tekstu do oceny (${ai.words} słów, wymagane min. 120).` : "Detekcja AI była wyłączona.");
  }
  const meter = (p) => h("div", { class: "meter" }, h("div", { style: { width: `${p}%`, background: p >= 65 ? "var(--exact-strong)" : p >= 35 ? "var(--para-strong)" : "var(--ok)" } }));
  return h("div", { class: "grid-2" },
    h("section", { class: "card" },
      h("h2", {}, `Wynik: ${ai.percent}% — ${ai.label}`),
      meter(ai.percent),
      h("p", { class: "muted small" }, `Pewność oceny: ${ai.confidence} (${ai.words} słów). Wynik heurystyczny — detektory AI często mylą się przy tekstach technicznych, krótkich i redagowanych. Nie traktuj go jako dowodu.`),
      h("h3", {}, "Najważniejsze sygnały"),
      ai.reasons.length ? ai.reasons.map((x) => h("div", { class: "reason" },
        h("b", {}, `${x.direction === "ai" ? "▲ wskazuje na AI" : "▼ wskazuje na człowieka"} · ${x.label}`),
        h("div", { class: "small muted" }, x.description))) : h("p", { class: "muted" }, "Brak wyraźnych sygnałów."),
      ai.markers.length ? h("div", {}, h("h3", { style: { marginTop: "12px" } }, "Wykryte frazy-markery"), ai.markers.map((m) => h("span", { class: "tag" }, m))) : null,
    ),
    h("section", { class: "card" },
      h("h2", {}, "Fragmenty"),
      ai.chunks.map((c) => h("div", { class: "chunk" },
        h("div", { class: "pct" }, `${c.percent}%`),
        h("div", {}, meter(c.percent), h("div", { class: "small", style: { marginTop: "6px" } }, c.excerpt, "…"),
          h("div", { class: "small muted" }, c.reasons.map((x) => x.label).join(" · "))),
      )),
    ),
  );
}

function phrasesPanel(r) {
  if (!r.phrases.length) return h("div", { class: "card empty" }, "Brak fraz kontrolnych (tekst zbyt krótki).");
  return h("section", { class: "card" },
    h("p", { class: "muted small" }, "Frazy wybrane do wyszukiwania. Kliknij, aby sprawdzić ręcznie w Google (wyszukiwanie dokładne w cudzysłowie). ✔ = fraza odnaleziona w źródle."),
    h("ol", { class: "phrase-list" }, r.phrases.map((p) => h("li", {},
      h("a", { href: p.google_url, target: "_blank", rel: "noopener noreferrer" }, p.text), p.found ? " ✔" : ""))),
  );
}

async function exportHtml(job) {
  const res = await api(`/api/jobs/${job.id}/export.html`, { raw: true });
  if (window.AndroidBridge) {  // WebView nie obsługuje pobierania blob: — zapis przez Androida
    const name = `raport_${job.filename.replace(/\.[^.]+$/, "")}.html`;
    window.AndroidBridge.toast(window.AndroidBridge.saveFile(name, "text/html", await res.text()));
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: `raport_${job.filename.replace(/\.[^.]+$/, "")}.html` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// --------------------------------------------------------------------- historia
async function renderHistory() {
  const card = h("section", { class: "card" }, h("p", { class: "muted" }, "Wczytywanie…"));
  view.append(h("h1", {}, "Historia sprawdzeń"), h("p", { class: "muted" }, `Historia jest powiązana z tą przeglądarką. Raporty są usuwane automatycznie po ${ttlText(health?.report_ttl_hours ?? 72)}.`), card);
  try {
    const { jobs } = await api("/api/jobs");
    if (!jobs.length) {
      card.replaceChildren(h("div", { class: "empty" }, "Brak sprawdzeń. ", h("a", { href: "#/" }, "Sprawdź pierwszy dokument")));
      return;
    }
    card.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["Dokument", "Status", "Podobieństwo", "AI", "Data", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, jobs.map((j) => h("tr", { class: "clickable", onclick: () => { location.hash = `#/job/${j.id}`; } },
        h("td", {}, h("b", {}, j.filename)),
        h("td", {}, h("span", { class: `badge ${j.status}` }, { pending: "w kolejce", running: `${j.progress}%`, done: "gotowe", error: "błąd" }[j.status])),
        h("td", {}, j.summary ? `${j.summary.similarity}%` : "—"),
        h("td", {}, j.summary && j.summary.ai != null ? `${j.summary.ai}%` : "—"),
        h("td", { class: "muted small" }, fmtDate(j.created_at)),
        h("td", {}, h("button", { class: "btn sm danger", onclick: async (e) => {
          e.stopPropagation();
          if (!confirm(`Usunąć „${j.filename}”?`)) return;
          await api(`/api/jobs/${j.id}`, { method: "DELETE" });
          route();
        } }, "Usuń")),
      ))),
    )));
  } catch (e) { card.replaceChildren(h("div", { class: "alert error" }, e.message)); }
}

// ----------------------------------------------------------------- baza lokalna
async function renderRefs() {
  const list = h("section", { class: "card" }, h("p", { class: "muted" }, "Wczytywanie…"));
  const fileInput = h("input", { type: "file", accept: ".docx,.pdf,.txt,.odt", multiple: true });
  const consent = h("input", { type: "checkbox", id: "consent" });
  const err = h("div", { class: "alert error hidden", role: "alert" });
  const btn = h("button", { class: "btn primary", type: "submit" }, "Dodaj do bazy");
  const form = h("form", { class: "card", onsubmit: async (e) => {
    e.preventDefault();
    err.classList.add("hidden");
    if (!fileInput.files.length) { err.textContent = "Wybierz plik(i)."; err.classList.remove("hidden"); return; }
    if (!consent.checked) { err.textContent = "Zaznacz zgodę na przechowywanie plików."; err.classList.remove("hidden"); return; }
    btn.disabled = true;
    try {
      for (const f of fileInput.files) {
        const fd = new FormData(); fd.append("file", f); fd.append("consent", "true");
        await api("/api/references", { method: "POST", body: fd });
      }
      route();
    } catch (ex) { err.textContent = ex.message; err.classList.remove("hidden"); btn.disabled = false; }
  } },
    h("h2", {}, "Dodaj pliki referencyjne"),
    h("p", { class: "muted small" }, "Np. Twoje wcześniejsze prace, notatki, materiały źródłowe. Nowe dokumenty będą z nimi porównywane."),
    fileInput,
    h("label", { class: "option", for: "consent", style: { marginTop: "12px" } }, consent,
      h("div", {}, h("b", {}, "Zgadzam się na przechowywanie tych plików na serwerze"), h("span", {}, "Możesz je usunąć w każdej chwili. Pliki są widoczne tylko w tej przeglądarce."))),
    err, h("div", { class: "row end", style: { marginTop: "12px" } }, btn),
  );
  view.append(h("h1", {}, "Baza lokalna"), h("div", { class: "grid-2" }, list, form));
  try {
    const { references, stats } = await api("/api/references");
    list.replaceChildren(h("h2", {}, `Pliki (${stats.count}) · ${stats.words.toLocaleString("pl-PL")} słów`),
      references.length ? h("div", { class: "table-wrap" }, h("table", { class: "list" }, h("tbody", {}, references.map((ref) => h("tr", {},
        h("td", {}, h("b", {}, ref.name), ref.shared ? h("span", { class: "badge", style: { marginLeft: "6px" } }, "wspólny") : null),
        h("td", { class: "muted small" }, `${ref.words} słów`),
        h("td", {}, ref.shared ? null : h("button", { class: "btn sm danger", onclick: async () => {
          await api(`/api/references/${ref.id}`, { method: "DELETE" }); route();
        } }, "Usuń")),
      ))))) : h("div", { class: "empty" }, "Baza jest pusta."));
  } catch (e) { list.replaceChildren(h("div", { class: "alert error" }, e.message)); }
}

// ------------------------------------------------------------ ustawienia (APK)
const SETTINGS_FORM = [
  ["Wyszukiwarka internetowa (opcjonalnie)", "Klucz API dodaje wyniki z całego internetu. Bez klucza przeszukiwane są Wikipedia i OpenAlex.", [
    ["BRAVE_API_KEY", "secret", "Brave Search API"],
    ["SERPER_API_KEY", "secret", "Serper (Google)"],
    ["SERPAPI_API_KEY", "secret", "SerpAPI (Google)"],
  ]],
  ["Darmowe źródła", "", [
    ["SEARCH_WIKIPEDIA", "bool", "Wikipedia"],
    ["SEARCH_OPENALEX", "bool", "OpenAlex — publikacje naukowe"],
    ["OPENALEX_MAILTO", "text", "E-mail kontaktowy dla Wikipedii i OpenAlex (opcjonalnie — mniej blokad „za dużo zapytań”)"],
  ]],
  ["Zakres wyszukiwania", "Więcej zapytań = wyższa skuteczność, ale dłuższa analiza i większe zużycie limitu płatnego API.", [
    ["MAX_WEB_QUERIES", "int", "Frazy dokładne na źródło"],
    ["KEYWORD_QUERIES", "int", "Zapytania słowami kluczowymi (wykrywają parafrazy)"],
    ["WIKIPEDIA_MAX_QUERIES", "int", "Limit zapytań do Wikipedii (1 na sekundę)"],
    ["KEYWORD_QUERIES_WEB", "bool", "Słowa kluczowe także do płatnej wyszukiwarki"],
    ["MAX_PAGES_FETCHED", "int", "Maks. stron pobieranych do porównania"],
  ]],
  ["Wykrywanie parafraz", "Niższy próg = więcej wykrytych parafraz, ale też więcej fałszywych trafień.", [
    ["SEMANTIC_ENABLED", "bool", "Model znaczeniowy (synonimy) — działa w telefonie"],
    ["SEMANTIC_THRESHOLD", "float", "Próg modelu znaczeniowego (0,5–0,98)"],
    ["PARAPHRASE_THRESHOLD", "float", "Próg parafraz leksykalnych (0,3–0,95)"],
  ]],
];
const PRESETS = {
  max: { MAX_WEB_QUERIES: 80, KEYWORD_QUERIES: 60, MAX_PAGES_FETCHED: 40, SEMANTIC_ENABLED: true, SEMANTIC_THRESHOLD: 0.78, PARAPHRASE_THRESHOLD: 0.55 },
  std: { MAX_WEB_QUERIES: 40, KEYWORD_QUERIES: 30, MAX_PAGES_FETCHED: 24, SEMANTIC_ENABLED: true, SEMANTIC_THRESHOLD: 0.8, PARAPHRASE_THRESHOLD: 0.6 },
};

async function renderSettings() {
  const card = h("section", { class: "card" }, h("p", { class: "muted" }, "Wczytywanie…"));
  view.append(h("h1", {}, "Ustawienia"), h("p", { class: "muted" }, "Ustawienia są zapisane tylko w tym telefonie."), card);
  let current;
  try { current = await api("/api/settings"); } catch (e) { card.replaceChildren(h("div", { class: "alert error" }, e.message)); return; }
  const inputs = {};
  const msg = h("div", { class: "alert hidden", role: "status" });
  const field = ([key, kind, label]) => {
    const id = `set-${key}`;
    let input;
    if (kind === "bool") {
      input = h("input", { type: "checkbox", id });
      input.checked = !!current[key];
      if (key === "SEMANTIC_ENABLED" && !current._model_available) { input.disabled = true; input.checked = false; }
      inputs[key] = input;
      return h("label", { class: "option", for: id }, input, h("div", {}, h("b", {}, label),
        key === "SEMANTIC_ENABLED" && !current._model_available ? h("span", {}, "Model nie jest dołączony do tej wersji aplikacji.") : null));
    }
    if (kind === "secret") {
      input = h("input", { type: "password", id, autocomplete: "off", placeholder: current[key].set ? `zapisany (${current[key].hint}) — wpisz nowy, aby zmienić` : "nie ustawiono" });
      const clear = current[key].set ? h("button", { class: "btn sm danger", type: "button", onclick: () => { input.value = ""; input.dataset.clear = "1"; input.placeholder = "zostanie usunięty po zapisaniu"; } }, "Usuń") : null;
      inputs[key] = input;
      return h("div", { class: "setting" }, h("label", { for: id }, h("b", {}, label)), h("div", { class: "row" }, input, clear));
    }
    input = h("input", { type: kind === "text" ? "text" : "number", id, step: kind === "float" ? "0.01" : "1", inputmode: kind === "text" ? "email" : "decimal" });
    input.value = current[key] ?? "";
    inputs[key] = input;
    return h("div", { class: "setting" }, h("label", { for: id }, h("b", {}, label)), input);
  };
  const applyPreset = (p) => Object.entries(PRESETS[p]).forEach(([k, v]) => {
    const el = inputs[k]; if (!el || el.disabled) return;
    if (el.type === "checkbox") el.checked = v; else el.value = v;
  });
  const form = h("form", { onsubmit: async (e) => {
    e.preventDefault();
    const payload = {};
    for (const [key, el] of Object.entries(inputs)) {
      if (el.disabled) continue;
      if (el.type === "checkbox") { if (el.checked !== !!current[key]) payload[key] = el.checked; }
      else if (el.type === "password") { if (el.value.trim()) payload[key] = el.value.trim(); else if (el.dataset.clear) payload[key] = ""; }
      else if (String(el.value) !== String(current[key] ?? "")) payload[key] = el.type === "number" ? Number(el.value) : el.value;
    }
    if (!Object.keys(payload).length) { msg.className = "alert"; msg.textContent = "Brak zmian."; return; }
    try {
      current = await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      health = await (await fetch("/api/health")).json();
      route();
      window.AndroidBridge?.toast("Zapisano ustawienia");
    } catch (ex) { msg.className = "alert error"; msg.textContent = ex.message; }
  } },
    h("div", { class: "row", style: { marginBottom: "12px" } },
      h("span", { class: "muted small" }, "Szybki wybór:"),
      h("button", { class: "btn sm", type: "button", onclick: () => applyPreset("max") }, "Maksymalna skuteczność"),
      h("button", { class: "btn sm", type: "button", onclick: () => applyPreset("std") }, "Domyślne")),
    SETTINGS_FORM.map(([title, hint, fields]) => h("fieldset", { class: "settings-group" },
      h("legend", {}, title), hint ? h("p", { class: "muted small" }, hint) : null, fields.map(field))),
    msg,
    h("div", { class: "row end", style: { marginTop: "12px" } }, h("button", { class: "btn primary", type: "submit" }, "Zapisz")),
  );
  card.replaceChildren(form);
}

// ------------------------------------------------------------------------ start
(async () => {
  try {
    health = await (await fetch("/api/health")).json();
    document.getElementById("footer-info").textContent = `PlagCheck ${health.version}${health.mobile ? " · aplikacja na telefon" : ""}`;
    if (health.mobile) {
      document.getElementById("nav-settings").classList.remove("hidden");
      const note = document.querySelector(".footer span:last-child");
      if (note) note.textContent = "Dokumenty i raporty są przechowywane tylko w tym telefonie. ORPPD i prywatne bazy uczelni nie są przeszukiwane.";
    }
  } catch { /* offline */ }
  route();
})();
