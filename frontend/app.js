// Minimal dependency-free dashboard. Routes: #/  #/p/<id>  #/p/<id>/scene/<n>
"use strict";

const $app = document.getElementById("app");
const $crumbs = document.getElementById("crumbs");
const $jobs = document.getElementById("jobs");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ICON = { not_generated: "—", generating: "⟳", generated: "•", ai_passed: "✓?",
  needs_review: "⚠", approved: "✓", rejected: "✗", failed: "✗" };
const CLS = { approved: "ok", ai_passed: "ok", needs_review: "warn", failed: "bad",
  rejected: "bad" };
const bust = () => `?t=${Date.now()}`;
const sceneUrl = (pid, sid) => `/files/${pid}/scenes/${String(sid).padStart(3, "0")}`;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : res.statusText);
  return data;
}

function act(fn) {
  return async (ev) => {
    const btn = ev?.currentTarget;
    if (btn) btn.disabled = true;
    try { await fn(); await route(); } catch (e) { alert(e.message); }
    finally { if (btn) btn.disabled = false; }
  };
}

function bind(sel, fn) {
  document.querySelectorAll(sel).forEach((el) => (el.onclick = act(() => fn(el.dataset))));
}

// --- jobs ---------------------------------------------------------------------------------
let currentProject = null;
let hadRunning = false;
async function pollJobs() {
  try {
    const jobs = await api(`/api/jobs${currentProject ? `?project=${currentProject}` : ""}`);
    const recent = jobs.slice(0, 6);
    $jobs.innerHTML = recent.map((j) => `<div class="job">
      <b>#${j.id} ${esc(j.kind)}${j.scene_id ? ` · scene ${j.scene_id}` : ""}</b>
      <span class="${j.status === "FAILED" ? "bad" : j.status === "COMPLETE" ? "ok" : "warn"}">
      ${esc(j.status)}</span><br><span class="muted">${esc((j.error || j.message || "")
        .split("\n")[0].slice(0, 160))}</span></div>`).join("");
    const running = jobs.some((j) => !["COMPLETE", "FAILED"].includes(j.status));
    if (hadRunning && !running) route();
    hadRunning = running;
  } catch (_) { /* server restarting */ }
}
setInterval(pollJobs, 2500);

async function runStage(pid, stage, params = {}) {
  const q = new URLSearchParams(params).toString();
  await api(`/api/projects/${pid}/stages/${stage}${q ? `?${q}` : ""}`, { method: "POST" });
  hadRunning = true;
  pollJobs();
}

// --- pages --------------------------------------------------------------------------------
async function projectsPage() {
  currentProject = null;
  $crumbs.innerHTML = "";
  const projects = await api("/api/projects");
  $app.innerHTML = `<h1>Projects</h1>
    <div class="panel"><table><tr><th>ID</th><th>Title</th></tr>
    ${projects.map((p) => `<tr><td><a href="#/p/${esc(p.id)}">${esc(p.id)}</a></td>
      <td>${esc(p.title)} ${p.error ? `<span class="bad">${esc(p.error)}</span>` : ""}</td>
      </tr>`).join("") || `<tr><td colspan=2 class="muted">No projects yet</td></tr>`}
    </table></div>
    <div class="panel"><h2>New project</h2><div class="row">
      <input id="np-id" placeholder="fruit-song"> <input id="np-title" placeholder="Title">
      <input id="np-topic" placeholder="Topic"> <input id="np-dur" type="number" placeholder="120"
        style="width:80px"> <button class="primary" id="np-go">Create</button></div>
      <p class="muted">Then edit <code>projects/&lt;id&gt;/project.yaml</code>.</p></div>`;
  document.getElementById("np-go").onclick = act(async () => {
    const v = (id) => document.getElementById(id).value.trim() || null;
    const body = { id: v("np-id"), title: v("np-title"), topic: v("np-topic"),
      duration: v("np-dur") ? Number(v("np-dur")) : null };
    await api("/api/projects", { method: "POST", body });
    location.hash = `#/p/${body.id}`;
  });
}

const STAGES = [
  ["lyrics", "Lyrics + plan"], ["music", "Music"], ["timing", "Timing + storyboard"],
  ["images", "Images"], ["image_review", "AI image review"], ["videos", "Videos"],
  ["video_review", "AI video review"], ["render_preview", "Render preview"],
  ["render_youtube", "Render YouTube"], ["render_shorts", "Render Shorts"],
  ["thumbnail", "Thumbnails"], ["metadata", "Metadata"],
];

async function projectPage(pid) {
  currentProject = pid;
  $crumbs.innerHTML = `/ <a href="#/p/${pid}">${esc(pid)}</a>`;
  const st = await api(`/api/projects/${pid}`);
  let plan = null;
  if (st.stages.lyrics) plan = await api(`/api/projects/${pid}/plan`);
  const thumbs = await api(`/api/projects/${pid}/thumbnail`);
  const s = st.stages;
  const yes = (b) => (b ? `<span class="ok">✓</span>` : `<span class="muted">—</span>`);

  const review = plan?.review;
  const reviewHtml = review ? `<p>Language review: ${review.pass ? `<span class="ok">pass</span>`
      : `<span class="warn">issues</span>`} <span class="muted">${esc(review.summary)}</span></p>
    <ul class="problems">${review.issues.map((i) => `<li>line ${i.line} [${esc(i.severity)} /
      ${esc(i.category)}] ${esc(i.reason)}<br><span class="muted">→ ${esc(i.suggestion)}
      </span></li>`).join("")}</ul>` : "";

  $app.innerHTML = `<h1>${esc(st.title)}</h1>
  <div class="grid">
    <div class="panel"><h2>Pipeline</h2><table>
      <tr><td>Lyrics</td><td>${yes(s.lyrics)}</td></tr>
      <tr><td>Music</td><td>${yes(s.music)}</td></tr>
      <tr><td>Timing</td><td>${yes(s.timing)}</td></tr>
      <tr><td>Storyboard</td><td>${yes(s.storyboard)}</td></tr>
      <tr><td>Images</td><td>${esc(s.images)}</td></tr>
      <tr><td>Videos</td><td>${esc(s.videos)}</td></tr>
      <tr><td>Thumbnail</td><td>${yes(s.thumbnail)}</td></tr>
      <tr><td>Metadata</td><td>${yes(s.metadata)}</td></tr></table>
      <p>${STAGES.map(([k, label]) => `<button data-stage="${k}">${label}</button>`).join("")}</p>
      <label class="muted"><input type="checkbox" id="force"> force / regenerate</label></div>
    <div class="panel"><h2>Approvals</h2><table>
      ${Object.entries(st.gates).map(([g, i]) => `<tr><td>${g}</td>
        <td>${i.approved ? `<span class="ok">✓</span>` : `<span class="muted">—</span>`}</td>
        <td class="muted">${esc(i.reason)}</td>
        <td>${i.approved ? "" : `<button data-gate="${g}">Approve</button>`}</td></tr>`).join("")}
      </table></div>
    <div class="panel"><h2>Costs (est.)</h2><table>
      ${st.costs.rows.map((r) => `<tr><td>${esc(r.label)}</td><td class="num">
        $${r.cost.toFixed(2)}</td><td class="num muted">${r.calls}</td></tr>`).join("")}
      <tr><th>TOTAL</th><th class="num">$${st.costs.total.toFixed(2)}</th>
        <th class="num muted">${st.costs.cache_hits} cached</th></tr></table></div>
  </div>

  ${plan ? `<div class="panel"><h2>${esc(plan.plan.title)} <span class="muted">
    ${esc(plan.plan.title_secondary)}</span></h2>${reviewHtml}
    <table><tr><th>#</th><th>Section</th><th>Sung</th><th>Primary</th><th>Secondary</th></tr>
    ${plan.plan.lyrics.map((l) => `<tr><td>${l.id}</td><td>${esc(l.section)}</td>
      <td>${esc(l.sung)}</td><td>${esc(l.primary)}</td><td>${esc(l.secondary)}</td></tr>`)
      .join("")}</table>
    <details><summary>Edit plan JSON</summary>
      <textarea id="plan-json">${esc(JSON.stringify(plan.plan, null, 2))}</textarea>
      <button class="primary" id="plan-save">Save plan</button></details></div>` : ""}

  ${st.scenes.length ? `<h2>Scenes</h2><div class="scenes">${st.scenes.map((sc) => `
    <a class="scene" href="#/p/${pid}/scene/${sc.id}">
      ${sc.image_versions ? `<img loading="lazy" src="${sceneUrl(pid, sc.id)}/selected.png${bust()}">`
        : `<div class="thumb"></div>`}
      <div class="meta"><b>${String(sc.id).padStart(2, "0")}</b> ${esc(sc.lyrics[0])}<br>
        <span class="${CLS[sc.image_status] || ""}">${ICON[sc.image_status]} image
        ${esc(sc.image_status)}</span> ·
        <span class="${CLS[sc.video_status] || ""}">${ICON[sc.video_status]} video
        ${esc(sc.video_status)}</span>
        ${sc.start != null ? `<br><span class="muted">${sc.start.toFixed(2)}–${sc.end.toFixed(2)}s
        </span>` : ""}
        ${[...sc.image_problems, ...sc.video_problems].map((p) => `<br><span class="warn">⚠
          ${esc(p)}</span>`).join("")}
        ${sc.error ? `<br><span class="bad">${esc(sc.error.slice(0, 140))}</span>` : ""}
      </div></a>`).join("")}</div>` : ""}

  ${Object.keys(st.renders).length ? `<div class="grid" style="margin-top:16px">
    ${Object.entries(st.renders).map(([preset, r]) => `<div class="panel"><h2>${esc(preset)}</h2>
      <video controls src="/files/${pid}/${esc(r.file)}${bust()}"></video>
      ${r.qc ? `<table>${r.qc.checks.map((c) => `<tr><td class="${c.passed ? "ok" : "bad"}">
        ${c.passed ? "✓" : "✗"}</td><td>${esc(c.name)}</td><td class="muted">${esc(c.detail)}
        </td></tr>`).join("")}</table>` : ""}</div>`).join("")}</div>` : ""}

  ${thumbs.candidates.length ? `<div class="panel"><h2>Thumbnail</h2><div class="versions">
    ${thumbs.candidates.map((n) => `<div class="v" data-thumb="${n}"><img
      src="/files/${pid}/thumbnail/candidate_v${n}.png">use v${n}</div>`).join("")}</div>
    ${thumbs.selected ? `<img class="preview" style="max-width:640px"
      src="/files/${pid}/thumbnail/selected.png${bust()}">` : ""}</div>` : ""}`;

  bind("[data-stage]", (d) => runStage(pid, d.stage,
    document.getElementById("force").checked ? { force: true } : {}));
  bind("[data-gate]", (d) => api(`/api/projects/${pid}/approve/${d.gate}`, { method: "POST" }));
  bind("[data-thumb]", (d) => api(`/api/projects/${pid}/thumbnail/select?version=${d.thumb}`,
    { method: "POST" }));
  const save = document.getElementById("plan-save");
  if (save) save.onclick = act(() => api(`/api/projects/${pid}/plan`, { method: "PUT",
    body: JSON.parse(document.getElementById("plan-json").value) }));
}

function trackPanel(pid, sid, data, track) {
  const t = data.state[track];
  const sel = t.versions.find((v) => v.version === t.selected);
  const review = sel?.review;
  const dir = sceneUrl(pid, sid);
  const media = (file) => track === "image" ? `<img src="${dir}/${file}">`
    : `<video src="${dir}/${file}#t=0.5" muted preload="metadata"></video>`;
  const prompts = data.prompts[track];
  return `<div class="panel"><h2>${track === "image" ? "Image" : "Animation"}
    <span class="chip ${CLS[t.status] || ""}">${ICON[t.status]} ${esc(t.status)}</span></h2>
    ${t.selected ? (track === "image" ? `<img class="preview" src="${dir}/selected.png${bust()}">`
      : `<video controls class="preview" src="${dir}/selected_video.mp4${bust()}"></video>`)
      : `<p class="muted">Not generated.</p>`}
    ${t.error ? `<p class="bad">${esc(t.error)}</p>` : ""}
    ${review ? `<p>AI review: <b class="${review.overall === "pass" ? "ok" : "warn"}">
      ${esc(review.overall)}</b></p><ul class="problems">${review.problems.map((p) =>
      `<li>⚠ ${esc(p)}</li>`).join("")}</ul><p class="muted">${Object.entries(review.checks)
      .map(([k, v]) => `${v ? "✓" : "✗"} ${k}`).join(" · ")}</p>` : ""}
    <div class="versions">${t.versions.map((v) => `<div class="v ${v.version === t.selected
      ? "sel" : ""}" data-select="${v.version}" data-track="${track}">${media(v.file)}
      v${v.version}${v.cache_hit ? " (cache)" : ""}</div>`).join("")}</div>
    <div class="row">
      <button class="primary" data-act="approve" data-track="${track}"
        ${t.selected ? "" : "disabled"}>${t.status === "needs_review" ? "Approve anyway"
        : "Approve"}</button>
      <button data-act="reject" data-track="${track}" ${t.selected ? "" : "disabled"}>Reject</button>
      <button data-regen="${track}">${t.versions.length ? "Regenerate" : "Generate"}</button>
      <button data-review="${track}" ${t.selected ? "" : "disabled"}>AI review</button>
    </div>
    <details ${prompts.override ? "open" : ""}><summary>Prompt ${prompts.override
      ? "(edited)" : ""}</summary>
      <textarea id="prompt-${track}">${esc(prompts.override || prompts.compiled ||
        "(compiled on first generation)")}</textarea>
      <button data-save-prompt="${track}">Save as override</button>
      <button data-clear-prompt="${track}">Use compiled prompt</button></details>
</div>`;
}

async function scenePage(pid, sid) {
  currentProject = pid;
  $crumbs.innerHTML = `/ <a href="#/p/${pid}">${esc(pid)}</a> / scene ${sid}`;
  const data = await api(`/api/projects/${pid}/scenes/${sid}`);
  const sc = data.scene;
  $app.innerHTML = `<h1>Scene ${sid}</h1>
    <div class="panel">${data.lyrics.map((l) => `<p><b>${esc(l.sung)}</b><br>
      <span class="muted">${esc(l.primary)} · ${esc(l.secondary)}</span></p>`).join("")}
      <p>${esc(sc.action)}</p><p class="muted">Characters: ${esc(sc.characters.join(", "))
      || "none"} · Camera: ${esc(sc.camera)} · ${data.timing ? `${data.timing.start.toFixed(2)}–
      ${data.timing.end.toFixed(2)}s` : "untimed"}</p>
      <p class="muted">Motion: ${esc(sc.motion_prompt)}</p></div>
    <div class="grid">${trackPanel(pid, sid, data, "image")}${trackPanel(pid, sid, data,
      "video")}</div>`;
  const base = `/api/projects/${pid}/scenes/${sid}`;
  bind("[data-act]", (d) => api(`${base}/${d.track}/${d.act}`, { method: "POST" }));
  bind("[data-select]", (d) => api(`${base}/${d.track}/select?version=${d.select}`,
    { method: "POST" }));
  bind("[data-regen]", (d) => runStage(pid, d.regen === "image" ? "images" : "videos",
    { scene: sid, force: true }));
  bind("[data-review]", (d) => runStage(pid, d.review === "image" ? "image_review"
    : "video_review", { scene: sid, force: true }));
  bind("[data-save-prompt]", (d) => api(`${base}/${d.savePrompt}/prompt`, { method: "PUT",
    body: { text: document.getElementById(`prompt-${d.savePrompt}`).value } }));
  bind("[data-clear-prompt]", (d) => api(`${base}/${d.clearPrompt}/prompt`, { method: "PUT",
    body: { text: null } }));
}

async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  try {
    if (parts[0] === "p" && parts[2] === "scene") await scenePage(parts[1], Number(parts[3]));
    else if (parts[0] === "p") await projectPage(parts[1]);
    else await projectsPage();
  } catch (e) {
    $app.innerHTML = `<p class="bad">${esc(e.message)}</p>`;
  }
  pollJobs();
}

window.addEventListener("hashchange", route);
route();
