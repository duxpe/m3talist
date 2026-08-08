const BAR_WIDTH = 20;

function crtToggle() {
  const stored = localStorage.getItem("crt");
  if (stored === "off") document.documentElement.classList.add("no-crt");
  const button = document.getElementById("crt");
  if (!button) return;
  const label = () => {
    button.textContent =
      "CRT: " + (document.documentElement.classList.contains("no-crt") ? "OFF" : "ON");
  };
  label();
  button.addEventListener("click", () => {
    const off = document.documentElement.classList.toggle("no-crt");
    localStorage.setItem("crt", off ? "off" : "on");
    label();
  });
}

function asciiBar(done, total) {
  if (!total) return "[" + "░".repeat(BAR_WIDTH) + "]   0%";
  const ratio = Math.min(done / total, 1);
  const filled = Math.round(ratio * BAR_WIDTH);
  const pct = String(Math.round(ratio * 100)).padStart(3, " ");
  return "[" + "█".repeat(filled) + "░".repeat(BAR_WIDTH - filled) + "] " + pct + "%";
}

function classify(line) {
  if (line.startsWith("error")) return "err";
  if (line.startsWith("skipped") || line.startsWith("needs review")) return "warn";
  return "";
}

function buildStream() {
  const log = document.getElementById("log");
  if (!log) return;
  const bar = document.getElementById("bar");
  const counters = {
    done: document.getElementById("c-done"),
    total: document.getElementById("c-total"),
    failed: document.getElementById("c-failed"),
    state: document.getElementById("c-state"),
    summary: document.getElementById("c-summary"),
  };
  const source = new EventSource("/stream");
  let finished = false;

  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.log.length) log.querySelector(".placeholder")?.remove();
    for (const line of data.log) {
      const row = document.createElement("div");
      row.className = classify(line);
      row.textContent = line;
      log.appendChild(row);
    }
    if (data.log.length) log.scrollTop = log.scrollHeight;
    if (bar) bar.textContent = asciiBar(data.done, data.total);
    counters.done.textContent = data.done;
    counters.total.textContent = data.total;
    counters.failed.textContent = data.failed;
    counters.state.textContent = data.running ? data.name : data.summary ? "DONE" : "IDLE";
    counters.state.className = "v " + (data.running ? "ok" : "note");
    counters.summary.textContent = data.summary;
    finished = !data.running;
  };

  source.addEventListener("end", () => source.close());
  // A transient network blip should let EventSource's built-in reconnect do
  // its job. Only close for good once we know the job itself is done.
  source.onerror = () => {
    if (finished) source.close();
  };
}

function rowNavigation() {
  const rows = Array.from(document.querySelectorAll("tbody tr[data-href]"));
  if (!rows.length) return;
  let index = -1;
  const select = (next) => {
    if (index >= 0) rows[index].classList.remove("selected");
    index = Math.max(0, Math.min(next, rows.length - 1));
    rows[index].classList.add("selected");
    rows[index].scrollIntoView({ block: "nearest" });
  };
  rows.forEach((row, position) => {
    row.addEventListener("click", () => {
      window.location = row.dataset.href;
    });
    row.addEventListener("mouseenter", () => select(position));
  });
  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea")) return;
    if (event.key === "ArrowDown" || event.key === "j") select(index + 1);
    else if (event.key === "ArrowUp" || event.key === "k") select(index - 1);
    else if (event.key === "g") select(0);
    else if (event.key === "G") select(rows.length - 1);
    else if (event.key === "Enter" && index >= 0) window.location = rows[index].dataset.href;
    else return;
    event.preventDefault();
  });
}

function filterRows() {
  const input = document.getElementById("filter");
  if (!input) return;
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !event.target.matches("input")) {
      event.preventDefault();
      input.focus();
      input.select();
    }
    if (event.key === "Escape" && event.target === input) input.blur();
  });
  input.addEventListener("input", () => {
    const needle = input.value.toLowerCase();
    for (const row of document.querySelectorAll("tbody tr")) {
      row.hidden = needle && !row.textContent.toLowerCase().includes(needle);
    }
  });
}

function trackReorder() {
  const list = document.getElementById("tracklist");
  if (!list) return;
  const field = document.getElementById("track_ids");
  let selected = null;

  const sync = () => {
    field.value = Array.from(list.querySelectorAll("tr")).map((r) => r.dataset.id).join(",");
    list.querySelectorAll("tr").forEach((row, position) => {
      row.querySelector(".position").textContent = String(position + 1).padStart(2, "0");
    });
  };

  const select = (row) => {
    selected?.classList.remove("selected");
    selected = row;
    selected?.classList.add("selected");
  };

  const move = (row, direction) => {
    const sibling = direction === "up" ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    if (direction === "up") list.insertBefore(row, sibling);
    else list.insertBefore(sibling, row);
    sync();
  };

  list.addEventListener("click", (event) => {
    const row = event.target.closest("tr");
    if (!row) return;
    const button = event.target.closest("button[data-move]");
    if (button) move(row, button.dataset.move);
    select(row);
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea") || !selected) return;
    if (event.key === "[") move(selected, "up");
    else if (event.key === "]") move(selected, "down");
    else return;
    event.preventDefault();
  });

  sync();
}

function helpOverlay() {
  const dialog = document.getElementById("help");
  if (!dialog) return;
  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea")) return;
    if (event.key === "?") dialog.showModal();
  });
  dialog.addEventListener("click", () => dialog.close());
}

function shortcuts() {
  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea") || event.metaKey || event.ctrlKey) return;
    const go = { l: "/", b: "/build", d: "/dupes", c: "/calibrate" }[event.key];
    if (go) {
      window.location = go;
      return;
    }
    if (event.key === "s") {
      const scanForm = document.querySelector('form[action="/scan"]');
      if (scanForm) {
        event.preventDefault();
        scanForm.requestSubmit();
      }
    }
  });
}

crtToggle();
buildStream();
rowNavigation();
filterRows();
trackReorder();
helpOverlay();
shortcuts();
