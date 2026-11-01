const statusEl = document.getElementById("status");

fetch("/health")
  .then((response) => {
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  })
  .then((data) => {
    statusEl.textContent = `后端正常 · ${data.version} · ${data.stage}`;
    statusEl.className = "status status--ok";
  })
  .catch(() => {
    statusEl.textContent = "后端未连接";
    statusEl.className = "status status--error";
  });
