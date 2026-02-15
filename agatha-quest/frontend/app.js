const API_BASE = "/api/game";

const locationsEl = document.getElementById("locations");
const suspectsEl = document.getElementById("suspects");
const cluesEl = document.getElementById("clues");
const interrogationsEl = document.getElementById("interrogations");
const caseInfoEl = document.getElementById("case-info");
const statusStripEl = document.getElementById("status-strip");
const verdictEl = document.getElementById("verdict");
const accusedSelectEl = document.getElementById("accused-select");

const locationMap = [
  { id: "study", label: "Study" },
  { id: "victim_room", label: "Victim's Room" },
  { id: "hallway", label: "Main Hallway" },
  { id: "victim_desk", label: "Writing Desk" },
];

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

function renderLocations(clues) {
  const discoveredByLocation = new Set(clues.map((c) => c.location));
  const locationToClueId = {
    study: "poison_vial",
    victim_room: "torn_letter",
    hallway: "muddy_footprints",
    victim_desk: "blackmail_note",
  };
  locationsEl.innerHTML = "";

  locationMap.forEach((location) => {
    const card = document.createElement("div");
    card.className = "card";

    const heading = document.createElement("h3");
    heading.textContent = location.label;
    card.appendChild(heading);

    const summary = document.createElement("p");
    summary.textContent = "Search this location for evidence.";
    card.appendChild(summary);

    const btn = document.createElement("button");
    btn.className = "btn btn-secondary";
    btn.textContent = "Search";
    btn.addEventListener("click", async () => {
      try {
        const clueData = await api(`/clues/${locationToClueId[location.id]}/discover`, { method: "POST" });
        setVerdict(`Clue found: ${clueData.clue.name}`, true);
      } catch (error) {
        setVerdict(error.message);
      }
      await refresh();
    });

    btn.disabled = discoveredByLocation.has(location.id);
    card.appendChild(btn);

    locationsEl.appendChild(card);
  });
}

function renderSuspects(suspects) {
  suspectsEl.innerHTML = "";
  accusedSelectEl.innerHTML = "";

  suspects.forEach((suspect) => {
    const card = document.createElement("div");
    card.className = "card";

    const heading = document.createElement("h3");
    heading.textContent = suspect.name;
    card.appendChild(heading);

    const desc = document.createElement("p");
    desc.textContent = suspect.description;
    card.appendChild(desc);

    const btn = document.createElement("button");
    btn.className = "btn btn-secondary";
    btn.textContent = suspect.interrogated ? "Interrogated" : "Interrogate";
    btn.disabled = suspect.interrogated;
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/interrogate", {
          method: "POST",
          body: JSON.stringify({ suspect_id: suspect.id }),
        });
        setVerdict(`Interrogated ${data.interrogation.suspect_name}`, true);
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
    cluesEl.innerHTML = "<li>No clues discovered yet.</li>";
    return;
  }
  clues.forEach((clue) => {
    const li = document.createElement("li");
    li.textContent = `${clue.name}: ${clue.description}`;
    cluesEl.appendChild(li);
  });
}

function renderInterrogations(interrogations) {
  interrogationsEl.innerHTML = "";
  if (!interrogations.length) {
    interrogationsEl.innerHTML = "<li>No interrogations conducted yet.</li>";
    return;
  }
  interrogations.forEach((note) => {
    const li = document.createElement("li");
    li.textContent = `${note.suspect_name} - Alibi: ${note.alibi}${note.secret ? ` | Secret: ${note.secret}` : ""}`;
    interrogationsEl.appendChild(li);
  });
}

async function refresh() {
  const [state, suspectsData, cluesData, interrogationsData] = await Promise.all([
    api("/state"),
    api("/suspects"),
    api("/clues"),
    api("/interrogations"),
  ]);

  statusStripEl.textContent = `Phase: ${state.phase} | Clues: ${state.clues_discovered_count} | Interrogations: ${state.interrogations_count}`;
  renderSuspects(suspectsData.suspects);
  renderClues(cluesData.clues);
  renderLocations(cluesData.clues);

  renderInterrogations(interrogationsData.interrogations);

  if (state.game_won === true) {
    setVerdict("Case closed. You solved the mystery.", true);
  } else if (state.game_won === false) {
    setVerdict("Wrong suspect. The killer slipped away.", false);
  }
}

async function startNewGame() {
  try {
    const game = await api("/new", { method: "POST" });
    caseInfoEl.textContent = `${game.case_info.victim} was found dead at ${game.case_info.location}. Cause: ${game.case_info.cause_of_death}. Time: ${game.case_info.time_of_death}.`;
    setVerdict("Investigation started.", true);
    await refresh();
  } catch (error) {
    setVerdict(error.message);
  }
}

document.getElementById("new-game").addEventListener("click", startNewGame);
document.getElementById("accuse-btn").addEventListener("click", async () => {
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
});

startNewGame();
