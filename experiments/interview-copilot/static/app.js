const $ = (id) => document.getElementById(id);
const asked = [];
let currentQuestion = "";

function ctx() {
  return {
    role: $("role").value.trim() || "Software Engineer",
    level: $("level").value,
    interview_type: $("type").value,
    resume: $("resume").value,
    job_description: $("jd").value,
  };
}

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function fillList(el, items) {
  el.replaceChildren(...items.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
}

function fillTags(el, items, cls = "") {
  el.replaceChildren(...items.map((t) => Object.assign(document.createElement("span"), { className: `tag ${cls}`, textContent: t })));
}

async function busy(btn, label, fn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try { await fn(); } finally { btn.disabled = false; btn.textContent = old; }
}

// Tabs
document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === b.dataset.tab));
  })
);

// Speech recognition helper
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

// Mock interview
$("nextQ").addEventListener("click", () =>
  busy($("nextQ"), "Thinking…", async () => {
    $("mockErr").textContent = "";
    try {
      const q = await post("/api/question", { ...ctx(), previous: asked });
      currentQuestion = q.question;
      asked.push(q.question);
      $("qText").textContent = q.question;
      $("qTests").textContent = `Tests: ${q.what_it_tests}`;
      $("qBox").hidden = false;
      $("answerBox").hidden = false;
      $("fbBox").hidden = true;
      $("answer").value = "";
    } catch (e) { $("mockErr").textContent = e.message; }
  }).then(() => { if (asked.length) $("nextQ").textContent = "Next question"; })
);

let answerRec = null;
$("micAnswer").addEventListener("click", () => {
  if (!SR) { $("mockErr").textContent = "Speech recognition isn't supported in this browser. Try Chrome or Edge, or type your answer."; return; }
  if (answerRec) { answerRec.stop(); answerRec = null; $("micAnswer").textContent = "🎙️ Speak answer"; return; }
  answerRec = makeRecognizer((t) => { $("answer").value += ($("answer").value ? " " : "") + t; });
  answerRec.onend = () => { answerRec = null; $("micAnswer").textContent = "🎙️ Speak answer"; };
  answerRec.start();
  $("micAnswer").textContent = "⏹ Stop recording";
});

$("submitAnswer").addEventListener("click", () =>
  busy($("submitAnswer"), "Scoring…", async () => {
    $("mockErr").textContent = "";
    const answer = $("answer").value.trim();
    if (!answer) { $("mockErr").textContent = "Write or speak an answer first."; return; }
    try {
      const fb = await post("/api/feedback", { role: ctx().role, question: currentQuestion, answer });
      $("fbScore").textContent = `${fb.score}/10`;
      fillList($("fbStrengths"), fb.strengths);
      fillList($("fbImprove"), fb.improvements);
      $("fbBetter").textContent = fb.stronger_answer;
      $("fbBox").hidden = false;
    } catch (e) { $("mockErr").textContent = e.message; }
  })
);

// Practice coach
let coachRec = null;
let coachText = "";
let coachTimer = null;

async function suggest() {
  if (!coachText.trim()) return;
  $("coachErr").textContent = "";
  try {
    const out = await post("/api/assist", { role: ctx().role, transcript: coachText, resume: ctx().resume });
    $("coachQ").textContent = out.detected_question;
    fillList($("coachPoints"), out.talking_points);
    $("coachOut").hidden = false;
  } catch (e) { $("coachErr").textContent = e.message; }
}

$("coachStart").addEventListener("click", () => {
  if (!SR) { $("coachErr").textContent = "Speech recognition isn't supported in this browser. Try Chrome or Edge."; return; }
  coachRec = makeRecognizer((t) => {
    coachText += t + "\n";
    $("coachTranscript").textContent = coachText;
    clearTimeout(coachTimer);
    if (t.endsWith("?")) coachTimer = setTimeout(suggest, 800);
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

// Resume match
$("runMatch").addEventListener("click", () =>
  busy($("runMatch"), "Analyzing…", async () => {
    $("matchErr").textContent = "";
    const jd = $("jd").value.trim();
    if (!jd) { $("matchErr").textContent = "Paste a job description in the field above first."; return; }
    const form = new FormData();
    form.append("job_description", jd);
    form.append("resume_text", $("resume").value);
    if ($("resumeFile").files[0]) form.append("resume_file", $("resumeFile").files[0]);
    try {
      const res = await fetch("/api/resume-match", { method: "POST", body: form });
      const m = await res.json();
      if (!res.ok) throw new Error(m.detail || "Request failed");
      $("mScore").textContent = `${m.match_score}% match`;
      fillTags($("mMatched"), m.matched_skills);
      fillTags($("mMissing"), m.missing_skills, "miss");
      fillList($("mBullets"), m.bullet_rewrites);
      $("mLetter").textContent = m.cover_letter;
      $("matchOut").hidden = false;
    } catch (e) { $("matchErr").textContent = e.message; }
  })
);
