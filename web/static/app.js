// Estado global de la interfaz
let currentFilter = "TODOS";
let currentPage = 1;
let pageSize = 25;
let searchQuery = "";
let searchTimeout = null;
let pollInterval = null;
let activeModalDocId = null;

document.addEventListener("DOMContentLoaded", () => {
    checkSystemStatus();
    loadSummary();
    loadTableData();
    startStatusPolling();
});

function setPath(path) {
    document.getElementById("scan-directory").value = path;
}

// -------------------------------------------------------------
// CONSULTA DE ESTADO Y PROGRESO
// -------------------------------------------------------------
async function checkSystemStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();
        
        const dbPill = document.getElementById("db-status-pill");
        if (data.mysql_connected) {
            dbPill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium";
            dbPill.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400"></span><span>MySQL: Conectado</span>`;
        } else {
            dbPill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs font-medium";
            dbPill.innerHTML = `<span class="w-2 h-2 rounded-full bg-rose-400"></span><span>MySQL: Desconectado</span>`;
        }

        updateProgressUI(data.auditor);
    } catch (e) {
        console.error("Error verificando estado del sistema:", e);
    }
}

function startStatusPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(async () => {
        try {
            const res = await fetch("/api/scan/progress");
            const data = await res.json();
            updateProgressUI(data);

            if (data.status === "RUNNING") {
                loadSummary();
            }
        } catch (e) {
            console.error("Error en polling:", e);
        }
    }, 1000);
}

function updateProgressUI(auditor) {
    if (!auditor) return;

    const progressContainer = document.getElementById("progress-container");
    const btnStart = document.getElementById("btn-start-scan");
    const btnStop = document.getElementById("btn-stop-scan");

    if (auditor.status === "RUNNING") {
        progressContainer.classList.remove("hidden");
        btnStart.disabled = true;
        btnStart.classList.add("opacity-50", "cursor-not-allowed");
        btnStop.disabled = false;

        document.getElementById("progress-current-file").textContent = auditor.current_file || "Analizando...";
        document.getElementById("progress-processed").textContent = auditor.processed_files;
        document.getElementById("progress-total").textContent = auditor.total_files;
        document.getElementById("progress-percent").textContent = auditor.progress_pct + "%";
        document.getElementById("progress-speed").textContent = auditor.rate_docs_per_sec + " docs/s";
        document.getElementById("progress-bar-fill").style.width = auditor.progress_pct + "%";
    } else {
        btnStart.disabled = false;
        btnStart.classList.remove("opacity-50", "cursor-not-allowed");
        btnStop.disabled = true;

        if (auditor.status === "COMPLETED" || auditor.status === "STOPPED") {
            document.getElementById("progress-percent").textContent = "100%";
            document.getElementById("progress-bar-fill").style.width = "100%";
            setTimeout(() => {
                if (auditor.status !== "RUNNING") {
                    loadTableData();
                    loadSummary();
                }
            }, 800);
        }
    }
}

// -------------------------------------------------------------
// CONTROL DE AUDITORÍA
// -------------------------------------------------------------
async function startScan() {
    const dir = document.getElementById("scan-directory").value.trim();
    const limitVal = document.getElementById("scan-limit").value;
    const limit = limitVal ? parseInt(limitVal) : null;

    if (!dir) {
        alert("Por favor introduce una ruta de directorio válida.");
        return;
    }

    try {
        const res = await fetch("/api/scan/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ directory: dir, recursive: false, limit: limit })
        });
        const data = await res.json();
        if (!res.ok) {
            alert("Error al iniciar: " + (data.detail || "Error desconocido"));
        } else {
            document.getElementById("progress-container").classList.remove("hidden");
        }
    } catch (e) {
        alert("Error de conexión al iniciar: " + e.message);
    }
}

async function stopScan() {
    try {
        await fetch("/api/scan/stop", { method: "POST" });
    } catch (e) {
        console.error("Error al detener auditoría:", e);
    }
}

// -------------------------------------------------------------
// MÉTRICAS Y TABLA DE RESULTADOS
// -------------------------------------------------------------
async function loadSummary() {
    try {
        const res = await fetch("/api/summary");
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById("kpi-total").textContent = data.total.toLocaleString();
        document.getElementById("kpi-correctos").textContent = data.correctos.toLocaleString();
        document.getElementById("kpi-discrepancias").textContent = data.discrepancias.toLocaleString();
        document.getElementById("kpi-errores").textContent = data.errores.toLocaleString();
        document.getElementById("kpi-tasa").textContent = data.tasa_discrepancia_pct + "%";

        document.getElementById("count-todos").textContent = data.total;
        document.getElementById("count-discrepancias").textContent = data.discrepancias;
    } catch (e) {
        console.error("Error cargando resumen:", e);
    }
}

async function loadTableData() {
    try {
        const params = new URLSearchParams({
            estado: currentFilter,
            search: searchQuery,
            page: currentPage,
            page_size: pageSize
        });

        const res = await fetch(`/api/results?${params.toString()}`);
        if (!res.ok) return;
        const data = await res.json();

        renderTable(data.items);
        renderPagination(data);
    } catch (e) {
        console.error("Error cargando tabla:", e);
    }
}

function renderTable(items) {
    const tbody = document.getElementById("table-body");
    tbody.innerHTML = "";

    if (!items || items.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="11" class="text-center py-8 text-slate-500">
                    <i class="fa-solid fa-folder-open text-2xl mb-2 text-slate-600 block"></i>
                    No se encontraron registros para los filtros seleccionados.
                </td>
            </tr>
        `;
        return;
    }

    items.forEach(doc => {
        const tr = document.createElement("tr");
        tr.className = "hover:bg-slate-700/30 transition border-b border-slate-700/40";

        // Badges de estado
        let badgeClass = "badge-correcto";
        let statusText = doc.estado;
        if (doc.estado.includes("DISCREPANCIA")) {
            badgeClass = "badge-discrepancia";
            statusText = "DISCREPANCIA";
        } else if (doc.estado === "ERROR_LECTURA" || doc.estado === "NOMBRE_INVALIDO") {
            badgeClass = "badge-error";
            statusText = "ERROR";
        }

        // Doble marca
        const dobleMarca = doc.coincide_encabezado_pie 
            ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"><i class="fa-solid fa-check mr-1"></i>SÍ</span>`
            : `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-700 text-slate-400">NO</span>`;

        // Trampa de antecedente
        const trampaHtml = doc.registro_antecedente 
            ? `<span class="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30 text-rose-300 font-mono font-semibold" title="Número detectado en Antecedentes">${doc.registro_antecedente}</span>`
            : `<span class="text-slate-500">-</span>`;

        // Nombre propuesto con botón de copia
        const propuestoHtml = doc.nombre_propuesto 
            ? `<div class="flex items-center gap-1.5 font-mono text-emerald-400 font-medium">
                 <span>${doc.nombre_propuesto}</span>
                 <button onclick="copyText('${doc.nombre_propuesto}')" title="Copiar nombre" class="text-slate-400 hover:text-white p-1">
                     <i class="fa-regular fa-copy"></i>
                 </button>
               </div>`
            : `<span class="text-slate-500">-</span>`;

        tr.innerHTML = `
            <td class="py-3 px-4">
                <span class="px-2 py-0.5 rounded-md text-[11px] font-semibold ${badgeClass}">
                    ${statusText}
                </span>
            </td>
            <td class="py-3 px-4 font-mono text-slate-200 font-medium">${doc.nombre_archivo}</td>
            <td class="py-3 px-4 text-center font-mono text-amber-300 font-bold">${doc.registro_actual || '-'}</td>
            <td class="py-3 px-4 text-center font-mono text-emerald-300 font-semibold">${doc.registro_encabezado || '-'}</td>
            <td class="py-3 px-4 text-center font-mono text-blue-300 font-semibold">${doc.registro_pie || '-'}</td>
            <td class="py-3 px-4 text-center">${dobleMarca}</td>
            <td class="py-3 px-4 text-center">${trampaHtml}</td>
            <td class="py-3 px-4">${propuestoHtml}</td>
            <td class="py-3 px-4 text-center font-bold ${doc.confianza_score >= 90 ? 'text-emerald-400' : 'text-amber-400'}">
                ${doc.confianza_score}%
            </td>
            <td class="py-3 px-4 text-slate-400 text-[11px] max-w-xs truncate" title="${doc.motivo_discrepancia || ''}">
                ${doc.motivo_discrepancia || '-'}
            </td>
            <td class="py-3 px-4 text-center whitespace-nowrap">
                <button onclick="openPreviewModal(${doc.id})" title="Inspección visual" class="p-1.5 rounded-lg bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 transition mr-1">
                    <i class="fa-solid fa-eye text-xs"></i>
                </button>
                ${doc.estado.includes("DISCREPANCIA") && doc.estado_renombrado === 'PENDIENTE' ? `
                    <button onclick="applyRowRename(${doc.id})" title="Aplicar renombrado" class="p-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 transition">
                        <i class="fa-solid fa-signature text-xs"></i>
                    </button>
                ` : ''}
            </td>
        `;

        tbody.appendChild(tr);
    });
}

function renderPagination(data) {
    const start = (data.page - 1) * data.page_size + (data.items.length > 0 ? 1 : 0);
    const end = Math.min(data.page * data.page_size, data.total);

    document.getElementById("page-start").textContent = start;
    document.getElementById("page-end").textContent = end;
    document.getElementById("page-total").textContent = data.total;
    document.getElementById("current-page").textContent = data.page;

    document.getElementById("btn-prev-page").disabled = data.page <= 1;
    document.getElementById("btn-next-page").disabled = data.page >= data.total_pages;
}

function changePage(delta) {
    currentPage += delta;
    if (currentPage < 1) currentPage = 1;
    loadTableData();
}

function setFilter(filter) {
    currentFilter = filter;
    currentPage = 1;
    document.querySelectorAll(".filter-tab").forEach(tab => {
        tab.className = "filter-tab px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600";
    });

    if (filter === "TODOS") document.getElementById("tab-todos").className = "filter-tab active px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white";
    if (filter === "DISCREPANCIAS") document.getElementById("tab-discrepancias").className = "filter-tab active px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white";
    if (filter === "CORRECTO") document.getElementById("tab-correctos").className = "filter-tab active px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white";
    if (filter === "ERROR_LECTURA") document.getElementById("tab-errores").className = "filter-tab active px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white";

    loadTableData();
}

function debounceSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        searchQuery = document.getElementById("table-search").value.trim();
        currentPage = 1;
        loadTableData();
    }, 300);
}

// -------------------------------------------------------------
// MODAL DE INSPECCIÓN VISUAL (BOUNDING BOXES)
// -------------------------------------------------------------
async function openPreviewModal(docId) {
    activeModalDocId = docId;
    try {
        const res = await fetch(`/api/document/${docId}`);
        if (!res.ok) throw new Error("No se pudo cargar el detalle");
        const doc = await res.json();

        document.getElementById("modal-doc-title").textContent = doc.nombre_archivo;
        document.getElementById("modal-actual-name").textContent = doc.nombre_archivo;
        document.getElementById("modal-propuesto-name").textContent = doc.nombre_propuesto || "N/A";
        document.getElementById("modal-confianza").textContent = doc.confianza_score + "%";
        document.getElementById("modal-motivo").textContent = doc.motivo_discrepancia || "Sin observaciones.";

        document.getElementById("modal-box-header").textContent = "Registro: " + (doc.registro_encabezado || "No detectado");
        document.getElementById("modal-box-footer").textContent = "Registro: " + (doc.registro_pie || "No detectado");
        document.getElementById("modal-box-ant").textContent = "Registro: " + (doc.registro_antecedente || "Ninguno (Sin confusión)");

        // Configurar imagen de vista previa
        const img = document.getElementById("modal-preview-img");
        img.src = `/api/document/${docId}/preview?t=${new Date().getTime()}`;

        // Botón de renombrado en modal
        const renameBtn = document.getElementById("modal-action-box");
        if (doc.estado.includes("DISCREPANCIA") && doc.estado_renombrado === 'PENDIENTE') {
            renameBtn.classList.remove("hidden");
        } else {
            renameBtn.classList.add("hidden");
        }

        document.getElementById("preview-modal").classList.remove("hidden");
    } catch (e) {
        alert("Error abriendo vista previa: " + e.message);
    }
}

function closePreviewModal() {
    document.getElementById("preview-modal").classList.add("hidden");
    document.getElementById("modal-preview-img").src = "";
    activeModalDocId = null;
}

async function applySingleRename() {
    if (!activeModalDocId) return;
    if (!confirm("¿Deseas renombrar este archivo físico al nombre propuesto por el OCR?")) return;

    try {
        const res = await fetch(`/api/rename/single/${activeModalDocId}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
            alert("Error al renombrar: " + (data.detail || data.message));
        } else {
            alert(data.message);
            closePreviewModal();
            loadTableData();
            loadSummary();
        }
    } catch (e) {
        alert("Error al ejecutar renombrado: " + e.message);
    }
}

async function applyRowRename(docId) {
    if (!confirm("¿Deseas renombrar este archivo físico al nombre propuesto por el OCR?")) return;
    try {
        const res = await fetch(`/api/rename/single/${docId}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
            alert("Error al renombrar: " + (data.detail || data.message));
        } else {
            alert(data.message);
            loadTableData();
            loadSummary();
        }
    } catch (e) {
        alert("Error al ejecutar renombrado: " + e.message);
    }
}

// -------------------------------------------------------------
// HERRAMIENTAS DE BASE DE DATOS
// -------------------------------------------------------------
function openDbModal() {
    document.getElementById("db-action-msg").classList.add("hidden");
    document.getElementById("db-modal").classList.remove("hidden");
}

function closeDbModal() {
    document.getElementById("db-modal").classList.add("hidden");
}

async function runDbAction(action, clean) {
    const msgBox = document.getElementById("db-action-msg");
    msgBox.classList.remove("hidden");
    msgBox.className = "text-xs p-2.5 rounded-lg bg-blue-500/20 text-blue-300 border border-blue-500/40";
    msgBox.textContent = "Procesando operación en MySQL...";

    try {
        let url = action === "init" ? "/api/db/init" : "/api/db/reset";
        let body = action === "init" ? { clean: clean } : {};

        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
        const data = await res.json();

        if (!res.ok) {
            msgBox.className = "text-xs p-2.5 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-500/40";
            msgBox.textContent = "Error: " + (data.detail || data.message);
        } else {
            msgBox.className = "text-xs p-2.5 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40";
            msgBox.textContent = data.message;
            loadSummary();
            loadTableData();
            checkSystemStatus();
        }
    } catch (e) {
        msgBox.className = "text-xs p-2.5 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-500/40";
        msgBox.textContent = "Error de red: " + e.message;
    }
}

// Utilidad para copiar al portapapeles
function copyText(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert("Copiado al portapapeles: " + text);
    });
}
