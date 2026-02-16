const API_BASE = "/api/game";

const locationsEl = document.getElementById("locations");
const suspectsEl = document.getElementById("suspects");
const cluesEl = document.getElementById("clues");
const interrogationsEl = document.getElementById("interrogations");
const caseInfoEl = document.getElementById("case-info");
const statusStripEl = document.getElementById("status-strip");
const verdictEl = document.getElementById("verdict");
const accusedSelectEl = document.getElementById("accused-select");
const pressureBarEl = document.getElementById("pressure-bar");
const pressureLabelEl = document.getElementById("pressure-label");
const pressureContainerEl = document.getElementById("pressure-container");

let currentPhase = "investigation";

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Request failed");
  return data;
}

function setVerdict(message, ok = false) {
  verdictEl.textContent = message;
  verdictEl.className = `verdict ${ok ? "success" : "fail"}`;
}

function renderPressure(remaining, max, warning) {
  const pct = Math.max(0, (remaining / max) * 100);
  pressureBarEl.style.width = pct + "%";

  if (remaining <= 0) {
    pressureBarEl.className = "pressure-fill expired";
    pressureLabelEl.textContent = "Time expired!";
  } else if (warning) {
    pressureBarEl.className = "pressure-fill warning";
    pressureLabelEl.textContent = `${remaining} action${remaining !== 1 ? "s" : ""} remaining!`;
  } else {
    pressureBarEl.className = "pressure-fill";
    pressureLabelEl.textContent = `${remaining} / ${max} actions`;
  }
}

function renderLocations(locations, gameOver) {
  locationsEl.innerHTML = "";

  locations.forEach((loc) => {
    const card = document.createElement("div");
    card.className = "card" + (loc.visited ? " visited" : "") + (loc.has_clues ? "" : " no-clues");

    const heading = document.createElement("h3");
    heading.textContent = loc.name;
    card.appendChild(heading);

    const desc = document.createElement("p");
    desc.className = "loc-desc";
    desc.textContent = loc.description || "Search this location for evidence.";
    card.appendChild(desc);

    if (loc.has_clues) {
      const badge = document.createElement("span");
      badge.className = "badge clue-badge";
      badge.textContent = "Evidence";
      card.appendChild(badge);
    }

    if (loc.visited) {
      const badge = document.createElement("span");
      badge.className = "badge visited-badge";
      badge.textContent = "Searched";
      card.appendChild(badge);
    }

    const btn = document.createElement("button");
    btn.className = "btn btn-secondary";
    btn.textContent = loc.visited ? "Search again" : "Search";
    btn.disabled = gameOver;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Searching...";
      try {
        const data = await api(`/locations/${loc.id}/search`, { method: "POST" });
        if (data.clues_found && data.clues_found.length > 0) {
          const names = data.clues_found.map((c) => c.name).join(", ");
          setVerdict(`Found: ${names}`, true);
        } else {
          setVerdict(data.message || "Nothing new here.");
        }
        if (data.pressure_warning) {
          setVerdict(data.pressure_warning);
        }
      } catch (error) {
        setVerdict(error.message);
      }
      await refresh();
    });

    card.appendChild(btn);
    locationsEl.appendChild(card);
  });
}

function renderSuspects(suspects, gameOver) {
  suspectsEl.innerHTML = "";
  accusedSelectEl.innerHTML = "";

  suspects.forEach((suspect) => {
    const card = document.createElement("div");
    card.className = "card" + (suspect.interrogated ? " interrogated" : "");

    const heading = document.createElement("h3");
    heading.textContent = suspect.name;
    card.appendChild(heading);

    const desc = document.createElement("p");
    desc.textContent = suspect.description;
    card.appendChild(desc);

    if (suspect.interrogated) {
      const badge = document.createElement("span");
      badge.className = "badge interrogated-badge";
      badge.textContent = "Interrogated";
      card.appendChild(badge);
    }

    const btn = document.createElement("button");
    btn.className = "btn btn-secondary";
    btn.textContent = suspect.interrogated ? "Already questioned" : "Interrogate";
    btn.disabled = suspect.interrogated || gameOver;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Questioning...";
      try {
        const data = await api("/interrogate", {
          method: "POST",
          body: JSON.stringify({ suspect_id: suspect.id }),
        });
        setVerdict(`Interrogated ${data.interrogation.suspect_name}`, true);
        if (data.pressure_warning) {
          setVerdict(data.pressure_warning);
        }
      } catch (error) {
        setVerdict(error.message);
      }
      await refresh();
    });

    card.appendChild(btn);
    suspectsEl.appendChild(card);

    const option = document.createElement("option");
    option.value = suspect.id;
    option.textContent = suspect.name;
    accusedSelectEl.appendChild(option);
  });
}

function renderClues(clues) {
  cluesEl.innerHTML = "";
  if (!clues.length) {
    cluesEl.innerHTML = '<li class="empty">No clues discovered yet. Search locations to find evidence.</li>';
    return;
  }
  clues.forEach((clue) => {
    const li = document.createElement("li");
    const strong = document.createElement("strong");
    strong.textContent = clue.name;
    li.appendChild(strong);
    li.appendChild(document.createTextNode(": " + clue.description));
    li.className = "clue-item";
    cluesEl.appendChild(li);
  });
}

function renderInterrogations(interrogations) {
  interrogationsEl.innerHTML = "";
  if (!interrogations.length) {
    interrogationsEl.innerHTML = '<li class="empty">No interrogations conducted yet.</li>';
    return;
  }
  interrogations.forEach((note) => {
    const li = document.createElement("li");
    li.className = "interrogation-item";
    const name = document.createElement("strong");
    name.textContent = note.suspect_name;
    li.appendChild(name);
    li.appendChild(document.createTextNode(" \u2014 Alibi: " + note.alibi));
    if (note.secret) {
      const secret = document.createElement("span");
      secret.className = "secret-text";
      secret.textContent = " | Secret: " + note.secret;
      li.appendChild(secret);
    }
    cluesEl.parentNode && interrogationsEl.appendChild(li);
  });
}

function updatePhaseUI(state) {
  currentPhase = state.phase;
  const accusationPanel = document.querySelector(".accusation-panel");
  const accuseBtn = document.getElementById("accuse-btn");

  // Phase indicator
  let phaseLabel = state.phase.charAt(0).toUpperCase() + state.phase.slice(1);
  let phaseIcon = "";
  if (state.phase === "investigation") phaseIcon = "\ud83d\udd0d ";
  else if (state.phase === "accusation") phaseIcon = "\u2696\ufe0f ";
  else if (state.phase === "complete") phaseIcon = state.game_won ? "\ud83c\udf89 " : "\ud83d\udea8 ";

  statusStripEl.innerHTML = `
    <span class="phase-text">${phaseIcon}${phaseLabel}</span>
    <span class="stat">Clues: ${state.clues_discovered_count}</span>
    <span class="stat">Interrogations: ${state.interrogations_count}</span>
    <span class="stat">Locations: ${state.locations_visited_count}</span>
  `;

  // Accusation panel visibility
  if (state.phase === "accusation" || state.phase === "complete") {
    accusationPanel.classList.add("visible");
  } else {
    accusationPanel.classList.remove("visible");
  }

  accuseBtn.disabled = state.phase !== "accusation";

  // Game over overlay
  if (state.game_won === true) {
    setVerdict("Case solved! Justice prevails at Blackwood Manor.", true);
    document.body.classList.add("game-over", "game-won");
  } else if (state.game_won === false) {
    setVerdict("The killer escapes into the night... Case unsolved.", false);
    document.body.classList.add("game-over", "game-lost");
  } else {
    document.body.classList.remove("game-over", "game-won", "game-lost");
  }
}

async function refresh() {
  try {
    const [state, locationsData, suspectsData, cluesData, interrogationsData] = await Promise.all([
      api("/state"),
      api("/locations"),
      api("/suspects"),
      api("/clues"),
      api("/interrogations"),
    ]);

    const gameOver = state.phase === "complete";

    renderPressure(state.pressure_remaining, state.pressure_max, state.pressure_warning);
    renderLocations(locationsData.locations, gameOver);
    renderSuspects(suspectsData.suspects, gameOver);
    renderClues(cluesData.clues);
    renderInterrogations(interrogationsData.interrogations);
    updatePhaseUI(state);
  } catch (error) {
    setVerdict("Error loading game state: " + error.message);
  }
}

async function startNewGame() {
  document.body.classList.remove("game-over", "game-won", "game-lost");
  try {
    const game = await api("/new", { method: "POST" });
    caseInfoEl.innerHTML = `
      <div class="case-detail"><strong>Victim:</strong> ${game.case_info.victim}</div>
      <div class="case-detail"><strong>Location:</strong> ${game.case_info.location}</div>
      <div class="case-detail"><strong>Cause:</strong> ${game.case_info.cause_of_death}</div>
      <div class="case-detail"><strong>Time:</strong> ${game.case_info.time_of_death}</div>
    `;
    setVerdict("A new investigation begins...", true);
    await refresh();
  } catch (error) {
    setVerdict(error.message);
  }
}

document.getElementById("new-game").addEventListener("click", startNewGame);
document.getElementById("accuse-btn").addEventListener("click", async () => {
  const accuseBtn = document.getElementById("accuse-btn");
  accuseBtn.disabled = true;
  accuseBtn.textContent = "Deliberating...";
  try {
    const result = await api("/accuse", {
      method: "POST",
      body: JSON.stringify({ suspect_id: accusedSelectEl.value }),
    });
    setVerdict(result.message, result.correct);
    await refresh();
  } catch (error) {
    setVerdict(error.message);
  }
  accuseBtn.textContent = "Accuse";
});

startNewGame();
