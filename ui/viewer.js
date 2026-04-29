// ui/viewer.js

// Keep dynamic host detection
const backendHost = `${window.location.hostname}:8000`;
const backendBaseURL = `http://${backendHost}`;

const statusSpan = document.getElementById('status');
const progressBar = document.getElementById('progress-bar');

let logPollingInterval = null;

// --- Fetch manifest from backend ---
async function fetchManifest() {
  try {
    const res = await fetch(`${backendBaseURL}/manifest`);
    if (!res.ok) throw new Error(`Manifest not found (status ${res.status})`);
    return await res.json();
  } catch (err) {
    console.error('Error fetching manifest:', err);
    return null;
  }
}

// --- Load floorplan SVG and render PNG ---
async function loadAssets() {
  const manifest = await fetchManifest();
  const floorplanDiv = document.getElementById('floorplan');
  const renderImg = document.getElementById('render');

  if (!manifest) {
    floorplanDiv.innerText = 'No floorplan yet. Click Generate.';
    renderImg.src = '';
    progressBar.style.width = '0%';
    statusSpan.textContent = '';
    return;
  }

  statusSpan.textContent = 'Loading assets...';
  progressBar.style.width = '20%';

  // --- SVG floorplan ---
  if (manifest.plans && manifest.plans.length > 0) {
    try {
      const svgText = await fetch(`${backendBaseURL}/${manifest.plans[0]}?t=${Date.now()}`)
        .then(r => r.text());
      floorplanDiv.innerHTML = svgText;
      progressBar.style.width = '60%';
    } catch {
      floorplanDiv.innerText = 'Failed to load floorplan';
    }
  } else {
    floorplanDiv.innerText = 'No floorplan in manifest';
  }

  // --- PNG render ---
  if (manifest.renders && manifest.renders.length > 0) {
    renderImg.src = `${backendBaseURL}/${manifest.renders[0]}?t=${Date.now()}`;
    renderImg.onload = () => {
      progressBar.style.width = '100%';
      setTimeout(() => { progressBar.style.width = '0%'; statusSpan.textContent = ''; }, 500);
    };
  } else {
    renderImg.src = '';
    progressBar.style.width = '0%';
    statusSpan.textContent = '';
  }
}

// --- Poll backend log for status updates ---
async function pollBackendLog() {
  try {
    const res = await fetch(`${backendBaseURL}/logs`);
    if (!res.ok) return;
    const text = await res.text();
    const lines = text.trim().split('\n');
    if (lines.length > 0) {
      const lastLine = lines[lines.length - 1];
      statusSpan.textContent = lastLine;
    }
  } catch (err) {
    console.error('Error polling backend log:', err);
  }
}

// --- Start log polling ---
function startLogPolling() {
  if (logPollingInterval) clearInterval(logPollingInterval);
  logPollingInterval = setInterval(pollBackendLog, 2000);
}

// --- Stop log polling ---
function stopLogPolling() {
  if (logPollingInterval) clearInterval(logPollingInterval);
  logPollingInterval = null;
}

// --- Handle Generate button ---
document.getElementById('generate').addEventListener('click', async () => {
  const prompt = document.getElementById('prompt').value;
  const url = `${backendBaseURL}/generate?prompt=${encodeURIComponent(prompt)}`;

  try {
    statusSpan.textContent = 'Starting generation...';
    progressBar.style.width = '10%';
    startLogPolling();

    await fetch(url, { method: 'POST' });

    // Poll manifest every 2 seconds until real assets appear
    const pollInterval = setInterval(async () => {
      const manifest = await fetchManifest();
      if (!manifest) return;

      const hasRealAssets = manifest.plans[0] && manifest.renders[0] &&
        !manifest.plans[0].includes('placeholder') &&
        !manifest.renders[0].includes('placeholder');

      if (hasRealAssets) {
        clearInterval(pollInterval);
        stopLogPolling();
        await loadAssets();
        statusSpan.textContent = 'Generation completed!';
      }
    }, 2000);

  } catch (err) {
    console.error('Error triggering generation:', err);
    statusSpan.textContent = 'Error during generation';
    progressBar.style.width = '0%';
    stopLogPolling();
  }
});

// --- Initial load ---
loadAssets();
