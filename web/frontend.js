const LOCAL_MERGE_MAX_BYTES = 80 * 1024 * 1024;
const LOCAL_MERGE_STEP_SECONDS = 5;

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
let pendingLocalMerge = null;

function show(el) {
  el.classList.remove("hidden");
}

function hide(el) {
  el.classList.add("hidden");
}

function setLoading(
  active,
  title = "Preparando mídia",
  message = "Analisando formatos disponíveis…",
) {
  submitButton.disabled = active;
  submitLabel.textContent = active ? "Preparando…" : "Preparar download";
  statusTitle.textContent = title;
  statusMessage.textContent = message;
  active ? show(statusCard) : hide(statusCard);
}

function setProcessingStatus(title, message) {
  statusTitle.textContent = title;
  statusMessage.textContent = message;
  show(statusCard);
}

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  if (!seconds) return "";

  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;

  return h
    ? [h, m, s]
        .map((part, index) =>
          index === 0 ? String(part) : String(part).padStart(2, "0"),
        )
        .join(":")
    : [m, s].map((part) => String(part).padStart(2, "0")).join(":");
}

function safeFilename(title, extension) {
  const cleaned = String(title || "download")
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_")
    .trim()
    .slice(0, 120);

  return `${cleaned || "download"}.${extension}`;
}

async function jsonRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch (_) {
    // A mensagem HTTP abaixo continua válida quando não há JSON.
  }

  if (!response.ok) {
    throw new Error(
      payload.detail || "O servidor não conseguiu concluir a solicitação.",
    );
  }

  return payload;
}

function estimatedMergeBytes(plan) {
  const videoSize = Number(plan?.sources?.video?.filesize);
  const audioSize = Number(plan?.sources?.audio?.filesize);

  if (!Number.isFinite(videoSize) || !Number.isFinite(audioSize)) {
    return null;
  }

  if (videoSize <= 0 || audioSize <= 0) {
    return null;
  }

  return videoSize + audioSize;
}

function browserMergeEligible(plan) {
  if (plan?.strategy !== "browser-merge") return false;
  if (!plan?.sources?.video?.relay_url || !plan?.sources?.audio?.relay_url) {
    return false;
  }

  const videoExt = String(plan.sources.video.ext || "").toLowerCase();
  const audioExt = String(plan.sources.audio.ext || "").toLowerCase();

  if (videoExt !== "mp4" || !["m4a", "mp4"].includes(audioExt)) {
    return false;
  }

  const estimatedBytes = estimatedMergeBytes(plan);
  return estimatedBytes !== null && estimatedBytes <= LOCAL_MERGE_MAX_BYTES;
}

function routeDescription(plan) {
  if (mediaType === "audio") {
    return "Conversão MP3 em streaming";
  }

  if (plan.strategy === "browser-merge") {
    if (browserMergeEligible(plan)) {
      return "Alta qualidade • áudio e vídeo serão unidos neste dispositivo";
    }

    return plan.fallback?.available
      ? "Alta qualidade • processamento compatível no servidor"
      : "Vídeo e áudio em faixas separadas";
  }

  if (plan.strategy === "direct-first") {
    return "Rota direta disponível • servidor como fallback";
  }

  return "Modo compatível via servidor";
}

function triggerBlobDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

function triggerServerFallback(url) {
  if (!url) return;

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

async function mergeInBrowser(plan, title) {
  const {
    ALL_FORMATS,
    BufferTarget,
    Conversion,
    Input,
    Mp4OutputFormat,
    Output,
    UrlSource,
  } = await import("mediabunny");

  const videoInput = new Input({
    formats: ALL_FORMATS,
    source: new UrlSource(plan.sources.video.relay_url, {
      maxCacheSize: 8 * 1024 * 1024,
      parallelism: 2,
    }),
  });

  const audioInput = new Input({
    formats: ALL_FORMATS,
    source: new UrlSource(plan.sources.audio.relay_url, {
      maxCacheSize: 4 * 1024 * 1024,
      parallelism: 2,
    }),
  });

  const target = new BufferTarget();
  const output = new Output({
    format: new Mp4OutputFormat(),
    target,
  });

  const videoConversion = await Conversion.init({
    input: videoInput,
    output,
    composable: true,
    audio: { discard: true },
    showWarnings: false,
  });

  const audioConversion = await Conversion.init({
    input: audioInput,
    output,
    composable: true,
    video: { discard: true },
    showWarnings: false,
  });

  if (!videoConversion.isValid || !audioConversion.isValid) {
    throw new Error("O navegador não conseguiu preparar o remux desta mídia.");
  }

  let videoProgress = 0;
  let audioProgress = 0;

  const updateProgress = () => {
    const average = Math.max(
      0,
      Math.min(1, (videoProgress + audioProgress) / 2),
    );
    const percent = Math.round(average * 100);

    setProcessingStatus(
      "Processando no dispositivo",
      `Baixando e unindo áudio + vídeo… ${percent}%`,
    );
  };

  videoConversion.onProgress = (value) => {
    videoProgress = Number.isFinite(value) ? value : videoProgress;
    updateProgress();
  };

  audioConversion.onProgress = (value) => {
    audioProgress = Number.isFinite(value) ? value : audioProgress;
    updateProgress();
  };

  await output.start();

  for (
    let until = LOCAL_MERGE_STEP_SECONDS;
    ;
    until += LOCAL_MERGE_STEP_SECONDS
  ) {
    const tasks = [];

    if (videoConversion.state !== "done") {
      tasks.push(videoConversion.execute({ until }));
    }

    if (audioConversion.state !== "done") {
      tasks.push(audioConversion.execute({ until }));
    }

    if (!tasks.length) break;

    await Promise.all(tasks);

    if (
      videoConversion.state === "done" &&
      audioConversion.state === "done"
    ) {
      break;
    }
  }

  await output.finalize();

  if (!target.buffer) {
    throw new Error("O navegador não gerou o arquivo final.");
  }

  const blob = new Blob([target.buffer], { type: "video/mp4" });
  triggerBlobDownload(blob, safeFilename(title, "mp4"));
}

function configureDownload(plan, resolved) {
  pendingLocalMerge = null;
  fallback.classList.add("hidden");
  fallback.removeAttribute("href");
  primary.removeAttribute("href");

  if (mediaType === "audio" && plan.conversion?.mp3_url) {
    primary.href = plan.conversion.mp3_url;
    primary.textContent = "Baixar MP3 ↓";
    resultBadge.textContent = "MP3";
    return;
  }

  if (plan.strategy === "browser-merge") {
    if (!plan.fallback?.available || !plan.fallback?.url) {
      throw new Error(
        "Este formato exige processamento que ainda não está disponível para esta combinação.",
      );
    }

    resultBadge.textContent = plan.quality ? `${plan.quality}p` : "Vídeo";

    if (browserMergeEligible(plan)) {
      pendingLocalMerge = {
        plan,
        title: resolved.title || "video",
      };
      primary.href = "#";
      primary.textContent = "Baixar e juntar neste dispositivo ↓";

      fallback.href = plan.fallback.url;
      fallback.textContent = "Processar no servidor";
      fallback.classList.remove("hidden");
      return;
    }

    primary.href = plan.fallback.url;
    primary.textContent = "Baixar vídeo ↓";
    return;
  }

  const source = plan.source;
  if (!source) {
    throw new Error("O servidor não retornou uma fonte compatível.");
  }

  primary.href = source.direct_url || source.relay_url;
  primary.textContent =
    mediaType === "video" ? "Baixar vídeo ↓" : "Baixar arquivo ↓";
  resultBadge.textContent = plan.quality ? `${plan.quality}p` : "Pronto";

  if (source.direct_url && source.relay_url) {
    fallback.href = source.relay_url;
    fallback.textContent = "Usar modo compatível";
    fallback.classList.remove("hidden");
  }
}

primary.addEventListener("click", async (event) => {
  if (!pendingLocalMerge) return;

  event.preventDefault();
  hide(errorCard);

  const operation = pendingLocalMerge;
  const serverFallback = operation.plan.fallback?.url;

  primary.setAttribute("aria-disabled", "true");
  primary.style.pointerEvents = "none";

  try {
    setProcessingStatus(
      "Processando no dispositivo",
      "Preparando os streams de áudio e vídeo…",
    );

    await mergeInBrowser(operation.plan, operation.title);

    setProcessingStatus(
      "Download preparado",
      "O arquivo foi unido no seu dispositivo, sem usar FFmpeg na VPS.",
    );

    window.setTimeout(() => hide(statusCard), 4_000);
  } catch (error) {
    setProcessingStatus(
      "Usando modo compatível",
      "O processamento local não funcionou. Transferindo a tarefa para o servidor…",
    );

    if (serverFallback) {
      window.setTimeout(() => {
        triggerServerFallback(serverFallback);
        hide(statusCard);
      }, 350);
    } else {
      hide(statusCard);
      errorMessage.textContent =
        error?.message || "Falha no processamento local.";
      show(errorCard);
    }
  } finally {
    primary.removeAttribute("aria-disabled");
    primary.style.pointerEvents = "";
  }
});

segments.forEach((button) => {
  button.addEventListener("click", () => {
    mediaType = button.dataset.format;
    segments.forEach((item) =>
      item.classList.toggle("active", item === button),
    );
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hide(errorCard);
  hide(result);
  pendingLocalMerge = null;

  const url = urlInput.value.trim();
  if (!url) return;

  try {
    setLoading(true);

    const resolved = await jsonRequest("/api/v1/resolve", {
      method: "POST",
      body: JSON.stringify({ url }),
    });

    setLoading(
      true,
      "Escolhendo a melhor rota",
      "Comparando qualidade, compatibilidade e custo de processamento…",
    );

    const requestedQuality =
      mediaType === "video" && quality.value ? Number(quality.value) : null;

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

    configureDownload(plan, resolved);

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
  window.addEventListener("load", () =>
    navigator.serviceWorker.register("/sw.js").catch(() => {}),
  );
}
