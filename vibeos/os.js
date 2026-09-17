const pages = [...document.querySelectorAll(".page")];
const dots = [...document.querySelectorAll(".dots button")];
let page = 0;

function show(n) {
  page = (n + pages.length) % pages.length;
  pages.forEach((el, i) => {
    el.hidden = i !== page;
  });
  dots.forEach((el, i) => el.classList.toggle("on", i === page));
}

dots.forEach((el) => el.addEventListener("click", () => show(Number(el.dataset.go))));

let startX = 0;
document.querySelector(".bezel").addEventListener("pointerdown", (e) => {
  startX = e.clientX;
});
document.querySelector(".bezel").addEventListener("pointerup", (e) => {
  const dx = e.clientX - startX;
  if (dx < -24) show(page + 1);
  if (dx > 24) show(page - 1);
});

function pad(n) {
  return String(n).padStart(2, "0");
}

function tickClock() {
  const d = new Date();
  document.getElementById("clock").textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function renderList(el, items, fallback) {
  if (!items || !items.length) {
    el.innerHTML = `<li>${fallback}</li>`;
    return;
  }
  el.innerHTML = items
    .slice(0, 6)
    .map((item) => {
      const name = item.name || item.project || item.title || "agent";
      const st = item.status || item.agent || item.kind || "";
      const cls = /attn|review|fail|block/i.test(st) ? "attn" : /end|done|complete/i.test(st) ? "done" : "";
      return `<li class="${cls}"><em>${st}</em>${name}</li>`;
    })
    .join("");
}

async function poll() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    const s = await res.json();
    document.getElementById("working").textContent = s.working ?? 0;
    document.getElementById("ended").textContent = s.ended ?? 0;
    document.getElementById("attention").textContent = s.attention ?? 0;
    document.querySelector(".bezel").dataset.attn = s.attention > 0 ? "1" : "0";

    const radio = document.getElementById("radio");
    const up = Boolean(s.watch && s.watch.connected);
    const iphone = s.watch && s.watch.bridge === "iphone";
    radio.textContent = up ? "LIVE" : iphone ? "PHONE" : "BT";
    radio.classList.toggle("dead", !up && !iphone);

    renderList(document.getElementById("orca-list"), s.orca?.items?.working || [], "no orca agents");

    document.getElementById("cursor-file").textContent = s.cursor?.running
      ? s.cursor.file_name || "Cursor open"
      : "Cursor idle";
    renderList(document.getElementById("cursor-list"), s.cursor?.agents || [], "no cursor agents");

    const w = s.watch || {};
    document.getElementById("radio-detail").textContent = up
      ? `${w.name || "Live3"}\n${w.address || ""}\n${w.last_push || "no push yet"}`
      : w.error || "searching 41:42:C6:70:B4:41";

    const head = s.watch?.last_push || s.orca?.terminals?.[0]?.title || "vibe coding watch";
    document.getElementById("ticker").textContent = head;
  } catch (err) {
    document.getElementById("ticker").textContent = "bridge offline";
  }
}

async function post(path, body) {
  const ticker = document.getElementById("ticker");
  ticker.textContent = "sending to watch…";
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    ticker.textContent = data.ok ? "watch ping sent — look at wrist" : data.error || "push failed";
  } catch (err) {
    ticker.textContent = "push failed";
  }
}

let busy = false;
document.getElementById("btn-find").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  await post("/api/find", { action: "find" });
  busy = false;
});
document.getElementById("btn-push").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  await post("/api/push", { action: "push", title: "VibeOS", body: "LOOK AT WATCH", alert: true });
  busy = false;
});

tickClock();
setInterval(tickClock, 1000);
poll();
setInterval(poll, 1500);
