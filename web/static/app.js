const form = document.querySelector("#download-form");
const urlInput = document.querySelector("#media-url");
const pasteButton = document.querySelector("#paste-button");
const submitButton = document.querySelector("#submit-button");
const submitLabel = document.querySelector("#submit-label");
const quality = document.querySelector("#quality");
const qualityWrap = document.querySelector("#quality-wrap");
const segments = [...document.querySelectorAll(".segment")];

const result = document.querySelector("#result");
const statusCard = document.querySelector("#status-card");
const statusTitle = document.querySelector("#status-title");
const statusMessage = document.querySelector("#status-message");
const errorCard = document.querySelector("#error-card");
const errorMessage = document.querySelector("#error-message");
const thumbnail = document.querySelector("#thumbnail");
const duration = document.querySelector("#duration");
const mediaTitle = document.querySelector("#media-title");
const routeLabel = document.querySelector("#route-label");
const resultBadge = document.querySelector("#result-badge");
const primary = document.querySelector("#download-primary");
const fallback = document.querySelector("#download-fallback");

let mediaType = "video";

function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

function setLoading(active, title = "Preparando mídia", message = "Analisando formatos disponíveis…") {
  submitButton.disabled = active;
  submitLabel.textContent = active ? "Preparando…" : "Preparar download";
  statusTitle.textContent = title;
  statusMessage.textContent = message;
  active ? show(statusCard) : hide(statusCard);
}

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h
    ? [h, m, s].map((part, i) => i === 0 ? String(part) : String(part).padStart(2, "0")).join(":")
    : [m, s].map(part => String(part).padStart(2, "0")).join(":");
}

async function jsonRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  let payload = {};
  try { payload = await response.json(); } catch (_) {}

  if (!response.ok) {
    throw new Error(payload.detail || "O servidor não conseguiu concluir a solicitação.");
  }
  return payload;
}

function routeDescription(plan) {
  if (mediaType === "audio") return "Conversão MP3 em streaming";
  if (plan.strategy === "browser-merge") {
    return plan.fallback?.available
      ? "Vídeo em alta qualidade • merge otimizado no servidor"
      : "Vídeo e áudio em faixas separadas";
  }
  if (plan.strategy === "direct-first") return "Rota direta disponível • servidor como fallback";
  return "Modo compatível via servidor";
}

function configureDownload(plan) {
  fallback.classList.add("hidden");
  fallback.removeAttribute("href");

  if (mediaType === "audio" && plan.conversion?.mp3_url) {
    primary.href = plan.conversion.mp3_url;
    primary.textContent = "Baixar MP3 ↓";
    resultBadge.textContent = "MP3";
    return;
  }

  if (plan.strategy === "browser-merge") {
    if (!plan.fallback?.available || !plan.fallback?.url) {
      throw new Error("Este formato exige processamento que ainda não está disponível para esta combinação.");
    }
    primary.href = plan.fallback.url;
    primary.textContent = "Baixar vídeo ↓";
    resultBadge.textContent = plan.quality ? `${plan.quality}p` : "Vídeo";
    return;
  }

  const source = plan.source;
  if (!source) throw new Error("O servidor não retornou uma fonte compatível.");

  primary.href = source.direct_url || source.relay_url;
  primary.textContent = mediaType === "video" ? "Baixar vídeo ↓" : "Baixar arquivo ↓";
  resultBadge.textContent = plan.quality ? `${plan.quality}p` : "Pronto";

  if (source.direct_url && source.relay_url) {
    fallback.href = source.relay_url;
    fallback.textContent = "Usar modo compatível";
    fallback.classList.remove("hidden");
  }
}

segments.forEach(button => {
  button.addEventListener("click", () => {
    mediaType = button.dataset.format;
    segments.forEach(item => item.classList.toggle("active", item === button));
    qualityWrap.classList.toggle("hidden", mediaType === "audio");
  });
});

pasteButton.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      urlInput.value = text.trim();
      urlInput.focus();
    }
  } catch (_) {
    urlInput.focus();
  }
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  hide(errorCard);
  hide(result);

  const url = urlInput.value.trim();
  if (!url) return;

  try {
    setLoading(true);

    const resolved = await jsonRequest("/api/v1/resolve", {
      method: "POST",
      body: JSON.stringify({ url }),
    });

    setLoading(true, "Escolhendo a melhor rota", "Comparando qualidade, compatibilidade e custo de processamento…");

    const requestedQuality = mediaType === "video" && quality.value
      ? Number(quality.value)
      : null;

    const plan = await jsonRequest("/api/v1/plan", {
      method: "POST",
      body: JSON.stringify({
        session_id: resolved.session_id,
        media_type: mediaType,
        quality: requestedQuality,
      }),
    });

    thumbnail.src = resolved.thumbnail || "";
    thumbnail.hidden = !resolved.thumbnail;
    mediaTitle.textContent = resolved.title || "Mídia pronta";
    duration.textContent = formatDuration(resolved.duration);
    routeLabel.textContent = routeDescription(plan);

    configureDownload(plan);

    setLoading(false);
    show(result);
    result.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    setLoading(false);
    errorMessage.textContent = error?.message || "Erro inesperado.";
    show(errorCard);
    errorCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
