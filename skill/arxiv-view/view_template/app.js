const FAVORITES_KEY = "followhub:arxiv-view:favorites";

let model = null;
let favorites = new Set();

function loadFavorites() {
  try {
    const raw = window.localStorage.getItem(FAVORITES_KEY);
    const values = raw ? JSON.parse(raw) : [];
    favorites = new Set(Array.isArray(values) ? values.map(String) : []);
  } catch (error) {
    console.warn("Failed to load favorites", error);
    favorites = new Set();
  }
}

function saveFavorites() {
  window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(Array.from(favorites)));
}

function toggleFavorite(arxivId) {
  const key = String(arxivId);
  if (favorites.has(key)) {
    favorites.delete(key);
  } else {
    favorites.add(key);
  }
  saveFavorites();
}

function normalizedText(item) {
  return [
    item.arxiv_id,
    item.title,
    item.one_liner_zh,
    item.summary_cn,
    item.abstract_en,
    (item.authors || []).join(" "),
    item.first_affiliation || "",
    (item.categories || []).join(" "),
    (item.matched_keywords || []).join(" "),
    (item.source_day || "")
  ].join(" ").toLowerCase();
}

function getFilters() {
  return {
    query: document.getElementById("searchInput").value.trim().toLowerCase(),
    category: document.getElementById("categoryFilter").value,
    day: document.getElementById("dayFilter").value,
    favoriteOnly: document.getElementById("favoriteOnly").checked
  };
}

function filterItems(items) {
  const filters = getFilters();
  return items.filter((item) => {
    if (filters.query && !normalizedText(item).includes(filters.query)) {
      return false;
    }
    if (filters.category && !(item.categories || []).includes(filters.category)) {
      return false;
    }
    if (filters.day && item.source_day !== filters.day) {
      return false;
    }
    if (filters.favoriteOnly && !favorites.has(String(item.arxiv_id))) {
      return false;
    }
    return true;
  });
}

function fillSelect(selectId, values, placeholder) {
  const select = document.getElementById(selectId);
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = placeholder;
  select.appendChild(defaultOption);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

function linkHtml(item) {
  const links = [];
  if (item.html_url) {
    links.push(`<a href="${item.html_url}" target="_blank" rel="noreferrer">Abs</a>`);
  }
  if (item.pdf_url) {
    links.push(`<a href="${item.pdf_url}" target="_blank" rel="noreferrer">PDF</a>`);
  }
  (item.code_urls || []).slice(0, 2).forEach((url, index) => {
    links.push(`<a href="${url}" target="_blank" rel="noreferrer">Code ${index + 1}</a>`);
  });
  (item.project_urls || []).slice(0, 2).forEach((url, index) => {
    links.push(`<a href="${url}" target="_blank" rel="noreferrer">Project ${index + 1}</a>`);
  });
  return links.join("");
}

function tagHtml(values) {
  return (values || [])
    .map((value) => `<span class="tag">${value}</span>`)
    .join("");
}

function buildCard(item) {
  const template = document.getElementById("cardTemplate");
  const node = template.content.cloneNode(true);

  node.querySelector(".source-day").textContent =
    item.source_day ? `${item.source_mode} / ${item.source_day}` : item.source_mode;
  node.querySelector(".card-title").textContent = item.title || item.arxiv_id;
  node.querySelector(".hotness").textContent =
    item.hot_score ? `Heat ${item.hot_score}` : "";
  node.querySelector(".hotness").style.display = item.hot_score ? "inline-flex" : "none";
  node.querySelector(".overallScore").textContent =
    item.overall_score ? `Score ${item.overall_score}` : "";
  node.querySelector(".overallScore").style.display = item.overall_score ? "inline-flex" : "none";
  node.querySelector(".authors").textContent =
    (item.authors || []).length ? `Authors: ${(item.authors || []).join(", ")}` : "Authors: -";
  node.querySelector(".dates").textContent =
    `Published: ${item.published || "-"} | Updated: ${item.updated || "-"}`;
  node.querySelector(".firstAffiliation").textContent =
    `First affiliation: ${item.first_affiliation || "—"}`;
  node.querySelector(".categories").innerHTML = tagHtml(item.categories || []);
  node.querySelector(".matched-keywords").innerHTML = tagHtml(item.matched_keywords || []);
  node.querySelector(".one-liner").textContent = item.one_liner_zh || "暂无一句话总结";
  node.querySelector(".summary-cn").textContent = item.summary_cn || "暂无中文总结";
  node.querySelector(".abstract-en").textContent = item.abstract_en || "No English abstract available.";
  node.querySelector(".links").innerHTML = linkHtml(item);

  const favoriteButton = node.querySelector(".favorite-toggle");
  const syncFavoriteState = () => {
    const active = favorites.has(String(item.arxiv_id));
    favoriteButton.classList.toggle("active", active);
    favoriteButton.textContent = active ? "★" : "☆";
  };
  favoriteButton.addEventListener("click", () => {
    toggleFavorite(item.arxiv_id);
    syncFavoriteState();
    render();
  });
  syncFavoriteState();

  return node;
}

function groupItems(items) {
  if (model.mode !== "backfill") {
    return [{ label: "", items }];
  }

  const groups = new Map();
  items.forEach((item) => {
    const key = item.source_day || "unknown";
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key).push(item);
  });

  return Array.from(groups.entries())
    .sort((a, b) => a[0] < b[0] ? 1 : -1)
    .map(([label, groupedItems]) => ({ label, items: groupedItems }));
}

function renderEmpty(message) {
  const cards = document.getElementById("cards");
  cards.innerHTML = `<div class="empty">${message}</div>`;
}

function render() {
  const cards = document.getElementById("cards");
  const filtered = filterItems(model.items || []);
  document.getElementById("summaryText").textContent =
    `${model.meta.item_count} total item(s), ${favorites.size} favorite(s), ${filtered.length} visible`;

  if (!filtered.length) {
    renderEmpty("No papers match the current filters.");
    return;
  }

  cards.innerHTML = "";
  groupItems(filtered).forEach((group) => {
    if (group.label) {
      const section = document.createElement("section");
      section.className = "day-group";
      section.innerHTML = `<h2 class="day-heading">${group.label}</h2>`;
      group.items.forEach((item) => section.appendChild(buildCard(item)));
      cards.appendChild(section);
    } else {
      group.items.forEach((item) => cards.appendChild(buildCard(item)));
    }
  });
}

async function copyFavorites() {
  const ids = Array.from(favorites);
  const feedback = document.getElementById("copyFeedback");
  if (!ids.length) {
    feedback.textContent = "No favorites selected.";
    return;
  }
  await navigator.clipboard.writeText(ids.join("\n"));
  feedback.textContent = `Copied ${ids.length} arXiv ID(s).`;
}

function bindControls() {
  ["searchInput", "categoryFilter", "dayFilter", "favoriteOnly"].forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
    document.getElementById(id).addEventListener("change", render);
  });
  document.getElementById("copyFavorites").addEventListener("click", () => {
    copyFavorites().catch((error) => {
      document.getElementById("copyFeedback").textContent =
        `Copy failed: ${error.message || error}`;
    });
  });
}

async function init() {
  const response = await fetch("data.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load data.json: HTTP ${response.status}`);
  }

  model = await response.json();
  loadFavorites();
  document.title = model.title;
  document.getElementById("pageTitle").textContent = model.title;
  document.getElementById("pageSubtitle").textContent = model.subtitle;

  fillSelect("categoryFilter", model.meta.categories || [], "All categories");
  fillSelect("dayFilter", model.meta.days || [], "All days");
  bindControls();
  render();
}

init().catch((error) => {
  document.getElementById("pageTitle").textContent = "arxiv-view failed to load";
  document.getElementById("pageSubtitle").textContent = error.message || String(error);
  renderEmpty("Viewer initialization failed.");
});
