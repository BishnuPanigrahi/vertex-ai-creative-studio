const $ = (id) => document.getElementById(id);
const state = { me: null, asked: [], currentQuestion: "", problems: [], problem: null, hints: [], lastMatch: null, lastTailor: "" };

// ---------- Helpers ----------

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(url, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { location.href = "/login.html?mode=login"; throw new ApiError("Please sign in.", 401); }
  if (!res.ok) throw new ApiError(data.detail || `Request failed (${res.status})`, res.status);
  return data;
}

let toastTimer;
function toast(msg, { error = false, upgrade = false } = {}) {
  $("toastMsg").textContent = msg;
  $("toast").classList.toggle("err", error);
  $("toastUpgrade").hidden = !upgrade;
  $("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.remove("show"), upgrade ? 10000 : 5000);
}
$("toastClose").addEventListener("click", () => $("toast").classList.remove("show"));
$("toastUpgrade").addEventListener("click", upgrade);

function showError(e) {
  if (e.status === 401) return;
  toast(e.message, { error: true, upgrade: e.status === 402 && state.me?.plan !== "pro" });
}

const el = (tag, props = {}, children = []) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
const fillList = (node, items) => node.replaceChildren(...items.map((t) => el("li", { textContent: t })));
const fillTags = (node, items, cls = "") => node.replaceChildren(...items.map((t) => el("span", { className: `tag ${cls}`, textContent: t })));

async function busy(btn, label, fn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try { await fn(); } catch (e) { showError(e); } finally { btn.disabled = false; btn.textContent = old; }
}

function download(filename, text, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = el("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied to clipboard."); }
  catch { toast("Couldn't copy. Select the text and copy it manually.", { error: true }); }
}

function ctx() {
  return {
    role: $("role").value.trim() || "Software Engineer",
    level: $("level").value,
    interview_type: $("type").value,
    resume: $("resume").value,
    job_description: $("jd").value,
  };
}

// ---------- Account ----------

async function loadMe() {
  const me = await api("/api/me");
  state.me = me;
  const pro = me.plan === "pro";
  $("planBadge").textContent = me.plan;
  $("planBadge").classList.toggle("pro", pro);
  $("menuEmail").textContent = me.email;
  $("upgradeBtn").hidden = pro;
  $("billingBtn").hidden = !(me.billing_enabled && me.has_subscription);
  $("devFreeBtn").hidden = !(me.dev_upgrade && pro);
  if (pro) $("usage").textContent = "Unlimited practice";
  else {
    const left = (k) => Math.max(0, (me.limits[k] ?? 0) - (me.usage[k] ?? 0));
    $("usage").textContent = `Today: ${left("question")} questions · ${left("coding")} problems · ${left("match")} resume left`;
  }
  return me;
}

async function upgrade() {
  try {
    if (state.me?.billing_enabled) {
      const { url } = await api("/api/billing/checkout", { method: "POST" });
      location.href = url;
    } else if (state.me?.dev_upgrade) {
      await api("/api/billing/dev-plan?plan=pro", { method: "POST" });
      await loadMe();
      $("upgradedBanner").hidden = false;
    } else {
      toast("Payments aren't set up on this server yet.", { error: true });
    }
  } catch (e) { showError(e); }
}

$("upgradeBtn").addEventListener("click", upgrade);
$("menuBtn").addEventListener("click", (e) => { e.stopPropagation(); $("menu").classList.toggle("open"); });
document.addEventListener("click", () => $("menu").classList.remove("open"));
$("billingBtn").addEventListener("click", async () => {
  try { location.href = (await api("/api/billing/portal", { method: "POST" })).url; } catch (e) { showError(e); }
});
$("devFreeBtn").addEventListener("click", async () => {
  try { await api("/api/billing/dev-plan?plan=free", { method: "POST" }); await loadMe(); } catch (e) { showError(e); }
});
$("logoutBtn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  location.href = "/";
});
$("deleteBtn").addEventListener("click", async () => {
  if (!confirm("Delete your account and all practice history? This can't be undone.")) return;
  try { await api("/api/account", { method: "DELETE" }); location.href = "/"; } catch (e) { showError(e); }
});

$("saveProfile").addEventListener("click", () =>
  busy($("saveProfile"), "Saving…", async () => {
    const c = ctx();
    await api("/api/profile", { method: "PUT", body: { role: c.role, level: c.level, resume: c.resume, job_description: c.job_description } });
    $("profileMsg").textContent = "Saved.";
    setTimeout(() => ($("profileMsg").textContent = ""), 2500);
  })
);

// ---------- Tabs ----------

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === name));
  if (name === "progress") loadProgress();
  try { localStorage.setItem("poised.tab", name); } catch {}
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------- Speech ----------

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function makeRecognizer(onText) {
  if (!SR) return null;
  const r = new SR();
  r.continuous = true;
  r.interimResults = false;
  r.lang = "en-US";
  r.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) onText(e.results[i][0].transcript.trim());
    }
  };
  return r;
}

function speak(text) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    u.onend = resolve;
    u.onerror = resolve;
    speechSynthesis.speak(u);
  });
}

// ---------- Mock interview ----------

let answerRec = null;
let answerStart = 0;
let answerTick = null;

function stopAnswerMic() {
  if (answerRec) { const r = answerRec; answerRec = null; r.stop(); }
  $("micAnswer").textContent = "🎙️ Speak answer";
}

function startAnswerMic() {
  if (!SR) { toast("Speech recognition isn't supported in this browser. Try Chrome or Edge, or type your answer.", { error: true }); return; }
  answerRec = makeRecognizer((t) => { $("answer").value += ($("answer").value ? " " : "") + t; });
  answerRec.onend = () => { answerRec = null; $("micAnswer").textContent = "🎙️ Speak answer"; };
  answerRec.start();
  $("micAnswer").textContent = "⏹ Stop recording";
}

function startAnswerTimer() {
  answerStart = Date.now();
  clearInterval(answerTick);
  answerTick = setInterval(() => {
    const s = Math.floor((Date.now() - answerStart) / 1000);
    $("answerTimer").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} elapsed`;
  }, 1000);
}

async function presentQuestion(text, tests, label) {
  state.currentQuestion = text;
  $("qLabel").textContent = label;
  $("qText").textContent = text;
  $("qTests").textContent = tests ? `Tests: ${tests}` : "";
  $("qBox").hidden = false;
  $("answerBox").hidden = false;
  $("fbBox").hidden = true;
  $("answer").value = "";
  startAnswerTimer();
  if ($("voiceMode").checked) {
    await speak(text);
    startAnswerMic();
  }
}

$("nextQ").addEventListener("click", () =>
  busy($("nextQ"), "Thinking…", async () => {
    stopAnswerMic();
    const q = await api("/api/question", { method: "POST", body: { ...ctx(), previous: state.asked } });
    state.asked.push(q.question);
    loadMe();
    await presentQuestion(q.question, q.what_it_tests, `Question ${state.asked.length}`);
  }).then(() => { if (state.asked.length) $("nextQ").textContent = "Next question"; })
);

$("micAnswer").addEventListener("click", () => (answerRec ? stopAnswerMic() : startAnswerMic()));

$("submitAnswer").addEventListener("click", () =>
  busy($("submitAnswer"), "Scoring…", async () => {
    stopAnswerMic();
    clearInterval(answerTick);
    const fb = await api("/api/feedback", {
      method: "POST",
      body: { role: ctx().role, question: state.currentQuestion, answer: $("answer").value, interview_type: ctx().interview_type },
    });
    $("fbScore").textContent = `${fb.score}/10`;
    fillList($("fbStrengths"), fb.strengths);
    fillList($("fbImprove"), fb.improvements);
    $("fbBetter").textContent = fb.stronger_answer;
    $("fbFollow").textContent = fb.follow_up_question;
    $("fbBox").hidden = false;
    if ($("voiceMode").checked) speak(`You scored ${fb.score} out of 10. ${fb.improvements[0] || ""}`);
  })
);

$("answerFollow").addEventListener("click", () => presentQuestion($("fbFollow").textContent, "", "Follow-up"));

// ---------- Coding interview ----------

let codeTick = null;
const CODE_MINUTES = { easy: 20, medium: 35, hard: 50 };

function startCodeTimer(minutes) {
  const end = Date.now() + minutes * 60000;
  clearInterval(codeTick);
  const draw = () => {
    const ms = end - Date.now();
    const s = Math.abs(Math.round(ms / 1000));
    const t = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    $("codeTimer").textContent = ms >= 0 ? `⏱ ${t} left` : `⏱ ${t} over time`;
    $("codeTimer").classList.toggle("late", ms < 0);
  };
  draw();
  codeTick = setInterval(draw, 1000);
}

$("getProblem").addEventListener("click", () =>
  busy($("getProblem"), "Generating…", async () => {
    const p = await api("/api/coding/problem", {
      method: "POST",
      body: { language: $("lang").value, difficulty: $("difficulty").value, topic: $("topic").value, previous: state.problems },
    });
    state.problem = p;
    state.problems.push(p.title);
    state.hints = [];
    $("pTitle").textContent = p.title;
    $("pStatement").textContent = p.statement;
    $("pExamples").textContent = p.examples.join("\n\n");
    fillList($("pConstraints"), p.constraints);
    $("editor").value = p.starter_code;
    $("hints").replaceChildren();
    $("problemBox").hidden = false;
    $("reviewBox").hidden = true;
    startCodeTimer(CODE_MINUTES[$("difficulty").value] || 35);
    loadMe();
  })
);

$("editor").addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  e.preventDefault();
  const t = e.target;
  const { selectionStart: s, selectionEnd: end } = t;
  t.setRangeText("    ", s, end, "end");
});

$("hintBtn").addEventListener("click", () =>
  busy($("hintBtn"), "Thinking…", async () => {
    const h = await api("/api/coding/hint", {
      method: "POST",
      body: { statement: state.problem.statement, code: $("editor").value, hints_given: state.hints.length },
    });
    state.hints.push(h.hint);
    fillList($("hints"), state.hints);
  })
);

$("reviewBtn").addEventListener("click", () =>
  busy($("reviewBtn"), "Reviewing…", async () => {
    const r = await api("/api/coding/review", {
      method: "POST",
      body: { title: state.problem.title, statement: state.problem.statement, code: $("editor").value, language: $("lang").value },
    });
    clearInterval(codeTick);
    $("rScore").textContent = `${r.score}/10`;
    $("rCorrect").textContent = r.correctness;
    $("rTime").textContent = r.time_complexity;
    $("rSpace").textContent = r.space_complexity;
    fillList($("rIssues"), r.issues);
    $("rCode").textContent = r.improved_code;
    $("reviewBox").hidden = false;
  })
);

// ---------- Practice coach ----------

let coachRec = null;
let coachText = "";
let coachTimer = null;

async function suggest() {
  if (!coachText.trim()) { toast("Nothing in the transcript yet.", { error: true }); return; }
  const out = await api("/api/assist", { method: "POST", body: { role: ctx().role, transcript: coachText, resume: ctx().resume } });
  $("coachQ").textContent = out.detected_question;
  fillList($("coachPoints"), out.talking_points);
  $("coachOut").hidden = false;
  loadMe();
}

$("coachStart").addEventListener("click", () => {
  if (!SR) { toast("Speech recognition isn't supported in this browser. Try Chrome or Edge.", { error: true }); return; }
  coachRec = makeRecognizer((t) => {
    coachText += t + "\n";
    $("coachTranscript").textContent = coachText;
    clearTimeout(coachTimer);
    if (/\?$|^(tell me|describe|walk me|how would|why|what|explain)/i.test(t)) coachTimer = setTimeout(() => suggest().catch(showError), 800);
  });
  coachRec.onend = () => { if (coachRec) coachRec.start(); }; // keep listening until stopped
  coachRec.start();
  $("coachStart").disabled = true;
  $("coachStop").disabled = false;
});

$("coachStop").addEventListener("click", () => {
  const r = coachRec;
  coachRec = null;
  if (r) r.stop();
  $("coachStart").disabled = false;
  $("coachStop").disabled = true;
});

$("coachSuggest").addEventListener("click", () => busy($("coachSuggest"), "Thinking…", suggest));
$("coachClear").addEventListener("click", () => { coachText = ""; $("coachTranscript").textContent = ""; $("coachOut").hidden = true; });

// ---------- Resume ----------

function resumeForm() {
  const jd = $("jd").value.trim();
  if (!jd) throw new ApiError("Paste a job description in the field above first.", 400);
  const form = new FormData();
  form.append("job_description", jd);
  form.append("resume_text", $("resume").value);
  if ($("resumeFile").files[0]) form.append("resume_file", $("resumeFile").files[0]);
  return form;
}

$("runMatch").addEventListener("click", () =>
  busy($("runMatch"), "Analyzing…", async () => {
    const m = await api("/api/resume-match", { method: "POST", form: resumeForm() });
    state.lastMatch = m;
    $("mScore").textContent = `${m.match_score}% match`;
    fillTags($("mMatched"), m.matched_skills);
    fillTags($("mMissing"), m.missing_skills, "miss");
    fillList($("mBullets"), m.bullet_rewrites);
    $("mLetter").textContent = m.cover_letter;
    $("matchOut").hidden = false;
    loadMe();
  })
);

$("runTailor").addEventListener("click", () =>
  busy($("runTailor"), "Writing…", async () => {
    const t = await api("/api/resume-tailor", { method: "POST", form: resumeForm() });
    state.lastTailor = t.resume_markdown;
    $("tResume").textContent = t.resume_markdown;
    $("tailorOut").hidden = false;
    loadMe();
  })
);

$("copyLetter").addEventListener("click", () => copy($("mLetter").textContent));
$("dlLetter").addEventListener("click", () => download("cover-letter.txt", $("mLetter").textContent));
$("copyResume").addEventListener("click", () => copy(state.lastTailor));
$("dlResume").addEventListener("click", () => download("tailored-resume.md", state.lastTailor, "text/markdown"));

// ---------- Progress ----------

const KIND_LABEL = { mock: "Mock interview", coding: "Coding", match: "Resume match" };
let historyCache = [];

function sparkline(values, max) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 100 32");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.classList.add("spark");
  if (values.length < 2) return svg;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${32 - (v / max) * 28 - 2}`).join(" ");
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", pts);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "var(--accent-2)");
  line.setAttribute("stroke-width", "2");
  line.setAttribute("vector-effect", "non-scaling-stroke");
  svg.append(line);
  return svg;
}

function statCard(kind, s, trend) {
  const max = kind === "match" ? 100 : 10;
  const avg = s?.average != null ? `${s.average}${kind === "match" ? "%" : "/10"}` : "–";
  return el("div", { className: "card stat" }, [
    el("div", { className: "hint", textContent: KIND_LABEL[kind] }),
    el("div", { className: "num", textContent: avg }),
    el("p", { className: "hint", textContent: `${s?.count ?? 0} saved · average score` }),
    sparkline(trend || [], max),
  ]);
}

function historyBody(h) {
  const r = h.result;
  const parts = [];
  const section = (title, node) => parts.push(el("div", {}, [el("strong", { textContent: title }), node]));
  const list = (items) => el("ul", {}, (items || []).map((t) => el("li", { textContent: t })));
  const para = (t) => el("p", { textContent: t, style: "white-space: pre-wrap; margin: 4px 0 0" });
  if (h.kind === "mock") {
    section("Your answer", para(h.answer));
    section("Strengths", list(r.strengths));
    section("Improve", list(r.improvements));
    section("Stronger answer", para(r.stronger_answer));
  } else if (h.kind === "coding") {
    section("Your code", el("pre", { className: "code-out", textContent: h.answer }));
    section("Correctness", para(r.correctness));
    section("Complexity", para(`Time: ${r.time_complexity} · Space: ${r.space_complexity}`));
    section("Issues", list(r.issues));
  } else {
    section("Missing skills", list(r.missing_skills));
    section("Suggested bullets", list(r.bullet_rewrites));
    section("Cover letter", para(r.cover_letter));
  }
  const del = el("button", { className: "btn small danger", textContent: "Delete" });
  del.addEventListener("click", async () => {
    try { await api(`/api/history/${h.id}`, { method: "DELETE" }); loadProgress(); } catch (e) { showError(e); }
  });
  parts.push(el("div", { className: "actions" }, [del]));
  return el("div", { className: "body stack" }, parts);
}

function renderHistory() {
  const filter = $("histFilter").value;
  const items = historyCache.filter((h) => !filter || h.kind === filter);
  if (!items.length) {
    $("historyList").replaceChildren(el("div", { className: "empty", textContent: "No saved practice yet. Answer a question or submit a solution to start building your history." }));
    return;
  }
  $("historyList").replaceChildren(
    ...items.map((h) => {
      const score = h.score == null ? "" : h.kind === "match" ? `${h.score}%` : `${h.score}/10`;
      const summary = el("summary", {}, [
        el("span", { className: "tag", textContent: KIND_LABEL[h.kind] }),
        el("span", { className: "q", textContent: h.question || "(untitled)" }),
        el("strong", { textContent: score }),
        el("span", { className: "when", textContent: new Date(h.created_at + "Z").toLocaleDateString() }),
      ]);
      const d = el("details", { className: "history-item" }, [summary]);
      d.addEventListener("toggle", () => { if (d.open && d.children.length === 1) d.append(historyBody(h)); }, { once: false });
      return d;
    })
  );
}

async function loadProgress() {
  try {
    const [stats, hist] = await Promise.all([api("/api/stats"), api("/api/history?limit=200")]);
    historyCache = hist;
    $("stats").replaceChildren(...["mock", "coding", "match"].map((k) => statCard(k, stats.by_kind[k], stats.trend[k])));
    renderHistory();
  } catch (e) { showError(e); }
}

$("histFilter").addEventListener("change", renderHistory);

$("exportBtn").addEventListener("click", () => {
  const lines = [`# Poised practice report`, ``, `Exported ${new Date().toLocaleString()} for ${state.me?.email || ""}`, ``];
  for (const h of historyCache) {
    const r = h.result;
    lines.push(`## ${KIND_LABEL[h.kind]}: ${h.question}`, ``, `- Date: ${h.created_at} UTC`, `- Score: ${h.score ?? "n/a"}`, ``);
    if (h.kind === "mock") {
      lines.push(`**Answer:** ${h.answer}`, ``, `**Strengths:**`, ...(r.strengths || []).map((s) => `- ${s}`), ``, `**Improve:**`, ...(r.improvements || []).map((s) => `- ${s}`), ``, `**Stronger answer:** ${r.stronger_answer}`, ``);
    } else if (h.kind === "coding") {
      lines.push("```", h.answer, "```", ``, `**Correctness:** ${r.correctness}`, `**Complexity:** ${r.time_complexity} time, ${r.space_complexity} space`, ``);
    } else {
      lines.push(`**Missing skills:** ${(r.missing_skills || []).join(", ")}`, ``);
    }
  }
  download("poised-report.md", lines.join("\n"), "text/markdown");
});

// ---------- Boot ----------

(async () => {
  let me;
  try { me = await loadMe(); } catch { return; }
  const p = me.profile;
  if (p.role) $("role").value = p.role;
  if (p.level) $("level").value = p.level;
  $("resume").value = p.resume || "";
  $("jd").value = p.job_description || "";
  const params = new URLSearchParams(location.search);
  if (params.get("upgraded")) { $("upgradedBanner").hidden = false; history.replaceState(null, "", "/app.html"); }
  if (params.get("upgrade") && me.plan !== "pro") upgrade();
  let tab = "mock";
  try { tab = localStorage.getItem("poised.tab") || "mock"; } catch {}
  if ($(tab)) showTab(tab);
})();
