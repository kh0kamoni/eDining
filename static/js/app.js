// State Variables
let token = localStorage.getItem("edining_token") || "";
let currentUser = null;
let activeAdminTable = "";
let adminTablesMetadata = [];
let managerActiveCycle = null;
let managerStudents = [];
let managerSearchMatches = [];

// API Base configuration
const API_PREFIX = "/api";

// Timezone-safe local date/month formatting helpers
function getLocalDateString(dateObj = new Date()) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function getLocalMonthString(dateObj = new Date()) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    return `${y}-${m}`;
}

// Helper for HTTP requests with JWT token
async function apiFetch(endpoint, options = {}) {
    const url = `${API_PREFIX}${endpoint}`;
    
    // Set headers
    options.headers = options.headers || {};
    if (token) {
        options.headers["Authorization"] = `Bearer ${token}`;
    }
    if (!(options.body instanceof FormData) && typeof options.body === "object") {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(options.body);
    }

    let response;
    try {
        response = await fetch(url, options);
    } catch (e) {
        throw new Error(`Network error: could not reach the server.`);
    }
    
    if (response.status === 401 && !endpoint.includes("/auth/login")) {
        // Token expired or invalid
        handleLogout();
        throw new Error("Session expired. Please sign in again.");
    }
    
    if (!response.ok) {
        let detail = "";
        try {
            const errData = await response.json();
            detail = errData.detail || errData.message || (typeof errData === "string" ? errData : "");
        } catch (e) {
            detail = await response.text().catch(() => "");
        }
        throw new Error(`Request failed (${response.status}): ${detail || response.statusText || "Unknown server error"}`);
    }
    
    return response.json();
}

// Show global banner message
function showBanner(message, isError = false) {
    const banner = document.getElementById("global-message-banner");
    const bannerText = document.getElementById("banner-text");
    
    banner.classList.remove("hidden", "bg-emerald-500/10", "border-emerald-500/25", "text-emerald-400", "bg-rose-500/10", "border-rose-500/25", "text-rose-400");
    
    if (isError) {
        banner.classList.add("bg-rose-500/10", "border-rose-500/25", "text-rose-400");
        bannerText.innerHTML = `<i class="fa-solid fa-circle-exclamation mr-2"></i> ${message}`;
    } else {
        banner.classList.add("bg-emerald-500/10", "border-emerald-500/25", "text-emerald-400");
        bannerText.innerHTML = `<i class="fa-solid fa-circle-check mr-2"></i> ${message}`;
    }
    banner.classList.remove("hidden");
    setTimeout(() => {
        banner.classList.add("hidden");
    }, 6000);
}

// Dark mode toggle
function toggleDarkMode() {
    const isDark = document.documentElement.classList.toggle("dark-mode");
    localStorage.setItem("edining_dark", isDark ? "true" : "false");
    applyDarkMode(isDark);
}
function applyDarkMode(isDark) {
    document.documentElement.classList.toggle("dark-mode", isDark);
    const icon = document.getElementById("dark-mode-icon");
    if (icon) icon.className = isDark ? "fa-solid fa-sun text-sm" : "fa-solid fa-moon text-sm";
    const mobileIcon = document.getElementById("dark-mode-icon-mobile");
    if (mobileIcon) mobileIcon.className = isDark ? "fa-solid fa-sun" : "fa-solid fa-moon";
}
(function initDarkMode() {
    const saved = localStorage.getItem("edining_dark");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyDarkMode(saved !== null ? saved === "true" : prefersDark);
})();

// Initial Setup on Page Load
document.addEventListener("DOMContentLoaded", async () => {
    // Populate registration halls dropdown
    await loadHallsDropdown();
    
    if (token) {
        try {
            await fetchUserProfile();
            showAppShell();
        } catch (e) {
            console.error("Profile load failed", e);
            showAuthPortal();
        }
    } else {
        showAuthPortal();
    }
    // Load signup lock state after everything is ready
    setTimeout(async () => { try { await loadStudentFeatureStates(); } catch {} }, 500);
});

// Load Halls list for signup dropdown
async function loadHallsDropdown() {
    try {
        const response = await fetch(`${API_PREFIX}/student/halls`);
        const halls = await response.json();
        const select = document.getElementById("reg-hall");
        select.innerHTML = '<option value="" disabled selected>Choose a Hall...</option>';
        
        halls.forEach(hall => {
            const opt = document.createElement("option");
            opt.value = hall.id;
            opt.textContent = hall.name;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error("Failed to load halls", e);
    }
}

// Navigation between Auth Tabs (Login vs Register)
function toggleAuthTab(tab) {
    const loginTabBtn = document.getElementById("tab-login-btn");
    const regTabBtn = document.getElementById("tab-register-btn");
    const payTabBtn = document.getElementById("tab-pay-btn");
    const loginForm = document.getElementById("login-form");
    const regForm = document.getElementById("register-form");
    const payPortal = document.getElementById("pay-portal");
    const errorDiv = document.getElementById("auth-error");
    const baseInactive = "flex-1 pb-3 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-white focus:outline-none";
    const baseActive = "flex-1 pb-3 text-sm font-semibold border-b-2 border-emerald-500 text-emerald-400 focus:outline-none";

    errorDiv.classList.add("hidden");
    loginForm.classList.add("hidden");
    regForm.classList.add("hidden");
    if (payPortal) payPortal.classList.add("hidden");

    if (tab === "login") {
        loginTabBtn.className = baseActive;
        regTabBtn.className = baseInactive;
        if (payTabBtn) payTabBtn.className = baseInactive;
        loginForm.classList.remove("hidden");
    } else if (tab === "register") {
        regTabBtn.className = baseActive;
        loginTabBtn.className = baseInactive;
        if (payTabBtn) payTabBtn.className = baseInactive;
        regForm.classList.remove("hidden");
    } else if (tab === "pay") {
        if (payTabBtn) payTabBtn.className = baseActive;
        loginTabBtn.className = baseInactive;
        regTabBtn.className = baseInactive;
        if (payPortal) payPortal.classList.remove("hidden");
    }
}

// Public Pay Portal
let publicSearchTimeout;
async function publicSearchStudents() {
    clearTimeout(publicSearchTimeout);
    const q = document.getElementById("pay-search").value.trim();
    const results = document.getElementById("pay-results");
    if (!q) { results.innerHTML = '<div class="text-xs text-slate-500 text-center py-4">Type a name, username, or room to search.</div>'; return; }
    publicSearchTimeout = setTimeout(async () => {
        try {
            const data = await apiFetch(`/public/students?query=${encodeURIComponent(q)}`);
            if (data.length === 0) { results.innerHTML = '<div class="text-xs text-slate-500 text-center py-4">No students found.</div>'; return; }
            results.innerHTML = data.map(s => `
                <div class="flex items-center justify-between p-3 rounded-xl bg-slate-900/40 border border-slate-800">
                    <div>
                        <p class="text-sm font-bold text-white">${s.name}</p>
                        <p class="text-[10px] text-slate-400">${s.username} · Room ${s.room_number || 'N/A'}</p>
                    </div>
                    <button onclick="openPublicPayModal('${s.username}', '${s.name}')" class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 px-4 py-1.5 rounded-xl text-xs font-bold transition">Pay</button>
                </div>
            `).join("");
        } catch (e) { results.innerHTML = `<div class="text-xs text-rose-400 text-center py-4">${e.message}</div>`; }
    }, 300);
}

function openPublicPayModal(username, name) {
    document.getElementById("public-pay-username").textContent = username;
    document.getElementById("public-pay-name").textContent = name;
    document.getElementById("public-pay-trx").value = "";
    document.getElementById("public-pay-feedback").className = "mt-3 p-3 rounded-xl text-xs hidden";
    document.getElementById("public-pay-modal").classList.remove("hidden");
}
function closePublicPayModal() { document.getElementById("public-pay-modal").classList.add("hidden"); }

async function handlePublicPayClaim() {
    const username = document.getElementById("public-pay-username").textContent;
    const trxId = document.getElementById("public-pay-trx").value.trim().toUpperCase();
    if (!trxId || trxId.length < 5) { showBanner("Enter a valid Transaction ID.", true); return; }
    const btn = document.querySelector("#public-pay-modal .bg-emerald-500");
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Processing...';
    try {
        const result = await apiFetch(`/public/deposit/claim?username=${encodeURIComponent(username)}&trx_id=${encodeURIComponent(trxId)}`, { method: "POST" });
        document.getElementById("public-pay-feedback").className = "mt-3 p-3 rounded-xl text-xs bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-semibold";
        document.getElementById("public-pay-feedback").textContent = result.message;
        document.getElementById("public-pay-trx").value = "";
    } catch (e) {
        document.getElementById("public-pay-feedback").className = "mt-3 p-3 rounded-xl text-xs bg-rose-500/10 border border-rose-500/20 text-rose-400 font-semibold";
        document.getElementById("public-pay-feedback").textContent = e.message;
    }
    btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-circle-check"></i> Confirm Payment';
}

// Handle login submission
async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById("login-username").value;
    const password = document.getElementById("login-password").value;
    const errorDiv = document.getElementById("auth-error");
    errorDiv.classList.add("hidden");

    try {
        const data = await apiFetch("/auth/login", {
            method: "POST",
            body: { username, password }
        });
        token = data.access_token;
        localStorage.setItem("edining_token", token);
        
        await fetchUserProfile();
        showAppShell();
        showBanner("Welcome back to eDining dashboard!");
    } catch (err) {
        errorDiv.textContent = err.message;
        errorDiv.classList.remove("hidden");
    }
}

// Handle student registration
async function handleRegister(e) {
    e.preventDefault();
    const name = document.getElementById("reg-name").value;
    const username = document.getElementById("reg-username").value;
    const password = document.getElementById("reg-password").value;
    const email = document.getElementById("reg-email").value;
    const hall_id = parseInt(document.getElementById("reg-hall").value);
    const room_number = document.getElementById("reg-room").value;
    const phone = document.getElementById("reg-phone").value;
    const errorDiv = document.getElementById("auth-error");
    errorDiv.classList.add("hidden");

    try {
        await apiFetch("/auth/register", {
            method: "POST",
            body: {
                username, password, name, email, hall_id, room_number, phone, role: "student"
            }
        });
        showBanner("Registration successful! You can now log in.");
        toggleAuthTab("login");
        document.getElementById("login-username").value = username;
    } catch (err) {
        errorDiv.textContent = err.message;
        errorDiv.classList.remove("hidden");
    }
}

// Fetch user profile info
async function fetchUserProfile() {
    currentUser = await apiFetch("/auth/me");
    
    // Update sidebar profiles
    document.getElementById("sidebar-user-name").textContent = currentUser.name;
    document.getElementById("sidebar-user-role").textContent = currentUser.role;
    
    // Update headers — show 0 for free_meal users (managers), cycle balance fetched later
    const initBal = currentUser.free_meal ? 0 : currentUser.balance;
        const setHb = (id, val) => { const e = document.getElementById(id); if (e) { const v = parseFloat(val) || 0; e.textContent = 'BDT ' + (v < 0 ? '-' : '') + Math.abs(v).toFixed(2); e.className = e.className.replace(/text-\w+(-\d+)?/g, '').trim() + (v >= 0 ? ' text-emerald-400' : ' text-rose-400') + ' font-bold'; } };
    setHb("header-balance-amount", initBal);
    setHb("mobile-balance", initBal);
    
    // Set hall badge
    const hallBadge = document.getElementById("header-hall-badge");
    if (hallBadge && currentUser.hall_name) {
        hallBadge.textContent = currentUser.hall_name;
    }
    
    // Show/hide sections based on role
    const isManager = ["manager", "assistant_manager", "superadmin"].includes(currentUser.role);
    const isAdmin = currentUser.role === "superadmin";
    
    document.getElementById("nav-manager-btn").style.display = isManager ? "flex" : "none";
    document.getElementById("nav-admin-btn").style.display = isAdmin ? "flex" : "none";
    
    // SMS simulator visible to superadmin only
    const simDrawer = document.getElementById("sms-simulator-drawer");
    if (simDrawer) simDrawer.classList.toggle("hidden", !isAdmin);
}

// Logout
function handleLogout() {
    token = "";
    currentUser = null;
    localStorage.removeItem("edining_token");
    showAuthPortal();
}

function showAuthPortal() {
    document.getElementById("auth-portal").classList.remove("hidden");
    document.getElementById("app-shell").classList.add("hidden");
}

function showAppShell() {
    document.getElementById("auth-portal").classList.add("hidden");
    document.getElementById("app-shell").classList.remove("hidden");
    
    const saved = localStorage.getItem("edining_section");
    const isManager = ["manager", "assistant_manager", "superadmin"].includes(currentUser?.role);
    const isAdmin = currentUser?.role === "superadmin";
    // Only restore valid section; fallback to student
    if (saved === "manager" && isManager) {
        showDashboardSection("manager");
    } else if (saved === "admin" && isAdmin) {
        showDashboardSection("admin");
    } else {
        showDashboardSection("student");
    }
}

// Sidebar routing
let studentPollTimer = null;

function showDashboardSection(section) {
    localStorage.setItem("edining_section", section);
    const sections = ["student", "manager", "admin"];
    sections.forEach(s => {
        document.getElementById(`${s}-section`).classList.add("hidden");
        const btn = document.getElementById(`nav-${s}-btn`);
        btn.className = "nav-item flex w-full items-center space-x-3 px-4 py-3 rounded-xl text-sm font-semibold transition";
        btn.classList.remove("nav-item-active");
    });
    
    document.getElementById(`${section}-section`).classList.remove("hidden");
    const activeBtn = document.getElementById(`nav-${section}-btn`);
    activeBtn.className = "nav-item flex w-full items-center space-x-3 px-4 py-3 rounded-xl text-sm font-semibold transition";
    activeBtn.classList.add("nav-item-active");


    // Stop any existing student poll
    if (studentPollTimer) { clearInterval(studentPollTimer); studentPollTimer = null; }

    if (section === "student") {
        loadStudentDashboard();
        // Auto-refresh every 60 seconds so manager changes are reflected live
        studentPollTimer = setInterval(() => {
            if (!document.getElementById('student-section').classList.contains('hidden')) {
                loadStudentDashboard(true); // silent refresh
            } else {
                clearInterval(studentPollTimer);
                studentPollTimer = null;
            }
        }, 60000);
    } else if (section === "manager") {
        const savedTab = localStorage.getItem("edining_mgr_tab");
        if (savedTab && ["ops","sheet","summary","rates","settings","bkash","profit","deposits","prefs","moneyflow"].includes(savedTab)) {
            activeManagerTab = savedTab;
        }
        loadManagerDashboard();
        // Restore the saved tab's visual state after load
        if (savedTab) {
            const tabBtn = document.querySelector(`.mgr-tab-btn[onclick*="'${savedTab}'"]`);
            if (tabBtn) toggleManagerTab(savedTab, tabBtn);
        }
    } else if (section === "admin") {
        loadAdminDashboard();
    }
}

// ==========================================
// STUDENT PORTAL LOGIC
// ==========================================
let studentInfo = null;

async function loadStudentDashboard(silent = false) {
    // Spin the refresh icon while loading
    const refreshBtn = document.getElementById('meal-grid-refresh-btn');
    const refreshIcon = refreshBtn ? refreshBtn.querySelector('i') : null;
    if (refreshIcon && !silent) refreshIcon.classList.add('fa-spin');

    try {
        await loadStudentFeatureStates();
        // Apply hide/lock for each feature
        const featureCards = [
            // { container: element, feat: string, useOverlay: bool }
        ];
        const bCard = document.getElementById("student-balance-card");
        if (bCard) featureCards.push({ container: bCard, feat: "balance_view", useOverlay: true });
        const depBtn = document.getElementById("student-deposit-btn");
        if (depBtn) featureCards.push({ container: depBtn, feat: "deposit", useOverlay: false });
        const dietCard = document.getElementById("diet-pref-card");
        if (dietCard) featureCards.push({ container: dietCard, feat: "profile", useOverlay: true });
        const editBtn = document.getElementById("student-edit-profile-btn");
        if (editBtn) featureCards.push({ container: editBtn, feat: "edit_profile", useOverlay: false });
        const statusPanel = document.querySelector("#ctrl-meal-status")?.closest(".glass-panel");
        if (statusPanel) featureCards.push({ container: statusPanel, feat: "meal_status", useOverlay: true });
        const calPanel = document.querySelector("#student-meal-grid")?.closest(".glass-panel");
        if (calPanel) featureCards.push({ container: calPanel, feat: "calendar", useOverlay: true });
        const hallCard = document.getElementById("student-hall-card");
        if (hallCard) featureCards.push({ container: hallCard, feat: "hall_details", useOverlay: true });
        const guestCard = document.getElementById("student-guest-card");
        if (guestCard) featureCards.push({ container: guestCard, feat: "guest_switcher", useOverlay: true });
        const depTab = document.getElementById("tab-student-deposits-btn");
        if (depTab) featureCards.push({ container: depTab, feat: "deposit_logs", useOverlay: false });
        const depPanel = document.getElementById("student-tab-deposits");
        if (depPanel) featureCards.push({ container: depPanel, feat: "deposit_logs", useOverlay: true });
        const rateTab = document.getElementById("tab-student-rates-btn");
        if (rateTab) featureCards.push({ container: rateTab, feat: "rate_logs", useOverlay: false });
        const ratePanel = document.getElementById("student-tab-rates");
        if (ratePanel) featureCards.push({ container: ratePanel, feat: "rate_logs", useOverlay: true });
        const mealHistTab = document.getElementById("tab-student-meals-btn");
        if (mealHistTab) featureCards.push({ container: mealHistTab, feat: "meal_history", useOverlay: false });
        const mealHistPanel = document.getElementById("student-tab-meals");
        if (mealHistPanel) featureCards.push({ container: mealHistPanel, feat: "meal_history", useOverlay: true });
        
        for (const { container: el, feat, useOverlay, alsoFeat } of featureCards) {
            el.querySelector(".feature-lock-overlay")?.remove();
            const state = checkFeature(feat);
            const alsoState = alsoFeat ? checkFeature(alsoFeat) : null;
            const hidden = state.hidden || (alsoState && alsoState.hidden);
            const locked = state.locked || (alsoState && alsoState.locked);
            const msg = state.message || (alsoState && alsoState.message) || "";
            
            if (hidden) {
                el.style.display = "none";
            } else if (locked && useOverlay) {
                el.style.display = "";
                el.style.position = "relative";
                const overlay = document.createElement("div");
                overlay.className = "feature-lock-overlay absolute inset-0 bg-slate-950/70 backdrop-blur-sm flex flex-col items-center justify-center z-10 rounded-2xl";
                overlay.innerHTML = `<i class="fa-solid fa-lock text-amber-400 text-lg mb-2"></i><span class="text-amber-400 text-xs font-bold text-center px-4">${msg || "This feature is locked."}</span>`;
                el.appendChild(overlay);
            } else if (locked && !useOverlay) {
                el.style.display = "";
                el.style.opacity = "0.5";
                el.style.pointerEvents = "none";
                el.title = msg || "This feature is locked.";
                // Add lock icon overlay on top of button
                if (!el.querySelector(".btn-lock-badge")) {
                    el.style.position = "relative";
                    const badge = document.createElement("span");
                    badge.className = "btn-lock-badge";
                    badge.innerHTML = '<i class="fa-solid fa-lock text-[8px]"></i>';
                    badge.style.cssText = "position:absolute;top:2px;right:2px;background:rgba(251,191,36,0.9);color:#000;border-radius:50%;width:14px;height:14px;display:flex;align-items:center;justify-content:center;z-index:5;";
                    el.appendChild(badge);
                }
            } else {
                el.style.display = "";
                el.style.opacity = "";
                el.style.pointerEvents = "";
                el.style.filter = "";
                el.title = "";
                el.querySelector(".btn-lock-badge")?.remove();
            }
        }
        // Show student section after feature checks are applied (prevents flash of hidden elements)
        const studentSection = document.getElementById("student-section");
        if (studentSection) studentSection.style.display = "";
        
        // Auto-hide grid if all children are hidden
        const topGrid = document.getElementById("student-top-grid");
        if (topGrid) {
            const visible = [...topGrid.children].some(c => c.style.display !== "none");
            topGrid.style.display = visible ? "" : "none";
        }
        const midGrid = document.querySelector("#student-section > .grid.grid-cols-1.lg\\:grid-cols-3");
        if (midGrid) {
            const visible = [...midGrid.children].some(c => c.style.display !== "none");
            midGrid.style.display = visible ? "" : "none";
        }
        // Hide tab container if all tab features are hidden
        const tabContainer = document.getElementById("student-tab-container");
        if (tabContainer) {
            const tabBtns = tabContainer.querySelectorAll("button[id^='tab-student-']");
            const anyVisible = [...tabBtns].some(btn => btn.style.display !== "none");
            tabContainer.style.display = anyVisible ? "" : "none";
        }
        
        studentInfo = await apiFetch("/student/dashboard-info");
        currentUser.balance = studentInfo.user.balance;
        const setBalColor = (el, val) => { if (el) { const v = parseFloat(val) || 0; el.textContent = 'BDT ' + (v < 0 ? '-' : '') + Math.abs(v).toFixed(2); el.className = el.className.replace(/text-\w+(-\d+)?/g, '').trim() + (v >= 0 ? ' text-emerald-400' : ' text-rose-400') + ' font-bold'; } };
        setBalColor(document.getElementById("header-balance-amount"), studentInfo.user.balance);
        const mobileBalEl = document.getElementById("mobile-balance");
        if (mobileBalEl) setBalColor(mobileBalEl, studentInfo.user.balance);
        setBalColor(document.getElementById("student-balance-lg"), studentInfo.user.balance);
        const depEl = document.getElementById("student-total-deposits");
        if (depEl) { depEl.textContent = `BDT ${(studentInfo.total_deposits || 0).toFixed(2)}`; depEl.className = depEl.className.replace(/text-\w+(-\d+)?/g, '').trim() + ' text-emerald-400 font-bold'; }

        document.getElementById("student-info-hall").innerHTML = `<i class="fa-solid fa-hotel mr-2 text-emerald-400"></i> ${studentInfo.user.hall_name}`;
        document.getElementById("student-info-room").textContent = `Room ${studentInfo.user.room_number || "N/A"} | Role: ${studentInfo.user.role}`;
        document.getElementById("header-hall-badge").textContent = studentInfo.user.hall_name;
        document.getElementById("cutoff-time-text").textContent = `Daily Cutoff: ${studentInfo.cutoff_time}`;
        
        // Load dietary preference
        const prefFish = document.getElementById("pref-fish-egg");
        if (prefFish) prefFish.value = studentInfo.user.fish_egg_pref || "normal";
        const prefMeat = document.getElementById("pref-meat");
        if (prefMeat) prefMeat.value = studentInfo.user.meat_pref || "normal";
        
        // Deposits table
        const depositTbody = document.getElementById("student-deposit-tbody");
        if (studentInfo.deposits.length === 0) {
            depositTbody.innerHTML = `<tr><td colspan="3" class="py-4 text-center text-xs text-slate-500">No deposits recorded yet.</td></tr>`;
        } else {
            depositTbody.innerHTML = studentInfo.deposits.map(d => `
                <tr class="hover:bg-slate-900/40">
                    <td class="py-3 px-4 font-semibold text-xs">${d.date}</td>
                    <td class="py-3 px-4 text-emerald-400 font-bold text-xs">+ BDT ${d.amount.toFixed(2)}</td>
                    <td class="py-3 px-4 text-slate-400 text-xs">${d.description || "-"}</td>
                </tr>
            `).join("");
        }
        
        // Find guest status
        let activeGuestHallId = "";
        let hasActiveGuest = false;
        Object.values(studentInfo.meals).forEach(m => {
            if (m.is_guest && m.status !== "off") {
                hasActiveGuest = true;
                if (m.target_hall_id) {
                    activeGuestHallId = m.target_hall_id;
                }
            }
        });

        // Render guest selector with other halls only (filter out home hall)
        const guestSelect = document.getElementById("guest-hall-select");
        const hallsResponse = await fetch(`${API_PREFIX}/student/halls`);
        const hallsList = await hallsResponse.json();
        
        guestSelect.innerHTML = '<option value="">Select Hall...</option>';
        hallsList.forEach(hall => {
            if (hall.id !== currentUser.hall_id) {
                const opt = document.createElement("option");
                opt.value = hall.id;
                opt.textContent = hall.name;
                guestSelect.appendChild(opt);
            }
        });
        
        // Restore guest hall selection from existing guest records (even if status=off)
        if (!hasActiveGuest) {
            // Check if any guest records exist (including off) to restore dropdown
            let lastGuestHall = null;
            Object.values(studentInfo.meals).forEach(m => {
                if (m.is_guest && m.target_hall_id) {
                    lastGuestHall = m.target_hall_id;
                }
            });
            if (lastGuestHall) {
                guestSelect.value = lastGuestHall;
            }
        }
        
        const guestConfirmBtn = document.getElementById("guest-confirm-btn");
        const guestInfoDiv = document.getElementById("guest-status-info");
        
        if (studentInfo.home_hall_active) {
            // Disable guest switcher
            guestSelect.disabled = true;
            if (guestConfirmBtn) guestConfirmBtn.disabled = true;
            guestInfoDiv.className = "text-xs text-rose-400 font-semibold mt-2";
            guestInfoDiv.innerHTML = `<i class="fa-solid fa-triangle-exclamation mr-1"></i> Guest switching disabled. Native hall dining is currently active.`;
        } else {
            // Enable
            guestSelect.disabled = false;
            if (guestConfirmBtn) guestConfirmBtn.disabled = false;
            
            if (hasActiveGuest) {
                guestSelect.value = activeGuestHallId;
                guestInfoDiv.className = "text-xs text-cyan-400 font-semibold mt-2";
                guestInfoDiv.innerHTML = `<i class="fa-solid fa-circle-check mr-1"></i> Guest meals active in other hall!`;
            } else {
                guestInfoDiv.className = "text-xs text-slate-400 mt-2";
                guestInfoDiv.textContent = "";
            }
        }

        // Next Day Controller logic
        const cutoffTime = studentInfo.cutoff_time || "20:00";
        const today = new Date();
        const todayStr = getLocalDateString(today);
        
        const tomorrow = new Date();
        tomorrow.setDate(today.getDate() + 1);
        const tomorrowStr = getLocalDateString(tomorrow);
        
        const dayAfter = new Date();
        dayAfter.setDate(today.getDate() + 2);
        const dayAfterStr = getLocalDateString(dayAfter);
        
        let targetChangeDate = tomorrowStr;
        let tomorrowIsLocked = checkCutoff(tomorrowStr, cutoffTime);
        
        if (tomorrowIsLocked) {
            targetChangeDate = dayAfterStr;
        }
        window._targetChangeDate = targetChangeDate;
        
        // Load status of target date
        const targetMealStatus = studentInfo.meals[targetChangeDate] || { status: "off" };
        const lunchOn = ["both", "lunch_only"].includes(targetMealStatus.status);
        const dinnerOn = ["both", "dinner_only"].includes(targetMealStatus.status);
        const isGuestMeal = targetMealStatus.is_guest && targetMealStatus.status !== "off";
        
        const dateTextSpan = document.getElementById("ctrl-date-text");
        const dateBadgeDiv = document.getElementById("ctrl-date-badge");
        
        if (tomorrowIsLocked) {
            if (isGuestMeal) {
                dateTextSpan.innerHTML = `<i class="fa-solid fa-plane-arrival mr-1"></i> Guest status active. Tomorrow locked. Changes apply from: ${dayAfterStr}`;
                dateBadgeDiv.className = "text-xs font-semibold text-cyan-400 bg-cyan-500/10 border border-cyan-500/15 p-3 rounded-xl flex items-center space-x-2";
            } else {
                dateTextSpan.textContent = `Tomorrow locked. Changes apply from: ${dayAfterStr}`;
                dateBadgeDiv.className = "text-xs font-semibold text-yellow-400 bg-yellow-500/10 border border-yellow-500/15 p-3 rounded-xl flex items-center space-x-2";
            }
        } else {
            if (isGuestMeal) {
                dateTextSpan.innerHTML = `<i class="fa-solid fa-plane-arrival mr-1"></i> Guest Meals Active starting Tomorrow (${tomorrowStr})`;
                dateBadgeDiv.className = "text-xs font-semibold text-cyan-400 bg-cyan-500/10 border border-cyan-500/15 p-3 rounded-xl flex items-center space-x-2";
            } else {
                dateTextSpan.textContent = `Changes apply starting: Tomorrow (${tomorrowStr})`;
                dateBadgeDiv.className = "text-xs font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/15 p-3 rounded-xl flex items-center space-x-2";
            }
        }
        
        // Set dropdown to current status
        const statusSelect = document.getElementById("ctrl-meal-status");
        if (statusSelect) {
            statusSelect.value = targetMealStatus.status || "off";
        }

        // Render meal grid scheduler (Preview next 7 days)
        renderMealGrid(studentInfo.meals);

        // Load active student log tab (skip on silent poll to avoid flickering)
        if (!silent) await toggleStudentLogTab(activeStudentTab);
    } catch (e) {
        if (!silent) showBanner(e.message, true);
    } finally {
        // Stop spin animation
        if (refreshIcon) refreshIcon.classList.remove('fa-spin');
    }
}

// Toggle Student Log Tabs
let activeStudentTab = "deposits";
async function toggleStudentLogTab(tab) {
    activeStudentTab = tab;
    
    // Manage tab buttons active style
    const tabs = ["deposits", "meals", "rates"];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-student-${t}-btn`);
        const panel = document.getElementById(`student-tab-${t}`);
        
        if (t === tab) {
            btn.className = "py-4 px-6 text-sm font-bold text-emerald-400 border-b-2 border-emerald-500 focus:outline-none";
            panel.classList.remove("hidden");
        } else {
            btn.className = "py-4 px-6 text-sm font-bold text-slate-400 border-b-2 border-transparent hover:text-white focus:outline-none";
            panel.classList.add("hidden");
        }
    });
    
    if (tab === "meals") {
        await loadStudentMeals();
    } else if (tab === "rates") {
        await loadStudentRates();
    }
}

// Fetch and load student meal logs
async function loadStudentMeals() {
    try {
        const data = await apiFetch("/student/meal-logs");
        const tbody = document.getElementById("student-meals-tbody");
        if (data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="py-4 text-center text-xs text-slate-500">No meal logs recorded.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = data.map(m => {
            const hasMeals = m.status !== "off";
            return `
                <tr class="hover:bg-slate-900/40 text-xs">
                    <td class="py-3 px-4 font-semibold">${m.date}</td>
                    <td class="py-3 px-4">
                        <span class="${hasMeals ? 'text-emerald-400 font-bold' : 'text-slate-500'}">
                            ${m.status === 'both' ? 'Lunch & Dinner' : m.status === 'lunch_only' ? 'Lunch Only' : m.status === 'dinner_only' ? 'Dinner Only' : 'Off'}
                        </span>
                    </td>
                    <td class="py-3 px-4 text-slate-400">${m.hall_name}</td>
                    <td class="py-3 px-4 text-center text-rose-400 font-bold">${hasMeals ? `BDT ${m.amount_deducted.toFixed(2)}` : '-'}</td>
                    <td class="py-3 px-4 text-right">
                        ${m.is_deducted ? 
                            `<span class="text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded text-[10px] font-bold"><i class="fa-solid fa-circle-check mr-1"></i> Billed</span>` : 
                            `<span class="text-slate-400 bg-slate-800 px-2 py-0.5 rounded text-[10px] font-bold"><i class="fa-solid fa-clock mr-1"></i> Pending</span>`}
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Fetch and load student daily rates logs
async function loadStudentRates() {
    try {
        const data = await apiFetch("/manager/daily-rates");
        const tbody = document.getElementById("student-rates-tbody");
        if (data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-xs text-slate-500">No daily rate data available.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = data.map(r => `
            <tr class="hover:bg-slate-900/40 text-xs">
                <td class="py-3 px-4 font-semibold">${r.date}</td>
                <td class="py-3 px-4 text-right text-slate-400">BDT ${r.daily_expenses.toFixed(2)}</td>
                <td class="py-3 px-4 text-right text-yellow-400 font-bold">BDT ${(r.lunch_rate||0).toFixed(2)}</td>
                <td class="py-3 px-4 text-right text-orange-400 font-bold">BDT ${(r.dinner_rate||0).toFixed(2)}</td>
                <td class="py-3 px-4 text-right text-emerald-400 font-bold">BDT ${(r.final_rate||0).toFixed(2)}</td>
                <td class="py-3 px-4 text-right text-cyan-400 font-bold">BDT ${(r.rate_with_charges||0).toFixed(2)}</td>
            </tr>
        `).join("");
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Help utility for toggle UI states
function updateToggleVisual(btn, isOn) {
    if (isOn) {
        btn.className = "h-6 w-11 rounded-full p-0.5 transition-colors duration-200 focus:outline-none flex items-center bg-emerald-500 justify-end cursor-pointer";
    } else {
        btn.className = "h-6 w-11 rounded-full p-0.5 transition-colors duration-200 focus:outline-none flex items-center bg-slate-800 justify-start cursor-pointer";
    }
}

// Cutoff check helper in Javascript
function checkCutoff(targetDateStr, cutoffTimeStr) {
    const today = new Date();
    const todayStr = getLocalDateString(today);
    
    const tomorrow = new Date();
    tomorrow.setDate(today.getDate() + 1);
    const tomorrowStr = getLocalDateString(tomorrow);
    
    if (targetDateStr <= todayStr) {
        return true;
    }
    
    if (targetDateStr === tomorrowStr) {
        const now = new Date();
        let [cutoffH, cutoffM] = cutoffTimeStr.split(":").map(Number);
        if (isNaN(cutoffH)) cutoffH = 20;
        if (isNaN(cutoffM)) cutoffM = 0;
        
        const cutoffDate = new Date();
        cutoffDate.setHours(cutoffH, cutoffM, 0, 0);
        
        if (now >= cutoffDate) {
            return true;
        }
    }
    
    return false;
}

// Handle action toggling
function onStudentStatusChange() {
    const select = document.getElementById("ctrl-meal-status");
    if (!select) return;
    const newStatus = select.value;
    const targetChangeDate = window._targetChangeDate;
    if (!targetChangeDate) return;
    
    const guestHallId = document.getElementById("guest-hall-select").value;
    const isSwappedGuest = guestHallId && guestHallId !== "" && !studentInfo.home_hall_active;
    
    apiFetch(isSwappedGuest ? `/student/guest-meal/toggle?target_hall_id=${guestHallId}` : "/student/meal-status/toggle", {
        method: "POST",
        body: { date: targetChangeDate, status: newStatus }
    }).then(response => {
        showBanner(response.message);
        loadStudentDashboard();
    }).catch(e => {
        showBanner(e.message, true);
        loadStudentDashboard();
    });
}

// For backward compatibility with toggle buttons
async function handleControlToggle(dateStr, type, currentState) {
    const targetMeal = studentInfo.meals[dateStr] || { status: "off" };
    let lunchOn = ["both", "lunch_only"].includes(targetMeal.status);
    let dinnerOn = ["both", "dinner_only"].includes(targetMeal.status);
    
    if (type === 'lunch') {
        lunchOn = !currentState;
    } else {
        dinnerOn = !currentState;
    }
    
    let newStatus = "off";
    if (lunchOn && dinnerOn) newStatus = "both";
    else if (lunchOn) newStatus = "lunch_only";
    else if (dinnerOn) newStatus = "dinner_only";
    
    const guestHallId = document.getElementById("guest-hall-select").value;
    const isSwappedGuest = guestHallId && guestHallId !== "" && !studentInfo.home_hall_active;
    
    try {
        let response;
        if (isSwappedGuest) {
            response = await apiFetch(`/student/guest-meal/toggle?target_hall_id=${guestHallId}`, {
                method: "POST",
                body: { date: dateStr, status: newStatus }
            });
        } else {
            response = await apiFetch("/student/meal-status/toggle", {
                method: "POST",
                body: { date: dateStr, status: newStatus }
            });
        }
        
        showBanner(response.message);
        await loadStudentDashboard();
    } catch (e) {
        showBanner(e.message, true);
        await loadStudentDashboard();
    }
}

// Validate and confirm guest hall selection
async function confirmGuestHall() {
    const hallId = document.getElementById("guest-hall-select").value;
    if (!hallId) {
        showBanner("Please select a target hall.", true);
        return;
    }
    const hallsResponse = await fetch(`${API_PREFIX}/student/halls`);
    const hallsList = await hallsResponse.json();
    const hall = hallsList.find(h => h.id == hallId);
    const hallName = hall ? hall.name : "selected hall";
    showBanner(`Guest hall set to ${hallName}. Use the controller above to schedule guest meals.`);
}

// Render read-only calendar preview (next 7 days)
function renderMealGrid(meals) {
    const grid = document.getElementById("student-meal-grid");
    grid.innerHTML = "";
    
    const dates = Object.keys(meals).sort();
    
    // Preview only the next 7 days
    const previewDates = dates.slice(0, 7);
    
    previewDates.forEach(dStr => {
        const item = meals[dStr];
        const dateObj = new Date(dStr);
        const dayName = dateObj.toLocaleDateString('en-US', { weekday: 'short' });
        const dayNum = dateObj.toLocaleDateString('en-US', { day: 'numeric', month: 'short' });
        
        const lunchOn = ["both", "lunch_only", "double", "triple"].includes(item.status);
        const dinnerOn = ["both", "dinner_only", "double", "triple"].includes(item.status);
        const isGuest = item.is_guest;
        
        const statusLabel = { both: "Both", lunch_only: "Lunch", dinner_only: "Dinner", double: "Double", triple: "Triple", off: "Off" };
        const lunchLabel = item.status === "double" || item.status === "triple" ? statusLabel[item.status] : (lunchOn ? "Active" : "Off");
        const dinnerLabel = item.status === "double" || item.status === "triple" ? statusLabel[item.status] : (dinnerOn ? "Active" : "Off");
        
        const card = document.createElement("div");
        card.className = "glass-card p-3.5 rounded-2xl flex flex-col justify-between space-y-3 bg-slate-900/30 text-center";
        
        card.innerHTML = `
            <div>
                <span class="text-[9px] text-slate-500 uppercase tracking-widest font-black block">${dayName}</span>
                <span class="text-xs font-bold text-white">${dayNum}</span>
            </div>
            
            <div class="space-y-1 bg-slate-950/20 p-2 rounded-xl border border-slate-800 text-[10px] text-left">
                <div class="flex items-center justify-between">
                    <span class="text-slate-400">Lunch</span>
                    <span class="${lunchOn ? 'text-emerald-400 font-bold' : 'text-slate-600'}">${lunchLabel}</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-slate-400">Dinner</span>
                    <span class="${dinnerOn ? 'text-emerald-400 font-bold' : 'text-slate-600'}">${dinnerLabel}</span>
                </div>
            </div>
            ${isGuest && item.status !== 'off' ? `
                <div class="text-[8px] font-bold text-cyan-400 uppercase tracking-wider">Guest Meal</div>
            ` : ''}
        `;
        
        grid.appendChild(card);
    });
}


// ==========================================
// MANAGER PORTAL LOGIC
// ==========================================
let activeManagerTab = "ops";

async function loadManagerDashboard() {
    try {
        // Fire all independent API calls in parallel
        const [cycle, summary] = await Promise.all([
            apiFetch("/manager/cycle/active"),
            apiFetch("/manager/financial-summary")
        ]);
        managerActiveCycle = cycle;
        
        // Fire remaining parallel calls (students, dashboard-info) - fire-and-forget UI updates
        Promise.all([
            apiFetch("/manager/students").then(data => { managerStudents = data; }).catch(() => {}),
            apiFetch("/student/dashboard-info").then(dashInfo => {
                const b = parseFloat(dashInfo?.cycle_balance) || 0;
                const s1 = document.getElementById("header-balance-amount");
                if (s1) { s1.textContent = (b < 0 ? '-BDT ' : 'BDT ') + Math.abs(b).toFixed(2); s1.className = s1.className.replace(/text-\w+(-\d+)?/g,'').trim() + (b>=0?' text-emerald-400':' text-rose-400')+' font-bold'; }
                const s2 = document.getElementById("mobile-balance");
                if (s2) { s2.textContent = (b < 0 ? '-BDT ' : 'BDT ') + Math.abs(b).toFixed(2); s2.className = s2.className.replace(/text-\w+(-\d+)?/g,'').trim() + (b>=0?' text-emerald-400':' text-rose-400')+' font-bold'; }
            }).catch(() => {})
        ]);
        
        const monthDisplay = document.getElementById("manager-cycle-month-display");
        const statusBadge = document.getElementById("manager-cycle-status-badge");
        const btnCreate = document.getElementById("btn-create-cycle");
        const btnActivate = document.getElementById("btn-activate-cycle");
        const btnClose = document.getElementById("btn-close-cycle");
        const btnReopen = document.getElementById("btn-reopen-cycle");
        const btnReset = document.getElementById("btn-reset-cycle");
        
        if (cycle && cycle.month) {
            monthDisplay.textContent = `Cycle: ${cycle.month}`;
            statusBadge.textContent = cycle.status.toUpperCase();
            
            if (cycle.status === 'active') {
                statusBadge.className = 'px-2.5 py-0.5 text-xs font-bold rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
            } else if (cycle.status === 'poll') {
                statusBadge.className = 'px-2.5 py-0.5 text-xs font-bold rounded-full bg-yellow-500/10 text-yellow-400 border border-yellow-500/20';
            } else {
                statusBadge.className = 'px-2.5 py-0.5 text-xs font-bold rounded-full bg-slate-800 text-slate-400 border border-slate-700/50';
            }
            
            if (cycle.status === "poll") {
                btnCreate.classList.add("hidden");
                btnActivate.classList.remove("hidden");
                btnClose.classList.add("hidden");
                btnReopen.classList.add("hidden");
                btnReset.classList.remove("hidden");
            } else if (cycle.status === "active") {
                btnCreate.classList.add("hidden");
                btnActivate.classList.add("hidden");
                btnClose.classList.remove("hidden");
                btnReopen.classList.add("hidden");
                btnReset.classList.remove("hidden");
            } else if (cycle.status === "closed") {
                btnCreate.classList.remove("hidden");
                btnActivate.classList.add("hidden");
                btnClose.classList.add("hidden");
                btnReopen.classList.remove("hidden");
                btnReset.classList.add("hidden");
            }
        } else {
            monthDisplay.textContent = "No Active Cycle";
            statusBadge.textContent = "OFFLINE";
            statusBadge.className = "px-2.5 py-0.5 text-xs font-bold rounded-full bg-slate-800 text-slate-400";
            
            btnCreate.classList.remove("hidden");
            btnActivate.classList.add("hidden");
            btnClose.classList.add("hidden");
            btnReopen.classList.add("hidden");
            btnReset.classList.add("hidden");
        }
        
        // Apply financial summary to UI
        const applyMC = (id, val, cls) => { const e = document.getElementById(id); if (e) { e.textContent = 'BDT ' + Math.abs(val).toFixed(2); e.className = e.className.replace(/text-\w+(-\d+)?/g,'').trim() + ' ' + cls + ' font-black text-2xl mt-1'; } };
        applyMC("metrics-expenses", summary.total_expenses, 'text-rose-400');
        applyMC("metrics-guests", summary.guest_contributions, 'text-slate-400');
        applyMC("metrics-rate", summary.meal_rate, 'text-slate-400');
        applyMC("metrics-rate-excl-fri", summary.meal_rate_excl_fri || 0, 'text-slate-400');
        const depEl = document.getElementById("metrics-deposits");
        if (depEl) { depEl.textContent = "BDT " + ((summary.total_deposits || 0)).toFixed(2); depEl.className = depEl.className.replace(/text-\w+(-\d+)?/g,'').trim() + ' text-emerald-400 font-black text-2xl mt-1'; }
        const rem = (summary.total_deposits || 0) - summary.total_expenses;
        const re = document.getElementById("metrics-remaining");
        if (re) { re.textContent = 'BDT ' + (rem < 0 ? '-' : '') + Math.abs(rem).toFixed(2); re.className = re.className.replace(/text-\w+(-\d+)?/g,'').trim() + (rem>=0?' text-emerald-400':' text-rose-400')+' font-black text-2xl mt-1'; }
        
        // Form default dates to today (only when empty — preserve user selections until refresh)
        const todayStr = getLocalDateString();
        if (!document.getElementById("dep-date").value) document.getElementById("dep-date").value = todayStr;
        if (!document.getElementById("exp-date").value) document.getElementById("exp-date").value = todayStr;
        if (!document.getElementById("sheet-date-select").value) document.getElementById("sheet-date-select").value = todayStr;
        if (!document.getElementById("exp-filter-date").value) document.getElementById("exp-filter-date").value = todayStr;
        if (!document.getElementById("dep-filter-date").value) document.getElementById("dep-filter-date").value = todayStr;

        // Init deposit entries
        document.getElementById("deposit-entries").innerHTML = "";
        depositEntryCount = 0;
        addDepositEntry();

        // Load tables based on active sub tab
        if (activeManagerTab === "ops") {
            await loadManagerExpenses();
        } else if (activeManagerTab === "deposits") {
            await loadManagerDeposits();
        } else if (activeManagerTab === "sheet") {
            await fetchPrintSheet();
        } else if (activeManagerTab === "summary") {
            await loadCycleSummaryTable();
        } else if (activeManagerTab === "rates") {
            await loadManagerRates();
        } else if (activeManagerTab === "settings" && cycle) {
            // Populate settings fields from cycle (now includes hall settings)
            document.getElementById("set-cutoff-time").value = cycle.cutoff_time || "20:00";
            document.getElementById("set-cycle-end-date").value = cycle.end_date || "";
            document.getElementById("set-lunch-perc").value = cycle.lunch_percentage || 0.5;
            document.getElementById("set-dinner-perc").value = cycle.dinner_percentage || 0.5;
            document.getElementById("set-mgr-fee").value = cycle.manager_charge_per_day || 5.0;
            document.getElementById("set-guest-fee").value = cycle.guest_charge_per_day || 5.0;
            document.getElementById("set-lunch-only-rate-pct").value = cycle.lunch_only_rate_percentage || 0.4;
            document.getElementById("set-dinner-only-rate-pct").value = cycle.dinner_only_rate_percentage || 0.6;
            // Populate full-rate days multi-select
            const frd = (cycle.full_rate_days || "4").split(",");
            const frdSelect = document.getElementById("set-full-rate-days");
            for (let opt of frdSelect.options) { opt.selected = frd.includes(opt.value); }
        }
        if (activeManagerTab === "settings") {
            loadSmtpConfig();
            loadPaymentNumbers();
            loadEmailTemplates();
            loadFeeOverrides();
        }
    } catch (e) {
        showBanner(e.message, true);
    }
}

// ─── Profit Tab ──────────────────────────────────────────────────────────────

async function loadManagerProfit() {
    const tbody = document.getElementById("profit-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-500 text-xs"><i class="fa-solid fa-circle-notch fa-spin mr-1"></i>Loading...</td></tr>`;
    try {
        const data = await apiFetch("/manager/profit");
        if (!data.has_active_cycle) {
            tbody.innerHTML = `<tr><td colspan="9" class="py-6 text-center text-slate-500 text-xs">No active cycle. Start a cycle first.</td></tr>`;
            document.getElementById("profit-home-amount").textContent = "BDT 0.00";
            document.getElementById("profit-guest-amount").textContent = "BDT 0.00";
            document.getElementById("profit-total-amount").textContent = "BDT 0.00";
            document.getElementById("profit-recovery-amount").textContent = "BDT 0.00";
            document.getElementById("profit-recovery-detail").textContent = "Revenue: BDT 0 / Expenses: BDT 0";
            return;
        }
        document.getElementById("profit-home-amount").textContent = `BDT ${data.profit_from_home.toFixed(2)}`;
        document.getElementById("profit-guest-amount").textContent = `BDT ${data.profit_from_guests.toFixed(2)}`;
        document.getElementById("profit-total-amount").textContent = `BDT ${data.total_profit.toFixed(2)}`;
        document.getElementById("profit-month").textContent = `Cycle: ${data.month}`;
        document.getElementById("profit-recovery-amount").textContent = `BDT ${data.total_rate_surplus.toFixed(2)}`;
        document.getElementById("profit-recovery-detail").textContent = `Revenue: BDT ${data.total_rate_revenue.toFixed(2)} / Expenses: BDT ${data.total_expenses.toFixed(2)}`;
        const recoveryColor = data.total_rate_surplus >= 0 ? 'text-emerald-400' : 'text-rose-500';
        document.getElementById("profit-recovery-amount").className = `text-2xl font-extrabold ${recoveryColor} mt-1`;

        // Summation counts
        let totalHomeDays = 0, totalGuestDays = 0;
        data.daily_breakdown.forEach(d => { totalHomeDays += d.home_active_count; totalGuestDays += d.guest_active_count; });
        document.getElementById("profit-home-count").textContent = `${totalHomeDays} active student-days`;
        document.getElementById("profit-guest-count").textContent = `${totalGuestDays} active guest-days`;
        document.getElementById("profit-mgr-rate").textContent = `BDT ${data.daily_breakdown.length > 0 && data.daily_breakdown[0].home_active_count > 0 ? (data.daily_breakdown.find(d => d.home_active_count > 0)?.home_profit / (data.daily_breakdown.find(d => d.home_active_count > 0)?.home_active_count || 1) || 0).toFixed(2) : "5.00"}`;


        tbody.innerHTML = data.daily_breakdown.map(d => {
            const surplusColor = d.rate_surplus >= 0 ? 'text-emerald-400' : 'text-rose-500';
            return `
            <tr class="hover:bg-slate-900/30">
                <td class="py-2.5 px-3 font-semibold text-slate-300">${d.date}</td>
                <td class="py-2.5 px-3 text-right text-slate-400">BDT ${d.expenses.toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right text-blue-400 font-bold">BDT ${d.rate_revenue.toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right font-bold ${surplusColor}">BDT ${d.rate_surplus.toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right text-slate-400">${d.home_active_count}</td>
                <td class="py-2.5 px-3 text-right text-emerald-400 font-bold">BDT ${d.home_profit.toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right text-slate-400">${d.guest_active_count}</td>
                <td class="py-2.5 px-3 text-right text-cyan-400 font-bold">BDT ${d.guest_profit.toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right text-amber-400 font-bold">BDT ${d.day_total.toFixed(2)}</td>
            </tr>`;
        }).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="9" class="py-6 text-center text-red-400 text-xs">Failed to load profit data.</td></tr>`;
        showBanner(e.message, true);
    }
}

// ─── Preferences Tab ──────────────────────────────────────────────────────────

let prefsData = [];

let mfData = null;

function renderMoneyFlowList(data) {
    const negList = document.getElementById("mf-negative-list");
    const posList = document.getElementById("mf-positive-list");
    if (!negList || !posList) return;
    
    const negQ = (document.getElementById("mf-neg-search").value || "").toLowerCase();
    const negF = document.getElementById("mf-neg-filter").value;
    const posQ = (document.getElementById("mf-pos-search").value || "").toLowerCase();
    const posF = document.getElementById("mf-pos-filter").value;
    
    const negFiltered = data.users_negative_list.filter(u =>
        (negF === "all" || u.user_type === negF) &&
        (!negQ || u.name.toLowerCase().includes(negQ) || u.username.toLowerCase().includes(negQ))
    );
    const posFiltered = data.users_positive_list.filter(u =>
        (posF === "all" || u.user_type === posF) &&
        (!posQ || u.name.toLowerCase().includes(posQ) || u.username.toLowerCase().includes(posQ))
    );
    
    negList.innerHTML = negFiltered.length
        ? negFiltered.map(u =>
            `<tr>
                <td class="py-1.5 pr-2 text-slate-300">${escapeHtml(u.name)} <span class="text-[10px] ${u.user_type === 'guest' ? 'text-amber-400' : 'text-sky-400'}">(${u.user_type})</span></td>
                <td class="py-1.5 text-right text-rose-400 font-bold">BDT ${u.balance.toFixed(2)}</td>
                <td class="py-1.5 text-right">
                    <div class="flex items-center justify-end gap-1">
                        <input id="mf-dep-inp-${u.id}" type="number" step="any" min="1" placeholder="amount" class="w-20 text-xs rounded bg-slate-800 border border-slate-700 py-1 px-2 text-white focus:outline-none focus:border-emerald-500">
                        <select id="mf-dep-method-${u.id}" class="text-[10px] rounded bg-slate-800 border border-slate-700 py-1 px-1 text-white focus:outline-none focus:border-emerald-500">
                            <option value="Cash">Cash</option>
                            <option value="Mobile Banking">Mobile Banking</option>
                            <option value="Card">Card</option>
                            <option value="Bank">Bank</option>
                        </select>
                        <button onclick="quickDeposit('${escapeHtml(u.username)}', '${escapeHtml(u.name)}', ${u.id})" class="text-[10px] bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-1 px-2 rounded transition whitespace-nowrap">Deposit</button>
                    </div>
                </td>
            </tr>`
        ).join("")
        : '<tr><td colspan="3" class="py-4 text-center text-slate-500">No matching users</td></tr>';
    
    posList.innerHTML = posFiltered.length
        ? posFiltered.map(u =>
            `<tr>
                <td class="py-1.5 pr-2 text-slate-300">${escapeHtml(u.name)} <span class="text-[10px] ${u.user_type === 'guest' ? 'text-amber-400' : 'text-sky-400'}">(${u.user_type})</span></td>
                <td class="py-1.5 text-right text-emerald-400 font-bold">BDT ${u.balance.toFixed(2)}</td>
                <td class="py-1.5 text-right">
                    <div class="flex items-center justify-end gap-1">
                        <input id="mf-pay-inp-${u.id}" type="number" step="any" min="1" placeholder="amount" class="w-20 text-xs rounded bg-slate-800 border border-slate-700 py-1 px-2 text-white focus:outline-none focus:border-emerald-500">
                        <button onclick="payUser(${u.id}, ${u.balance}, '${escapeHtml(u.name)}')" class="text-[10px] bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-1 px-2 rounded transition whitespace-nowrap">Pay</button>
                    </div>
                </td>
            </tr>`
        ).join("")
        : '<tr><td colspan="3" class="py-4 text-center text-slate-500">No matching users</td></tr>';
}

function filterMoneyFlow() {
    if (mfData) renderMoneyFlowList(mfData);
}

async function loadMoneyFlow() {
    const negList = document.getElementById("mf-negative-list");
    const posList = document.getElementById("mf-positive-list");
    if (!negList || !posList) return;
    try {
        const data = await apiFetch("/manager/money-flow");
        mfData = data;
        if (!data.has_active_cycle) {
            document.getElementById("mf-total-deposits").textContent = "BDT 0.00";
            document.getElementById("mf-cash-deposits").textContent = "BDT 0.00";
            document.getElementById("mf-non-cash-deposits").textContent = "BDT 0.00";
            document.getElementById("mf-cashout-amount").textContent = "BDT 0.00";
            document.getElementById("mf-total-expenses").textContent = "BDT 0.00";
            document.getElementById("mf-paid-expenses").textContent = "BDT 0.00";
            document.getElementById("mf-unpaid-expenses").textContent = "BDT 0.00";
            document.getElementById("mf-total-bkash").textContent = "BDT 0.00";
            document.getElementById("mf-inventory-payments").textContent = "BDT 0.00";
            document.getElementById("mf-net-operating").textContent = "BDT 0.00";
            document.getElementById("mf-negative-total").textContent = "BDT 0.00";
            document.getElementById("mf-positive-total").textContent = "BDT 0.00";
            document.getElementById("mf-negative-count").textContent = "";
            document.getElementById("mf-positive-count").textContent = "";
            document.getElementById("mf-net-cash").textContent = "BDT 0.00";
            negList.innerHTML = '<tr><td colspan="3" class="py-4 text-center text-slate-500">No active cycle</td></tr>';
            posList.innerHTML = '<tr><td colspan="3" class="py-4 text-center text-slate-500">No active cycle</td></tr>';
            return;
        }
        
        document.getElementById("mf-total-deposits").textContent = `BDT ${data.total_deposits.toFixed(2)}`;
        document.getElementById("mf-cash-deposits").textContent = `BDT ${data.cash_deposits.toFixed(2)}`;
        document.getElementById("mf-non-cash-deposits").textContent = `BDT ${data.non_cash_deposits.toFixed(2)}`;
        document.getElementById("mf-cashout-amount").textContent = `BDT ${data.cashout.toFixed(2)}`;
        document.getElementById("mf-total-expenses").textContent = `BDT ${data.total_expenses.toFixed(2)}`;
        document.getElementById("mf-paid-expenses").textContent = `BDT ${data.paid_expenses.toFixed(2)}`;
        document.getElementById("mf-unpaid-expenses").textContent = `BDT ${data.unpaid_expenses.toFixed(2)}`;
        document.getElementById("mf-total-bkash").textContent = `BDT ${data.total_bkash_approved.toFixed(2)}`;
        document.getElementById("mf-net-operating").textContent = `BDT ${data.net_operating.toFixed(2)}`;
        document.getElementById("mf-negative-total").textContent = `BDT ${data.users_negative_total.toFixed(2)}`;
        document.getElementById("mf-positive-total").textContent = `BDT ${data.users_positive_total.toFixed(2)}`;
        document.getElementById("mf-negative-count").textContent = `${data.users_negative_count} user(s)`;
        document.getElementById("mf-positive-count").textContent = `${data.users_positive_count} user(s)`;
        
        const netCash = data.cash_deposits + data.total_bkash_approved - data.total_expenses - data.users_positive_total;
        document.getElementById("mf-net-cash").textContent = `BDT ${netCash.toFixed(2)}`;
        
        const payDate = document.getElementById("inv-pay-date");
        if (payDate && !payDate.value) payDate.value = new Date().toISOString().slice(0, 10);
        
        renderMoneyFlowList(data);
    } catch (e) {
        showBanner("Failed to load money flow: " + e.message, true);
    }
}

async function loadCashouts() {
    const tbody = document.getElementById("cashout-list");
    if (!tbody) return;
    try {
        const cashouts = await apiFetch("/manager/cashouts");
        const total = cashouts.reduce((s, c) => s + c.amount, 0);
        document.getElementById("mf-cashout-amount").textContent = `BDT ${total.toFixed(2)}`;
        tbody.innerHTML = cashouts.length
            ? cashouts.map(c => `
                <tr class="text-xs hover:bg-slate-900/30">
                    <td class="py-1.5 pr-2 text-slate-300">${c.date}</td>
                    <td class="py-1.5 pr-2 text-right text-cyan-400 font-bold">BDT ${c.amount.toFixed(2)}</td>
                    <td class="py-1.5 pr-2 text-slate-400">${c.from_method}</td>
                    <td class="py-1.5 pr-2 text-slate-500">${escapeHtml(c.notes || '')}</td>
                    <td class="py-1.5 text-right">
                        <button onclick="editCashout(${c.id})" class="text-[10px] text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 px-1.5 py-0.5 rounded transition mr-1"><i class="fa-solid fa-pen"></i></button>
                        <button onclick="deleteCashout(${c.id})" class="text-[10px] text-rose-400 hover:text-rose-300 bg-rose-500/10 hover:bg-rose-500/20 px-1.5 py-0.5 rounded transition"><i class="fa-solid fa-trash-can"></i></button>
                    </td>
                </tr>`).join("")
            : '<tr><td colspan="5" class="py-4 text-center text-slate-500">No cashouts recorded</td></tr>';
    } catch (e) { showBanner(e.message, true); }
}

async function addCashout(e) {
    e.preventDefault();
    const body = {
        date: document.getElementById("cashout-date").value,
        amount: parseFloat(document.getElementById("cashout-amount").value),
        from_method: document.getElementById("cashout-method").value,
        notes: document.getElementById("cashout-notes").value.trim()
    };
    if (!body.date || !body.amount || body.amount <= 0) { showBanner("Fill date and amount.", true); return; }
    try {
        await apiFetch("/manager/cashouts", { method: "POST", body });
        const keepDate = document.getElementById("cashout-date").value;
        document.getElementById("cashout-form").reset();
        document.getElementById("cashout-date").value = keepDate || new Date().toISOString().slice(0, 10);
        await loadCashouts();
        showBanner("Cashout added.");
    } catch (e) { showBanner(e.message, true); }
}

async function editCashout(id) {
    const cashouts = await apiFetch("/manager/cashouts");
    const c = cashouts.find(x => x.id === id);
    if (!c) return;
    document.getElementById("cashout-date").value = c.date;
    document.getElementById("cashout-amount").value = c.amount;
    document.getElementById("cashout-method").value = c.from_method;
    document.getElementById("cashout-notes").value = c.notes || "";
    const form = document.getElementById("cashout-form");
    form.onsubmit = async (e) => {
        e.preventDefault();
        const body = {
            date: document.getElementById("cashout-date").value,
            amount: parseFloat(document.getElementById("cashout-amount").value),
            from_method: document.getElementById("cashout-method").value,
            notes: document.getElementById("cashout-notes").value.trim()
        };
        try {
            await apiFetch(`/manager/cashouts/${id}`, { method: "PUT", body });
            form.onsubmit = addCashout;
            const keepDate = document.getElementById("cashout-date").value;
            form.reset();
            document.getElementById("cashout-date").value = keepDate || new Date().toISOString().slice(0, 10);
            await loadCashouts();
            showBanner("Cashout updated.");
        } catch (e) { showBanner(e.message, true); }
    };
}

async function deleteCashout(id) {
    if (!confirm("Delete this cashout?")) return;
    try {
        await apiFetch(`/manager/cashouts/${id}`, { method: "DELETE" });
        await loadCashouts();
        showBanner("Cashout deleted.");
    } catch (e) { showBanner(e.message, true); }
}

async function quickDeposit(username, userName, userId) {
    const inp = document.getElementById(`mf-dep-inp-${userId}`);
    const methodEl = document.getElementById(`mf-dep-method-${userId}`);
    if (!inp || !methodEl) return;
    const amount = parseFloat(inp.value);
    if (!amount || amount <= 0) { showBanner("Enter a valid amount.", true); return; }
    const method = methodEl.value;
    const today = new Date().toISOString().slice(0, 10);
    try {
        await apiFetch("/manager/deposit", {
            method: "POST",
            body: { username, amount, date: today, description: `${method} Deposit` }
        });
        inp.value = "";
        showBanner(`BDT ${amount.toFixed(2)} deposited via ${method}.`);
        await loadMoneyFlow();
    } catch (e) {
        showBanner(e.message, true);
    }
}

async function loadInventoryPayments() {
    const tbody = document.getElementById("inv-payments-list");
    if (!tbody) return;
    try {
        const payments = await apiFetch("/manager/inventory-payments");
        const total = payments.reduce((s, p) => s + p.amount, 0);
        document.getElementById("mf-inventory-payments").textContent = `BDT ${total.toFixed(2)}`;
        tbody.innerHTML = payments.length
            ? payments.map(p => `
                <tr class="text-xs hover:bg-slate-900/30">
                    <td class="py-1.5 pr-2 text-slate-300">${p.date}</td>
                    <td class="py-1.5 pr-2 text-white">${escapeHtml(p.paid_to)}</td>
                    <td class="py-1.5 pr-2 text-slate-400">${p.method}</td>
                    <td class="py-1.5 pr-2 text-right text-purple-400 font-bold">BDT ${p.amount.toFixed(2)}</td>
                    <td class="py-1.5 pr-2 text-slate-500">${escapeHtml(p.notes || '')}</td>
                    <td class="py-1.5 text-right">
                        <button onclick="editInventoryPayment(${p.id})" class="text-[10px] text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 px-1.5 py-0.5 rounded transition mr-1"><i class="fa-solid fa-pen"></i></button>
                        <button onclick="deleteInventoryPayment(${p.id})" class="text-[10px] text-rose-400 hover:text-rose-300 bg-rose-500/10 hover:bg-rose-500/20 px-1.5 py-0.5 rounded transition"><i class="fa-solid fa-trash-can"></i></button>
                    </td>
                </tr>`).join("")
            : '<tr><td colspan="6" class="py-4 text-center text-slate-500">No payments recorded</td></tr>';
    } catch (e) { showBanner(e.message, true); }
}

async function addInventoryPayment(e) {
    e.preventDefault();
    const body = {
        date: document.getElementById("inv-pay-date").value,
        paid_to: document.getElementById("inv-pay-to").value.trim(),
        method: document.getElementById("inv-pay-method").value,
        amount: parseFloat(document.getElementById("inv-pay-amount").value),
        notes: document.getElementById("inv-pay-notes").value.trim()
    };
    if (!body.date || !body.paid_to || !body.amount || body.amount <= 0) { showBanner("Fill in all required fields.", true); return; }
    try {
        await apiFetch("/manager/inventory-payments", { method: "POST", body });
        const keepDate = document.getElementById("inv-pay-date").value;
        document.getElementById("inv-payment-form").reset();
        document.getElementById("inv-pay-date").value = keepDate || new Date().toISOString().slice(0, 10);
        await loadInventoryPayments();
        await loadMoneyFlow();
        showBanner("Payment added.");
    } catch (e) { showBanner(e.message, true); }
}

async function editInventoryPayment(id) {
    const payments = await apiFetch("/manager/inventory-payments");
    const p = payments.find(x => x.id === id);
    if (!p) return;
    document.getElementById("inv-pay-date").value = p.date;
    document.getElementById("inv-pay-to").value = p.paid_to;
    document.getElementById("inv-pay-method").value = p.method;
    document.getElementById("inv-pay-amount").value = p.amount;
    document.getElementById("inv-pay-notes").value = p.notes || "";
    const form = document.getElementById("inv-payment-form");
    form.onsubmit = async (e) => {
        e.preventDefault();
        const body = {
            date: document.getElementById("inv-pay-date").value,
            paid_to: document.getElementById("inv-pay-to").value.trim(),
            method: document.getElementById("inv-pay-method").value,
            amount: parseFloat(document.getElementById("inv-pay-amount").value),
            notes: document.getElementById("inv-pay-notes").value.trim()
        };
        try {
            await apiFetch(`/manager/inventory-payments/${id}`, { method: "PUT", body });
            form.onsubmit = addInventoryPayment;
            const keepDate = document.getElementById("inv-pay-date").value;
            form.reset();
            document.getElementById("inv-pay-date").value = keepDate || new Date().toISOString().slice(0, 10);
            await loadInventoryPayments();
            await loadMoneyFlow();
            showBanner("Payment updated.");
        } catch (e) { showBanner(e.message, true); }
    };
}

async function deleteInventoryPayment(id) {
    if (!confirm("Delete this payment?")) return;
    try {
        await apiFetch(`/manager/inventory-payments/${id}`, { method: "DELETE" });
        await loadInventoryPayments();
        await loadMoneyFlow();
        showBanner("Payment deleted.");
    } catch (e) { showBanner(e.message, true); }
}

async function payUser(userId, maxAmount, userName) {
    const inp = document.getElementById(`mf-pay-inp-${userId}`);
    if (!inp) return;
    const amount = parseFloat(inp.value);
    if (!amount || amount <= 0) { showBanner("Enter a valid amount.", true); return; }
    // Flexible: allow any amount (not capped to displayed positive balance)
    try {
        const res = await apiFetch(`/manager/money-flow/pay?user_id=${userId}&amount=${amount}`, { method: "POST" });
        inp.value = "";
        showBanner(res.message);
        await loadMoneyFlow();
    } catch (e) {
        showBanner(e.message, true);
    }
}

async function loadManagerPrefs() {
    const tbody = document.getElementById("prefs-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="4" class="py-6 text-center text-slate-500 text-xs"><i class="fa-solid fa-circle-notch fa-spin mr-1"></i>Loading...</td></tr>`;
    try {
        if (!managerStudents || managerStudents.length === 0) {
            managerStudents = await apiFetch("/manager/students");
        }
        prefsData = managerStudents;
        // Fetch today's active user IDs for filtering
        const today = getLocalDateString();
        const activeSheet = await apiFetch("/manager/student-meals?date_str=" + today);
        window._activeUserIds = new Set(activeSheet.filter(i => i.status !== "off").map(i => i.user_id));
        renderPrefsTable(prefsData);
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="py-6 text-center text-red-400 text-xs">Failed to load students.</td></tr>`;
    }
}

function renderPrefsTable(data) {
    const tbody = document.getElementById("prefs-tbody");
    if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="py-6 text-center text-slate-500">No students found.</td></tr>`;
        return;
    }
    const fishLabels = { normal: "Normal", if_pangas_then_egg: "Pangas→Egg", egg_instead_of_fish: "Egg instead of Fish" };
    const meatLabels = { normal: "Normal", beef: "Beef", mutton: "Mutton" };
    tbody.innerHTML = data.map(s => {
        const fv = s.fish_egg_pref || "normal";
        const mv = s.meat_pref || "normal";
        return `
            <tr class="hover:bg-slate-900/30">
                <td class="py-2 px-3 font-semibold text-white text-xs">${s.room_number || 'N/A'}</td>
                <td class="py-2 px-3 text-xs">${s.name} (<span class="text-slate-400">${s.username}</span>)</td>
                <td class="py-2 px-3">
                    <select onchange="updatePrefFishEgg(${s.id}, this.value)" class="w-full rounded-xl bg-slate-950 border border-slate-800 text-white text-xs py-1.5 px-2 focus:outline-none focus:border-emerald-500">
                        ${Object.entries(fishLabels).map(([v, l]) => `<option value="${v}" ${fv === v ? 'selected' : ''}>${l}</option>`).join("")}
                    </select>
                </td>
                <td class="py-2 px-3">
                    <select onchange="updatePrefMeat(${s.id}, this.value)" class="w-full rounded-xl bg-slate-950 border border-slate-800 text-white text-xs py-1.5 px-2 focus:outline-none focus:border-emerald-500">
                        ${Object.entries(meatLabels).map(([v, l]) => `<option value="${v}" ${mv === v ? 'selected' : ''}>${l}</option>`).join("")}
                    </select>
                </td>
            </tr>`;
    }).join("");
}

function filterPrefsTable() {
    const query = document.getElementById("prefs-search").value.toLowerCase().trim();
    const prefFilter = document.getElementById("prefs-filter").value;
    const activeOnly = document.getElementById("prefs-active-only").checked;
    let filtered = prefsData;
    // Active only filter
    if (activeOnly && window._activeUserIds) {
        filtered = filtered.filter(s => window._activeUserIds.has(s.id));
    }
    // Preference filter
    if (prefFilter) {
        filtered = filtered.filter(s =>
            (s.fish_egg_pref || "normal") === prefFilter ||
            (s.meat_pref || "normal") === prefFilter
        );
    }
    // Search text filter
    if (query) {
        filtered = filtered.filter(s =>
            (s.name && s.name.toLowerCase().includes(query)) ||
            (s.username && s.username.toLowerCase().includes(query)) ||
            (s.room_number && s.room_number.toLowerCase().includes(query))
        );
    }
    renderPrefsTable(filtered);
}

async function updatePrefFishEgg(userId, value) {
    try {
        await apiFetch(`/manager/students/${userId}/preferences`, {
            method: "PUT",
            body: { fish_egg_pref: value }
        });
        const student = prefsData.find(s => s.id === userId);
        if (student) student.fish_egg_pref = value;
        if (managerStudents) {
            const ms = managerStudents.find(s => s.id === userId);
            if (ms) ms.fish_egg_pref = value;
        }
    } catch (e) {
        showBanner(e.message, true);
    }
}

async function updatePrefMeat(userId, value) {
    try {
        await apiFetch(`/manager/students/${userId}/preferences`, {
            method: "PUT",
            body: { meat_pref: value }
        });
        const student = prefsData.find(s => s.id === userId);
        if (student) student.meat_pref = value;
        if (managerStudents) {
            const ms = managerStudents.find(s => s.id === userId);
            if (ms) ms.meat_pref = value;
        }
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Toggle Sub Tabs inside Manager
function toggleManagerTab(tab, element) {
    activeManagerTab = tab;
    localStorage.setItem("edining_mgr_tab", tab);
    
    // Manage active style
    const btns = document.querySelectorAll(".mgr-tab-btn");
    btns.forEach(b => {
        b.className = "mgr-tab-btn py-4 px-6 text-sm font-bold text-slate-400 border-b-2 border-transparent hover:text-white focus:outline-none";
    });
    element.className = "mgr-tab-btn py-4 px-6 text-sm font-bold text-emerald-400 border-b-2 border-emerald-500 focus:outline-none";
    
    // Manage elements visibility
    document.getElementById("mgr-tab-ops").classList.add("hidden");
    document.getElementById("mgr-tab-sheet").classList.add("hidden");
    document.getElementById("mgr-tab-summary").classList.add("hidden");
    document.getElementById("mgr-tab-rates").classList.add("hidden");
    document.getElementById("mgr-tab-settings").classList.add("hidden");
    document.getElementById("mgr-tab-bkash").classList.add("hidden");
    document.getElementById("mgr-tab-profit").classList.add("hidden");
    document.getElementById("mgr-tab-moneyflow").classList.add("hidden");
    document.getElementById("mgr-tab-deposits").classList.add("hidden");
    document.getElementById("mgr-tab-prefs").classList.add("hidden");
    
    document.getElementById(`mgr-tab-${tab}`).classList.remove("hidden");
    
    if (tab === 'bkash') {
        loadManagerBkashTransactions();
    } else if (tab === 'profit') {
        loadManagerProfit();
    } else if (tab === 'moneyflow') {
        loadMoneyFlow();
        loadInventoryPayments();
        loadCashouts();
    } else if (tab === 'deposits') {
        loadManagerDashboard();
    } else if (tab === 'prefs') {
        loadManagerPrefs();
    } else {
        loadManagerDashboard();
        if (tab === 'ops') {
            const dSelect = document.getElementById("print-ops-date-select");
            if (dSelect && !dSelect.value) {
                dSelect.value = getLocalDateString();
            }
        }
    }
}

// ─── bKash Payments Tab ───────────────────────────────────────────────────────

async function loadManagerBkashTransactions() {
    const tbody = document.getElementById('bkash-trx-tbody');
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-500 text-xs"><i class="fa-solid fa-circle-notch fa-spin mr-1"></i>Loading...</td></tr>`;
    try {
        const data = await apiFetch('/manager/bkash/transactions');
        if (!data || data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-500 text-xs">No transactions recorded yet.</td></tr>`;
            return;
        }
        tbody.innerHTML = data.map(t => {
            let statusCell = '';
            if (t.status === 'approved') {
                statusCell = `<span class="bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded text-[10px] font-bold">Approved BDT ${(t.approved_amount||t.amount).toFixed(2)}</span>
                    <button onclick="deleteBkashTrx('${t.trx_id}')" class="ml-1 text-[10px] text-rose-400 hover:text-rose-300" title="Delete"><i class="fa-solid fa-xmark"></i></button>`;
            } else if (t.status === 'pending' || t.is_claimed) {
                statusCell = `<span class="bg-yellow-500/10 text-yellow-400 px-2 py-0.5 rounded text-[10px] font-bold">Pending <i class="fa-solid fa-clock ml-1"></i></span>
                    <input type="number" id="amt-${t.trx_id}" value="${(t.amount||100).toFixed(2)}" step="0.01" class="bg-slate-950 border border-slate-700 text-white text-xs py-1 px-1.5 w-20 rounded text-right ml-1">
                    <button onclick="approveBkashTrx('${t.trx_id}')" class="ml-1 text-[10px] bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 px-1.5 py-0.5 rounded font-bold">Approve</button>
                    <button onclick="deleteBkashTrx('${t.trx_id}')" class="ml-1 text-[10px] text-rose-400 hover:text-rose-300" title="Delete"><i class="fa-solid fa-xmark"></i></button>`;
            } else {
                statusCell = `<span class="bg-slate-800 text-slate-400 px-2 py-0.5 rounded text-[10px] font-bold">Unclaimed</span>
                    <button onclick="deleteBkashTrx('${t.trx_id}')" class="ml-1 text-[10px] text-rose-400 hover:text-rose-300" title="Delete"><i class="fa-solid fa-xmark"></i></button>`;
            }
            return `
                <tr class="hover:bg-slate-900/30 text-xs">
                    <td class="py-2.5 px-3 text-slate-400">${escapeHtml(t.date_received)}</td>
                    <td class="py-2.5 px-3 font-mono font-bold text-pink-300 tracking-widest">${escapeHtml(t.trx_id)}</td>
                    <td class="py-2.5 px-3 text-slate-300">${escapeHtml(t.sender)}</td>
                    <td class="py-2.5 px-3 text-emerald-400 font-bold">BDT ${(t.approved_amount || t.amount).toFixed(2)}</td>
                    <td class="py-2.5 px-3">${t.claimed_by ? escapeHtml(t.claimed_by) : '-'}</td>
                    <td class="py-2.5 px-3">${statusCell}</td>
                </tr>`;
        }).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-red-400 text-xs">Failed to load transactions. Please try again.</td></tr>`;
    }
}

async function handleAddManualBkashTrx(event) {
    event.preventDefault();
    const alertEl = document.getElementById('bkash-form-alert');
    const btn = document.getElementById('btn-add-bkash-trx');
    const trxId = document.getElementById('bkash-trx-input').value.trim().toUpperCase();
    const amount = parseFloat(document.getElementById('bkash-amount-input').value);
    const senderRaw = document.getElementById('bkash-sender-input').value.trim();
    const sender = senderRaw || 'Manager';

    // Client-side validation
    if (!trxId || trxId.length !== 10 || !/^[A-Z0-9]{10}$/.test(trxId)) {
        showBkashAlert(alertEl, 'error', 'Transaction ID must be exactly 10 alphanumeric characters.');
        return;
    }
    if (!amount || amount <= 0) {
        showBkashAlert(alertEl, 'error', 'Amount must be a positive number.');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Adding...`;
    alertEl.classList.add('hidden');

    try {
        const result = await apiFetch('/manager/bkash/transactions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trx_id: trxId, amount: amount, sender: sender })
        });
        showBkashAlert(alertEl, 'success', `✓ Transaction ${result.trx_id} added successfully.`);
        document.getElementById('form-add-bkash-trx').reset();
        document.getElementById('bkash-sender-input').value = 'Manager';
        await loadManagerBkashTransactions();
    } catch (err) {
        const msg = err.message || 'Failed to add transaction.';
        showBkashAlert(alertEl, 'error', msg);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-plus-circle"></i> Add Transaction Record`;
    }
}

async function setManagerPin() {
    const pin = document.getElementById("manager-approve-pin").value.trim();
    if (pin.length !== 4 || !/^\d{4}$/.test(pin)) { showBanner("Enter a 4-digit PIN.", true); return; }
    try {
        await apiFetch("/manager/bkash/set-pin?pin=" + pin, { method: "POST" });
        showBanner("Manager PIN set successfully.");
    } catch (e) { showBanner(e.message, true); }
}

async function deleteBkashTrx(trxId) {
    if (!confirm("Delete transaction " + trxId + "? This reverses the deposit if approved.")) return;
    try {
        await apiFetch("/manager/bkash/transactions/" + trxId, { method: "DELETE" });
        showBanner("Transaction deleted.");
        await loadManagerBkashTransactions();
    } catch (e) { showBanner(e.message, true); }
}

async function approveBkashTrx(trxId) {
    const amtInput = document.getElementById("amt-" + trxId);
    const amt = parseFloat(amtInput ? amtInput.value : "100");
    if (!amt || amt <= 0) { showBanner("Enter a valid amount.", true); return; }
    try {
        const result = await apiFetch("/manager/bkash/approve?trx_id=" + trxId + "&amount=" + amt, { method: "POST" });
        showBanner(result.message);
        await loadManagerBkashTransactions();
    } catch (e) {
        showBanner(e.message, true);
    }
}

function showBkashAlert(el, type, message) {
    el.textContent = message;
    el.className = type === 'success'
        ? 'text-xs rounded-xl px-4 py-2.5 font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
        : 'text-xs rounded-xl px-4 py-2.5 font-semibold bg-red-500/10 text-red-400 border border-red-500/30';
    el.classList.remove('hidden');
}

function escapeHtml(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Load current month's expenses
async function loadManagerExpenses() {
    try {
        const dateFilter = document.getElementById("exp-filter-date").value;
        const url = dateFilter ? `/manager/expenses?date=${dateFilter}` : "/manager/expenses";
        const expenses = await apiFetch(url);
        const tbody = document.getElementById("mgr-expenses-tbody");
        if (expenses.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-xs text-slate-500">No expenses recorded for this cycle yet.</td></tr>`;
        } else {
            const mealBadge = { lunch: 'text-yellow-400 bg-yellow-400/10', dinner: 'text-orange-400 bg-orange-400/10', both: 'text-slate-400 bg-slate-700/50' };
            tbody.innerHTML = expenses.map(e => {
                const mt = (e.meal_type || 'both').toLowerCase();
                const label = mt.charAt(0).toUpperCase() + mt.slice(1);
                const cls = mealBadge[mt] || mealBadge['both'];
                return `
                <tr class="hover:bg-slate-900/30 text-xs">
                    <td class="py-2.5 px-4 font-semibold text-slate-400">${e.date}</td>
                    <td class="py-2.5 px-4 text-white">${e.description}</td>
                    <td class="py-2.5 px-4"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${cls}">${label}</span></td>
                    <td class="py-2.5 px-4 text-slate-400">${e.quantity ? e.quantity + ' ' + (e.unit || '') : '-'}</td>
                    <td class="py-2.5 px-4 text-right text-emerald-400 font-bold">BDT ${e.amount.toFixed(2)}</td>
                    <td class="py-2.5 px-4 text-center"><span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${e.paid ? 'text-emerald-400 bg-emerald-400/10' : 'text-amber-400 bg-amber-400/10'}">${e.paid ? 'Paid' : 'Unpaid'}</span></td>
                    <td class="py-2.5 px-4 text-center">
                        <button onclick="openExpenseEditModal(${e.id}, '${e.date}', \`${escapeHtml(e.description)}\`, ${e.amount}, '${e.meal_type || 'both'}', ${e.quantity || ''}, '${e.unit || ''}', ${e.paid})" class="text-[10px] text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 px-2 py-0.5 rounded transition mr-1" title="Edit"><i class="fa-solid fa-pen"></i></button>
                        <button onclick="deleteExpense(${e.id})" class="text-[10px] text-rose-400 hover:text-rose-300 bg-rose-500/10 hover:bg-rose-500/20 px-2 py-0.5 rounded transition" title="Delete"><i class="fa-solid fa-trash-can"></i></button>
                    </td>
                </tr>
            `;
            }).join("");
        }

        // Sum of "monju" expenses in the current view (read-only display)
        const monjuTotal = expenses
            .filter(e => (e.description || "").toLowerCase().includes("monju"))
            .reduce((s, e) => s + e.amount, 0);
        const monjuEl = document.getElementById("mgr-expenses-monju-summary");
        if (monjuEl) {
            if (expenses.length > 0) {
                monjuEl.classList.remove("hidden");
                monjuEl.innerHTML = `<span class="text-slate-400 font-bold uppercase">Monju Expenses:</span>
                    <span class="text-emerald-400 font-extrabold">BDT ${monjuTotal.toFixed(2)}</span>
                    <span class="text-slate-500">(${expenses.filter(e => (e.description || "").toLowerCase().includes("monju")).length} records)</span>`;
            } else {
                monjuEl.classList.add("hidden");
            }
        }
    } catch (e) {
        console.error(e);
    }
}

// Expense edit modal
function openExpenseEditModal(id, date, desc, amount, mealType, qty, unit, paid) {
    document.getElementById("edit-exp-id").value = id;
    document.getElementById("edit-exp-date").value = date;
    document.getElementById("edit-exp-desc").value = desc;
    document.getElementById("edit-exp-amount").value = amount;
    document.getElementById("edit-exp-meal-type").value = mealType;
    document.getElementById("edit-exp-paid").value = paid ? "true" : "false";
    if (qty) document.getElementById("edit-exp-qty").value = qty;
    if (unit) document.getElementById("edit-exp-unit").value = unit;
    document.getElementById("expense-edit-modal").classList.remove("hidden");
}

function closeExpenseEditModal() {
    document.getElementById("expense-edit-modal").classList.add("hidden");
}

async function handleExpenseEdit(e) {
    e.preventDefault();
    const id = document.getElementById("edit-exp-id").value;
    const data = {
        date: document.getElementById("edit-exp-date").value,
        description: document.getElementById("edit-exp-desc").value,
        amount: parseFloat(document.getElementById("edit-exp-amount").value),
        meal_type: document.getElementById("edit-exp-meal-type").value,
        paid: document.getElementById("edit-exp-paid").value === "true",
        quantity: parseFloat(document.getElementById("edit-exp-qty").value) || null,
        unit: document.getElementById("edit-exp-unit").value || null
    };
    try {
        await apiFetch(`/manager/expenses/${id}`, { method: "PUT", body: data });
        showBanner("Expense updated successfully!");
        closeExpenseEditModal();
        await loadManagerExpenses();
    } catch (e) {
        showBanner(e.message, true);
    }
}

async function deleteExpense(id) {
    if (!confirm("Delete this expense record? This cannot be undone.")) return;
    try {
        await apiFetch(`/manager/expenses/${id}`, { method: "DELETE" });
        showBanner("Expense deleted.");
        await loadManagerExpenses();
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Handle deposit entries by manager
async function handlePostDeposit(e) {
    e.preventDefault();
    const date = document.getElementById("dep-date").value;
    const entries = document.querySelectorAll("#deposit-entries > div");
    let successCount = 0;
    let errors = [];

    for (const entry of entries) {
        const idx = entry.id.replace("dep-entry-", "");
        const usernameEl = document.getElementById(`dep-username-${idx}`);
        const amountEl = document.getElementById(`dep-amount-${idx}`);
        const remarksEl = document.getElementById(`dep-rem-${idx}`);
        if (!usernameEl || !usernameEl.value || !amountEl || !amountEl.value) continue;
        const username = usernameEl.value;
        const amount = parseFloat(amountEl.value);
        const remark = remarksEl ? remarksEl.value.trim() : "Cash Deposit";
        if (!amount || amount <= 0) { errors.push(`${username}: invalid amount`); continue; }
        try {
            await apiFetch("/manager/deposit", {
                method: "POST",
                body: { username, amount, date, description: remark }
            });
            successCount++;
        } catch (err) {
            errors.push(`${username}: ${err.message}`);
        }
    }

    if (successCount > 0) {
        showBanner(`Successfully deposited BDT to ${successCount} student(s)!`);
    }
    if (errors.length > 0) {
        showBanner(`Errors: ${errors.join("; ")}`, true);
    }
    // Reset entries only — keep date
    document.getElementById("deposit-entries").innerHTML = "";
    depositEntryCount = 0;
    addDepositEntry();
    await loadManagerDashboard();
}

// ─── Deposit CRUD (filter, edit, delete) ──────────────────────────────────────

async function loadManagerDeposits() {
    try {
        const dateFilter = document.getElementById("dep-filter-date").value;
        const url = dateFilter ? `/manager/deposits?date=${dateFilter}` : "/manager/deposits";
        const deposits = await apiFetch(url);
        const tbody = document.getElementById("mgr-deposits-tbody");
        if (deposits.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="py-4 text-center text-xs text-slate-500">No deposit records found.</td></tr>`;
        } else {
            tbody.innerHTML = deposits.map(d => `
                <tr class="hover:bg-slate-900/30 text-xs">
                    <td class="py-2.5 px-4 font-semibold text-slate-400">${d.date}</td>
                    <td class="py-2.5 px-4 text-white">${d.name} (${d.username})</td>
                    <td class="py-2.5 px-4 text-slate-400">${d.description || '-'}</td>
                    <td class="py-2.5 px-4 text-right text-emerald-400 font-bold">BDT ${d.amount.toFixed(2)}</td>
                    <td class="py-2.5 px-4 text-center">
                        <button onclick='openDepositEditModal(${d.id}, "${d.username}", "${d.date}", ${d.amount}, "${d.description.replace(/"/g, '\\"')}")' class="text-[10px] text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 px-2 py-0.5 rounded transition mr-1" title="Edit"><i class="fa-solid fa-pen"></i></button>
                        <button onclick="deleteDeposit(${d.id})" class="text-[10px] text-rose-400 hover:text-rose-300 bg-rose-500/10 hover:bg-rose-500/20 px-2 py-0.5 rounded transition" title="Delete"><i class="fa-solid fa-trash-can"></i></button>
                    </td>
                </tr>
            `).join("");
        }
    } catch (e) {
        console.error(e);
    }
}

function openDepositEditModal(id, username, date, amount, desc) {
    document.getElementById("edit-dep-id").value = id;
    document.getElementById("edit-dep-username").value = username;
    document.getElementById("edit-dep-date").value = date;
    document.getElementById("edit-dep-amount").value = amount;
    document.getElementById("edit-dep-desc").value = desc;
    document.getElementById("deposit-edit-modal").classList.remove("hidden");
}

function closeDepositEditModal() {
    document.getElementById("deposit-edit-modal").classList.add("hidden");
}

async function handleDepositEdit(e) {
    e.preventDefault();
    const id = document.getElementById("edit-dep-id").value;
    const data = {
        username: document.getElementById("edit-dep-username").value,
        date: document.getElementById("edit-dep-date").value,
        amount: parseFloat(document.getElementById("edit-dep-amount").value),
        description: document.getElementById("edit-dep-desc").value
    };
    try {
        await apiFetch(`/manager/deposits/${id}`, { method: "PUT", body: data });
        showBanner("Deposit updated successfully!");
        closeDepositEditModal();
        await loadManagerDeposits();
        await loadManagerDashboard();
    } catch (e) {
        showBanner(e.message, true);
    }
}

async function deleteDeposit(id) {
    if (!confirm("Delete this deposit record? This will reverse the student's balance.")) return;
    try {
        await apiFetch(`/manager/deposits/${id}`, { method: "DELETE" });
        showBanner("Deposit deleted and balance reversed.");
        await loadManagerDeposits();
        await loadManagerDashboard();
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Add a new expense item row
function addExpenseRow() {
    const container = document.getElementById("expense-rows");
    const newRow = document.createElement("div");
    newRow.className = "expense-row grid grid-cols-12 gap-2 items-end bg-slate-900/50 p-3 rounded-xl border border-slate-800";
    newRow.innerHTML = `
        <div class="col-span-12 md:col-span-3">
            <label class="block text-[10px] text-slate-400 font-bold uppercase">Item</label>
            <input type="text" name="exp-desc" placeholder="e.g. Oil" required class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
        </div>
        <div class="col-span-6 md:col-span-2">
            <label class="block text-[10px] text-slate-400 font-bold uppercase">For Meal</label>
            <select name="exp-meal-type" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-2 text-white text-xs focus:outline-none focus:border-emerald-500">
                <option value="both">Both</option>
                <option value="lunch">Lunch</option>
                <option value="dinner">Dinner</option>
            </select>
        </div>
        <div class="col-span-6 md:col-span-2">
            <label class="block text-[10px] text-slate-400 font-bold uppercase">Amount (BDT)</label>
            <input type="number" name="exp-amount" step="any" required class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
        </div>
        <div class="col-span-4 md:col-span-1">
            <label class="block text-[10px] text-slate-400 font-bold uppercase">Paid</label>
            <select name="exp-paid" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-1 text-white text-xs focus:outline-none focus:border-emerald-500">
                <option value="true">Yes</option>
                <option value="false">No</option>
            </select>
        </div>
        <div class="col-span-4 md:col-span-2">
            <label class="block text-[10px] text-slate-400 font-bold uppercase">Qty</label>
            <input type="number" name="exp-qty" step="any" placeholder="10" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
        </div>
        <div class="col-span-4 md:col-span-1">
            <label class="block text-[10px] text-slate-400 font-bold uppercase">Unit</label>
            <input type="text" name="exp-unit" list="unit-options" placeholder="kg" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
        </div>
        <div class="col-span-12 md:col-span-1 flex justify-end items-end pb-1">
            <button type="button" onclick="removeExpenseRow(this)" class="text-rose-400 hover:text-rose-300 p-2 rounded-lg hover:bg-rose-500/10 transition" title="Remove row">
                <i class="fa-solid fa-trash-can text-xs"></i>
            </button>
        </div>
    `;
    container.appendChild(newRow);
}

function removeExpenseRow(btn) {
    const rows = document.querySelectorAll("#expense-rows .expense-row");
    if (rows.length <= 1) {
        showBanner("At least one expense item is required.", true);
        return;
    }
    btn.closest(".expense-row").remove();
}

// Handle expense entries by manager (batch)
async function handlePostExpense(e) {
    e.preventDefault();
    const date = document.getElementById("exp-date").value;
    if (!date) {
        showBanner("Please select a date.", true);
        return;
    }

    const rows = document.querySelectorAll("#expense-rows .expense-row");
    const items = [];
    for (const row of rows) {
        const description = row.querySelector('[name="exp-desc"]').value.trim();
        const amount = parseFloat(row.querySelector('[name="exp-amount"]').value);
        const meal_type = row.querySelector('[name="exp-meal-type"]').value;
        const qtyInput = row.querySelector('[name="exp-qty"]').value;
        const quantity = qtyInput ? parseFloat(qtyInput) : null;
        const unit = row.querySelector('[name="exp-unit"]').value || null;
        const paid = row.querySelector('[name="exp-paid"]').value === "true";

        if (!description || isNaN(amount) || amount <= 0) {
            showBanner("Each item must have a description and a positive amount.", true);
            return;
        }
        items.push({ description, date, amount, quantity, unit, meal_type, paid });
    }

    try {
        const result = await apiFetch("/manager/expenses/batch", {
            method: "POST",
            body: { items }
        });
        showBanner(`${result.count} expense item(s) logged successfully!`);
        // Reset all rows except the first
        const allRows = document.querySelectorAll("#expense-rows .expense-row");
        for (let i = 1; i < allRows.length; i++) allRows[i].remove();
        const firstRow = document.querySelector("#expense-rows .expense-row");
        if (firstRow) {
            firstRow.querySelector('[name="exp-desc"]').value = "";
            firstRow.querySelector('[name="exp-amount"]').value = "";
            firstRow.querySelector('[name="exp-qty"]').value = "";
            firstRow.querySelector('[name="exp-unit"]').value = "";
            firstRow.querySelector('[name="exp-meal-type"]').value = "both";
        }
        await loadManagerDashboard();
    } catch (err) {
        showBanner(err.message, true);
    }
}

// Handle update rules/settings
async function handleUpdateSettings(e) {
    e.preventDefault();
    const cutoff_time = document.getElementById("set-cutoff-time").value;
    const lunch_percentage = parseFloat(document.getElementById("set-lunch-perc").value);
    const dinner_percentage = parseFloat(document.getElementById("set-dinner-perc").value);
    const manager_charge_per_day = parseFloat(document.getElementById("set-mgr-fee").value);
    const guest_charge_per_day = parseFloat(document.getElementById("set-guest-fee").value);
    const lunch_only_rate_percentage = parseFloat(document.getElementById("set-lunch-only-rate-pct").value);
    const dinner_only_rate_percentage = parseFloat(document.getElementById("set-dinner-only-rate-pct").value);
    const fullRateDaysSelect = document.getElementById("set-full-rate-days");
    const full_rate_days = Array.from(fullRateDaysSelect.selectedOptions).map(o => o.value).join(",") || "4";
    const cycle_end_date = document.getElementById("set-cycle-end-date").value || "";

    try {
        const url = `/manager/settings?manager_charge_per_day=${manager_charge_per_day}&guest_charge_per_day=${guest_charge_per_day}&cutoff_time=${encodeURIComponent(cutoff_time)}&lunch_percentage=${lunch_percentage}&dinner_percentage=${dinner_percentage}&lunch_only_rate_percentage=${lunch_only_rate_percentage}&dinner_only_rate_percentage=${dinner_only_rate_percentage}&full_rate_days=${encodeURIComponent(full_rate_days)}${cycle_end_date ? `&cycle_end_date=${cycle_end_date}` : ""}`;
        await apiFetch(url, { method: "POST" });
        showBanner("Dining rules settings saved!");
        await loadManagerDashboard();
    } catch (err) {
        showBanner(err.message, true);
    }
}

async function loadFeeOverrides() {
    const tbody = document.getElementById("fee-overrides-list");
    if (!tbody) return;
    try {
        const list = await apiFetch("/manager/daily-fee-overrides");
        tbody.innerHTML = list.length
            ? list.map(o => `
                <tr class="hover:bg-slate-900/30">
                    <td class="py-1.5 pr-2 text-slate-300">${o.date}</td>
                    <td class="py-1.5 pr-2 text-right">${o.manager_charge != null ? `BDT ${o.manager_charge.toFixed(2)}` : 'default'}</td>
                    <td class="py-1.5 pr-2 text-right">${o.guest_charge != null ? `BDT ${o.guest_charge.toFixed(2)}` : 'default'}</td>
                    <td class="py-1.5 text-right">
                        <button onclick="editFeeOverride(${o.id})" class="text-[10px] text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 px-1.5 py-0.5 rounded transition mr-1"><i class="fa-solid fa-pen"></i></button>
                        <button onclick="deleteFeeOverride(${o.id})" class="text-[10px] text-rose-400 hover:text-rose-300 bg-rose-500/10 hover:bg-rose-500/20 px-1.5 py-0.5 rounded transition"><i class="fa-solid fa-trash-can"></i></button>
                    </td>
                </tr>`).join("")
            : '<tr><td colspan="4" class="py-4 text-center text-slate-500">No overrides</td></tr>';
    } catch (e) { showBanner(e.message, true); }
}

async function addFeeOverride() {
    const dateVal = document.getElementById("fee-ovr-date").value;
    const mgrVal = document.getElementById("fee-ovr-mgr").value;
    const guestVal = document.getElementById("fee-ovr-guest").value;
    if (!dateVal) { showBanner("Select a date.", true); return; }
    if (!mgrVal && !guestVal) { showBanner("Enter at least one charge.", true); return; }
    const body = { date: dateVal, manager_charge: mgrVal ? parseFloat(mgrVal) : null, guest_charge: guestVal ? parseFloat(guestVal) : null };
    try {
        const res = await apiFetch("/manager/daily-fee-overrides", { method: "POST", body });
        const keepDate = document.getElementById("fee-ovr-date").value;
        document.getElementById("fee-ovr-mgr").value = "";
        document.getElementById("fee-ovr-guest").value = "";
        document.getElementById("fee-ovr-date").value = keepDate || "";
        await loadFeeOverrides();
        showBanner(res.message);
    } catch (e) { showBanner(e.message, true); }
}

async function editFeeOverride(id) {
    try {
        const list = await apiFetch("/manager/daily-fee-overrides");
        const o = list.find(x => x.id === id);
        if (!o) return;
        document.getElementById("fee-ovr-date").value = o.date;
        document.getElementById("fee-ovr-mgr").value = o.manager_charge != null ? o.manager_charge : "";
        document.getElementById("fee-ovr-guest").value = o.guest_charge != null ? o.guest_charge : "";
        window._feeOverrideId = id;
        const addBtn = document.querySelector('#mgr-tab-settings button[onclick="addFeeOverride()"]');
        if (addBtn) { addBtn.textContent = "Update"; addBtn.onclick = () => updateFeeOverride(); }
        document.getElementById("fee-ovr-date").scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) { showBanner(e.message, true); }
}

async function updateFeeOverride() {
    const id = window._feeOverrideId;
    const dateVal = document.getElementById("fee-ovr-date").value;
    const mgrVal = document.getElementById("fee-ovr-mgr").value;
    const guestVal = document.getElementById("fee-ovr-guest").value;
    if (!dateVal) { showBanner("Select a date.", true); return; }
    const body = { date: dateVal, manager_charge: mgrVal ? parseFloat(mgrVal) : null, guest_charge: guestVal ? parseFloat(guestVal) : null };
    try {
        await apiFetch(`/manager/daily-fee-overrides/${id}`, { method: "PUT", body });
        resetFeeOverrideForm();
        await loadFeeOverrides();
        showBanner("Override updated.");
    } catch (e) { showBanner(e.message, true); }
}

async function deleteFeeOverride(id) {
    if (!confirm("Delete this override?")) return;
    try {
        await apiFetch(`/manager/daily-fee-overrides/${id}`, { method: "DELETE" });
        await loadFeeOverrides();
        showBanner("Override deleted.");
    } catch (e) { showBanner(e.message, true); }
}

function resetFeeOverrideForm() {
    window._feeOverrideId = null;
    const keepDate = document.getElementById("fee-ovr-date").value;
    document.getElementById("fee-ovr-mgr").value = "";
    document.getElementById("fee-ovr-guest").value = "";
    document.getElementById("fee-ovr-date").value = keepDate || "";
    const addBtn = document.querySelector('#mgr-tab-settings button[onclick="addFeeOverride()"]');
    if (addBtn) { addBtn.textContent = "Add"; addBtn.onclick = () => addFeeOverride(); }
}

// Load SMTP config into settings form
async function loadSmtpConfig() {
    try {
        const cfg = await apiFetch("/manager/smtp-config");
        document.getElementById("smtp-host").value = cfg.smtp_host || "smtp.gmail.com";
        document.getElementById("smtp-port").value = cfg.smtp_port || "587";
        document.getElementById("smtp-user").value = cfg.smtp_user || (currentUser && currentUser.email ? currentUser.email : "");
        document.getElementById("smtp-pass").value = "";
    } catch (e) { /* ignore */ }
}

// Save SMTP config
async function handleSmtpConfigSave(e) {
    e.preventDefault();
    const host = document.getElementById("smtp-host").value.trim();
    const port = document.getElementById("smtp-port").value.trim() || "587";
    const user = document.getElementById("smtp-user").value.trim();
    const pass = document.getElementById("smtp-pass").value;
    try {
        const url = "/manager/smtp-config?smtp_host=" + encodeURIComponent(host) + "&smtp_port=" + encodeURIComponent(port) + "&smtp_user=" + encodeURIComponent(user) + "&smtp_pass=" + encodeURIComponent(pass);
        await apiFetch(url, { method: "POST" });
        showBanner("SMTP email configuration saved!");
        document.getElementById("smtp-pass").value = "";
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Payment Accounts Settings
async function loadPaymentNumbers() {
    try {
        const data = await apiFetch("/manager/payment-numbers");
        document.getElementById("set-bkash-number").value = data.bkash_number || "";
        document.getElementById("set-nagad-number").value = data.nagad_number || "";
    } catch (e) { /* ignore */ }
}

async function handlePaymentNumbersSave(e) {
    e.preventDefault();
    const bkash = document.getElementById("set-bkash-number").value.trim();
    const nagad = document.getElementById("set-nagad-number").value.trim();
    try {
        await apiFetch(`/manager/payment-numbers?bkash_number=${encodeURIComponent(bkash)}&nagad_number=${encodeURIComponent(nagad)}`, { method: "POST" });
        showBanner("Payment numbers updated!");
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Email template settings
async function loadEmailTemplates() {
    const configs = { bkash: "deposit_email_bkash_", manual: "deposit_email_manual_", bill: "bill_email_" };
    for (const [type, prefix] of Object.entries(configs)) {
        try {
            const subj = await apiFetch(`/manager/app-config/${prefix}subject`);
            document.getElementById(`email-tpl-${type}-subject`).value = subj.value || "";
            const body = await apiFetch(`/manager/app-config/${prefix}body`);
            document.getElementById(`email-tpl-${type}-body`).value = body.value || "";
        } catch (_) {}
    }
}

window.saveEmailTemplate = async function(type) {
    const prefix = (type === "bill" ? "bill_email_" : "deposit_email_") + type;
    const subject = document.getElementById(`email-tpl-${type}-subject`).value;
    const body = document.getElementById(`email-tpl-${type}-body`).value;
    try {
        await Promise.all([
            apiFetch(`/manager/app-config/${prefix}_subject?value=${encodeURIComponent(subject)}`, { method: "POST" }),
            apiFetch(`/manager/app-config/${prefix}_body?value=${encodeURIComponent(body)}`, { method: "POST" })
        ]);
        showBanner("Email template saved!");
    } catch (e) {
        showBanner(e.message, true);
    }
};

// Guest meal force disable
async function deactivateAllGuests() {
    if (!confirm("Are you sure you want to deactivate all guest meals for today and future days of this cycle?")) {
        return;
    }
    try {
        const data = await apiFetch("/manager/guests/deactivate-all", { method: "POST" });
        showBanner(data.message);
        await loadManagerDashboard();
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Daily menu toggles
async function loadDailyMenu(dateStr) {
    try {
        const menu = await apiFetch("/manager/daily-menu?date_str=" + dateStr);
        document.getElementById("menu-fish").checked = menu.pangas_served || false;
        document.getElementById("menu-other-fish").checked = menu.other_fish_served || false;
        document.getElementById("menu-beef").checked = menu.beef_served || false;
        document.getElementById("menu-mutton").checked = menu.mutton_served || false;
    } catch (e) { /* ignore */ }
}

async function updateDailyMenu() {
    const dStr = document.getElementById("sheet-date-select").value;
    if (!dStr) return;
    const pangas = document.getElementById("menu-fish").checked;
    const otherFish = document.getElementById("menu-other-fish").checked;
    const beef = document.getElementById("menu-beef").checked;
    const mutton = document.getElementById("menu-mutton").checked;
    try {
        await apiFetch(`/manager/daily-menu?date_str=${dStr}&pangas_served=${pangas}&other_fish_served=${otherFish}&beef_served=${beef}&mutton_served=${mutton}`, { method: "POST" });
        if (managerSheetData && managerSheetData.length) {
            renderDiningSheetData(managerSheetData);
        }
    } catch (e) { /* ignore */ }
}

// Fetch and render printable dining sheet
let managerSheetData = [];

async function fetchPrintSheet() {
    const dStr = document.getElementById("sheet-date-select").value;
    if (!dStr) return;
    
    loadDailyMenu(dStr);
    
    document.getElementById("sheet-date-title").textContent = `Meal Active Sheet - ${dStr}`;
    document.getElementById("print-date").textContent = `Date: ${dStr}`;
    
    try {
        const data = await apiFetch(`/manager/student-meals?date_str=${dStr}`);
        managerSheetData = data;
        
        // Preserve search across refreshes
        const searchEl = document.getElementById("sheet-search");
        const prevSearch = searchEl.value;
        
        renderDiningSheetData(data);
        
        // Restore search value and re-apply all filters
        searchEl.value = prevSearch;
        filterDiningSheet();
    } catch (e) {
        showBanner(e.message, true);
    }
}

function renderDiningSheetData(sheet) {
    const dStr = document.getElementById("sheet-date-select").value;
    const tbody = document.getElementById("mgr-sheet-tbody");
    const printGrid = document.getElementById("print-sheet-grid");
    
    // Update stats bar
    let statBoth = 0, statLunch = 0, statDinner = 0, statDouble = 0, statTriple = 0, statOff = 0, statGuest = 0;
    sheet.forEach(item => {
        if (item.is_guest) statGuest++;
        if (item.status === "both") statBoth++;
        else if (item.status === "lunch_only") statLunch++;
        else if (item.status === "dinner_only") statDinner++;
        else if (item.status === "double") statDouble++;
        else if (item.status === "triple") statTriple++;
        else if (item.status === "off") statOff++;
    });
    document.getElementById("sheet-stat-both").textContent = statBoth;
    document.getElementById("sheet-stat-lunch").textContent = statLunch;
    document.getElementById("sheet-stat-dinner").textContent = statDinner;
    document.getElementById("sheet-stat-double").textContent = statDouble;
    document.getElementById("sheet-stat-triple").textContent = statTriple;
    document.getElementById("sheet-stat-off").textContent = statOff;
    document.getElementById("sheet-stat-guest").textContent = statGuest;
    
    // Preference counts for active (non-off) students based on selected menu
    const countPangasEgg = sheet.filter(i => i.status !== "off" && (i.fish_egg_pref || "normal") === "if_pangas_then_egg").length;
    const countOtherFishEgg = sheet.filter(i => i.status !== "off" && (i.fish_egg_pref || "normal") === "egg_instead_of_fish").length;
    const countBeef = sheet.filter(i => i.status !== "off" && (i.meat_pref || "normal") === "beef").length;
    const countMutton = sheet.filter(i => i.status !== "off" && (i.meat_pref || "normal") === "mutton").length;
    document.getElementById("sheet-pref-pangas-egg").textContent = countPangasEgg;
    document.getElementById("sheet-pref-other-egg").textContent = countOtherFishEgg;
    document.getElementById("sheet-pref-beef").textContent = countBeef;
    document.getElementById("sheet-pref-mutton").textContent = countMutton;
    
    if (sheet.length === 0) {
        const emptyTr = `<tr><td colspan="9" class="py-6 text-center text-xs text-slate-500">No student meals found for this day.</td></tr>`;
        tbody.innerHTML = emptyTr;
        if (printGrid) {
            printGrid.innerHTML = `<div style="grid-column: span 3; padding:20px; text-align:center; color:#999; font-size:11px;">No student meals found.</div>`;
        }
        const totalEl = document.getElementById("print-total-summary");
        if (totalEl) totalEl.textContent = "Total: 0 Lunch / 0 Dinner";
        return;
    }
    
    let html = "";
    let lunchCount = 0;
    let dinnerCount = 0;
    
    // Group data by room for on-screen display with room headers
    const roomGroups = {};
    sheet.forEach(item => {
        const room = item.room_number || "N/A";
        if (!roomGroups[room]) roomGroups[room] = [];
        roomGroups[room].push(item);
    });
    
    const sortedRooms = Object.keys(roomGroups).sort((a, b) => {
        const dA = parseInt(a.replace(/\D/g, '')) || 99999;
        const dB = parseInt(b.replace(/\D/g, '')) || 99999;
        return dA - dB;
    });
    
    sortedRooms.forEach(room => {
        // Room header row in on-screen table
        html += `<tr class="bg-slate-800/30"><td colspan="9" class="py-2 px-4 text-[10px] font-black text-emerald-400 uppercase tracking-widest"><i class="fa-solid fa-door-open mr-1.5 opacity-50"></i>Room ${room}</td></tr>`;
        
        roomGroups[room].forEach(item => {
            const hasLunch = ["both", "lunch_only", "double", "triple"].includes(item.status);
            const hasDinner = ["both", "dinner_only", "double", "triple"].includes(item.status);
            const mult = item.status === "double" ? 2 : item.status === "triple" ? 3 : 1;
            if (hasLunch) lunchCount += mult;
            if (hasDinner) dinnerCount += mult;
            const hasStatusRec = item.status_id !== null;
            
            html += `
                <tr class="hover:bg-slate-900/30 text-xs border-l-2 ${item.status !== 'off' ? 'border-l-emerald-500/40' : 'border-l-transparent'}">
                    <td class="py-2 px-2"><input type="checkbox" class="sheet-row-chk h-3.5 w-3.5 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500" data-user="${item.user_id}"></td>
                    <td class="py-2 px-4 font-bold text-white text-sm">${item.room_number}</td>
                    <td class="py-2 px-4">
                        <a href="#" onclick="event.preventDefault(); openStudentLedger(${item.user_id})" class="text-white hover:text-emerald-400 transition font-semibold">${item.name}</a>
                        ${item.is_guest ? ' <span class="text-cyan-400 bg-cyan-500/10 px-1.5 py-0.5 rounded text-[9px] font-bold ml-1">GUEST</span>' : ''}
                        ${(() => { 
                            const p = document.getElementById("menu-fish")?.checked;
                            const o = document.getElementById("menu-other-fish")?.checked;
                            const b = document.getElementById("menu-beef")?.checked;
                            const mt = document.getElementById("menu-mutton")?.checked;
                            const fep = item.fish_egg_pref || "normal";
                            const mp2 = item.meat_pref || "normal";
                            let t = '';
                            if (p && (fep === "if_pangas_then_egg" || fep === "egg_instead_of_fish")) t += ' <span class="text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded text-[9px] font-bold ml-1">Egg</span>';
                            if (o && fep === "egg_instead_of_fish") t += ' <span class="text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded text-[9px] font-bold ml-1">Egg</span>';
                            if (b && mp2 === "beef") t += ' <span class="text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded text-[9px] font-bold ml-1">Beef</span>';
                            if (mt && mp2 === "mutton") t += ' <span class="text-green-400 bg-green-500/10 px-1.5 py-0.5 rounded text-[9px] font-bold ml-1">Mutton</span>';
                            return t;
                        })()}
                    </td>
                    <td class="py-2 px-4"><span class="text-slate-400 text-[10px]">${item.is_guest ? 'Guest' : item.role}</span></td>
                    <td class="py-2 px-4">
                        <select onchange="updateStudentMealStatus(${item.user_id}, '${dStr}', this.value)" class="bg-slate-950 border border-slate-800 text-[10px] text-white rounded px-1.5 py-0.5 focus:outline-none">
                            <option value="off" ${item.status === 'off' ? 'selected' : ''}>Off</option>
                            <option value="both" ${item.status === 'both' ? 'selected' : ''}>Both</option>
                            <option value="lunch_only" ${item.status === 'lunch_only' ? 'selected' : ''}>Lunch Only</option>
                            <option value="dinner_only" ${item.status === 'dinner_only' ? 'selected' : ''}>Dinner Only</option>
                            <option value="double" ${item.status === 'double' ? 'selected' : ''}>Double</option>
                            <option value="triple" ${item.status === 'triple' ? 'selected' : ''}>Triple</option>
                        </select>
                        <label class="inline-flex items-center ml-1.5 cursor-pointer" title="Mark as guest">
                            <input type="checkbox" ${item.is_guest ? 'checked' : ''} onchange="toggleGuestFlag(${item.user_id}, '${dStr}', ${item.status === 'off' ? "'both'" : "'" + item.status + "'"}, this.checked)" class="h-3 w-3 rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500">
                            <span class="text-[9px] text-slate-400 ml-0.5">Guest</span>
                        </label>
                    </td>
                    <td class="py-2 px-4 text-center">
                        <input type="checkbox" ${item.ticked_lunch ? 'checked' : ''} ${!hasStatusRec ? 'disabled' : ''} onchange="toggleMealTicked(${item.status_id}, 'lunch', this.checked)" class="h-4 w-4 rounded border-slate-800 text-emerald-500 focus:ring-emerald-500 bg-slate-900 disabled:opacity-40">
                    </td>
                    <td class="py-2 px-4 text-center">
                        <input type="checkbox" ${item.ticked_dinner ? 'checked' : ''} ${!hasStatusRec ? 'disabled' : ''} onchange="toggleMealTicked(${item.status_id}, 'dinner', this.checked)" class="h-4 w-4 rounded border-slate-800 text-emerald-500 focus:ring-emerald-500 bg-slate-900 disabled:opacity-40">
                    </td>
                    <td class="py-2 px-4 text-center">
                        <input type="checkbox" ${item.kept_lunch_for_dinner ? 'checked' : ''} ${!hasStatusRec ? 'disabled' : ''} onchange="toggleMealKeptForDinner(${item.status_id}, this.checked)" class="h-4 w-4 rounded border-slate-800 text-emerald-500 focus:ring-emerald-500 bg-slate-900 disabled:opacity-40">
                    </td>
                    <td class="py-2 px-4 text-center">
                        <button onclick="openStudentLedger(${item.user_id})" class="text-[10px] text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 px-2 py-0.5 rounded-lg transition font-semibold" title="View ledger">
                            <i class="fa-solid fa-receipt mr-0.5"></i> Ledger
                        </button>
                    </td>
                </tr>
            `;
        });
    });
    
    tbody.innerHTML = html;
    
    // Build print view: room-grouped, compact room cards in grid, only active meals
    let printHtml = "";
    let serialNo = 0;
    let printLunch = 0;
    let printDinner = 0;
    
    // Filter only active meals for print
    const activeSheet = sheet.filter(i => i.status !== "off");
    const printRoomGroups = {};
    activeSheet.forEach(item => {
        const room = item.room_number || "N/A";
        if (!printRoomGroups[room]) printRoomGroups[room] = [];
        printRoomGroups[room].push(item);
    });
    
    const printSortedRooms = Object.keys(printRoomGroups).sort((a, b) => {
        const dA = parseInt(a.replace(/\D/g, '')) || 99999;
        const dB = parseInt(b.replace(/\D/g, '')) || 99999;
        return dA - dB;
    });
    
    printSortedRooms.forEach(room => {
        let roomRowsHtml = "";
        
        printRoomGroups[room].forEach(item => {
            serialNo++;
            const hasLunch = ["both", "lunch_only", "double", "triple"].includes(item.status);
            const hasDinner = ["both", "dinner_only", "double", "triple"].includes(item.status);
            const pMult = item.status === "double" ? 2 : item.status === "triple" ? 3 : 1;
            if (hasLunch) printLunch += pMult;
            if (hasDinner) printDinner += pMult;
            
            const guestTag = item.is_guest ? ' (G)' : '';
            // Multiplier indicator for double/triple meals
            const multTag = item.status === "double" ? ' [×2]' : item.status === "triple" ? ' [×3]' : '';
            // Dietary preference indicators
            const pOn = document.getElementById("menu-fish").checked;
            const oOn = document.getElementById("menu-other-fish").checked;
            const bOn = document.getElementById("menu-beef").checked;
            const mOn = document.getElementById("menu-mutton").checked;
            const fep = item.fish_egg_pref || "normal";
            const mp2 = item.meat_pref || "normal";
            let prefTag = '';
            if (pOn && (fep === "if_pangas_then_egg" || fep === "egg_instead_of_fish")) prefTag += ' [Egg]';
            if (oOn && fep === "egg_instead_of_fish") prefTag += ' [Egg]';
            if (bOn && mp2 === "beef") prefTag += ' [Beef]';
            if (mOn && mp2 === "mutton") prefTag += ' [Mutton]';
            
            const nameWithPref = item.name + multTag + guestTag + prefTag;
            // If the student doesn't have a meal, we display a dash "—" instead of an empty square "☐"
            const lunchBox = hasLunch ? '☐' : '—';
            const dinnerBox = hasDinner ? '☐' : '—';
            const lunchColor = hasLunch ? '#000' : '#888';
            const dinnerColor = hasDinner ? '#000' : '#888';
            
            roomRowsHtml += `
                <tr style="border-bottom: 1px dotted #ccc;">
                    <td style="padding: 1px 3px; font-size: 7px; color: #444; width: 12px; text-align: center;">${serialNo}</td>
                    <td style="padding: 2px 4px; font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px; color: #000;">${nameWithPref}</td>
                    <td style="padding: 1px 4px; text-align: center; font-size: 15px; width: 28px; font-weight: bold; border-left: 1px solid #ddd; color: ${lunchColor};">${lunchBox}</td>
                    <td style="padding: 1px 4px; text-align: center; font-size: 15px; width: 28px; font-weight: bold; border-left: 1px solid #ddd; color: ${dinnerColor};">${dinnerBox}</td>
                </tr>
            `;
        });
        
        printHtml += `
            <div style="border: 1px solid #000; padding: 2px; break-inside: avoid; page-break-inside: avoid; background: #fff; border-radius: 2px; display: inline-block; width: 100%; box-sizing: border-box; margin-bottom: 6px; font-family: 'Segoe UI', Arial, sans-serif;">
                <div style="font-weight: 800; font-size: 11px; background: #f0f0f0; padding: 3px 6px; text-align: center; letter-spacing: 0.5px; color: #000;">ROOM ${room}</div>
                <table style="width: 100%; border-collapse: collapse; table-layout: fixed; border-top: 1px solid #000;">
                    <thead>
                        <tr style="border-bottom: 1px solid #000; background: #fafafa;">
                            <th style="width: 12px; font-size: 6px; padding: 1px; color: #555;">#</th>
                            <th style="font-size: 6px; text-align: left; padding: 1px 4px; color: #555;">Name</th>
                            <th style="width: 22px; font-size: 6px; text-align: center; border-left: 1px solid #ddd; color: #555;">L</th>
                            <th style="width: 22px; font-size: 6px; text-align: center; border-left: 1px solid #ddd; color: #555;">D</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${roomRowsHtml}
                    </tbody>
                </table>
            </div>
        `;
    });
    
    if (printGrid) {
        printGrid.innerHTML = printHtml || `<div style="grid-column: span 3; padding: 20px; text-align: center; color: #666; font-size: 11px;">No active student meals found.</div>`;
    }
    
    // Update total summary in print view
    const totalEl = document.getElementById("print-total-summary");
    if (totalEl) totalEl.textContent = `Total Active: ${printLunch} Lunch / ${printDinner} Dinner (${serialNo} students)`;
    
    // Update Today's Meals Metrics
    document.getElementById("metrics-meals").textContent = `${lunchCount} / ${dinnerCount}`;
}

function filterDiningSheet() {
    const query = document.getElementById("sheet-search").value.toLowerCase().trim();
    const statusFilter = document.getElementById("sheet-status-filter").value;
    const typeFilter = document.getElementById("sheet-type-filter")?.value || "all";
    renderDiningSheetData(managerSheetData.filter(item => {
        // Status filter
        if (statusFilter === "active" && item.status === "off") return false;
        if (statusFilter === "inactive" && item.status !== "off") return false;
        if (["both", "lunch_only", "dinner_only", "double", "triple", "off"].includes(statusFilter) && item.status !== statusFilter) return false;
        // Type filter (native = home hall student, guest = from other hall)
        if (typeFilter === "native" && item.is_guest) return false;
        if (typeFilter === "guest" && !item.is_guest) return false;
        // Search text filter
        if (!query) return true;
        return (item.name && item.name.toLowerCase().includes(query)) ||
               (item.username && item.username.toLowerCase().includes(query)) ||
               (item.room_number && item.room_number.toLowerCase().includes(query));
    }));
}

async function updateStudentMealStatus(userId, dateStr, status) {
    try {
        await apiFetch("/manager/students/toggle-meal", {
            method: "POST",
            body: { user_id: userId, date: dateStr, status: status }
        });
        showBanner("Student meal status updated!");
        await fetchPrintSheet();
    } catch (e) {
        showBanner(e.message, true);
        await fetchPrintSheet();
    }
}

async function toggleGuestFlag(userId, dateStr, status, isGuest) {
    try {
        await apiFetch("/manager/students/toggle-meal", {
            method: "POST",
            body: { user_id: userId, date: dateStr, status: status, is_guest: isGuest }
        });
        showBanner(`Guest flag ${isGuest ? 'enabled' : 'disabled'} for student.`);
        await fetchPrintSheet();
    } catch (e) {
        showBanner(e.message, true);
        await fetchPrintSheet();
    }
}

// Tick off a meal from the print sheet directly (Attendance tracking)
async function toggleMealTicked(statusId, type, ticked) {
    try {
        await apiFetch(`/manager/meal-tick?status_id=${statusId}&meal_type=${type}&ticked=${ticked}`, {
            method: "POST"
        });
        showBanner("Meal attendance ticked!");
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Keep lunch for dinner toggle
async function toggleMealKeptForDinner(statusId, kept) {
    try {
        await apiFetch(`/manager/keep-lunch-for-dinner?status_id=${statusId}&kept=${kept}`, {
            method: "POST"
        });
        showBanner("Kept lunch for dinner state saved!");
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Open student ledger modal from Cycle Summary or dining sheet
async function openLedgerModal(userId) {
    await openStudentLedger(userId);
}
async function openStudentLedger(userId) {
    try {
        const ledger = await apiFetch(`/manager/students/${userId}/ledger`);
        if (!ledger || !ledger.student) { showBanner("Ledger not found.", true); return; }
        const s = ledger.student;
        const bal = (ledger.total_deposits || 0) - (ledger.total_bill || 0);
        const rt = ledger.rates || {};
        
        const statusLabel = { both: 'Both', lunch_only: 'Lunch', dinner_only: 'Dinner', double: 'Double', triple: 'Triple', off: 'Off' };
        
        const depRows = (ledger.deposits || []).map(d =>
            `<tr><td style="padding:3px 4px;border:1px solid #ccc;">${d.date}</td><td style="padding:3px 4px;text-align:right;border:1px solid #ccc;">BDT ${d.amount.toFixed(2)}</td><td style="padding:3px 4px;border:1px solid #ccc;">${d.description || ''}</td></tr>`
        ).join('') || '<tr><td colspan="3" style="padding:6px 4px;text-align:center;">No deposits</td></tr>';
        
        const mealRows = (ledger.daily_meals || []).filter(m => m.status !== 'off').map(m =>
            `<tr><td style="padding:3px 4px;border:1px solid #ccc;">${m.date}</td><td style="padding:3px 4px;text-align:center;border:1px solid #ccc;">${statusLabel[m.status] || m.status}</td><td style="padding:3px 4px;text-align:center;border:1px solid #ccc;">${m.ticked_lunch ? '✓' : '-'}</td><td style="padding:3px 4px;text-align:center;border:1px solid #ccc;">${m.ticked_dinner ? '✓' : '-'}</td><td style="padding:3px 4px;text-align:right;border:1px solid #ccc;font-weight:bold;">BDT ${(m.day_cost || 0).toFixed(2)}</td></tr>`
        ).join('') || '<tr><td colspan="5" style="padding:6px 4px;text-align:center;">No meals</td></tr>';
        
        const modalHtml = `
        <div class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4 z-50" onclick="if(event.target===this)this.remove()">
            <div class="bg-white rounded-2xl p-5 max-w-4xl w-full max-h-[90vh] overflow-y-auto relative" style="color:#000;font-family:Segoe UI,Arial,sans-serif;font-size:10px;">
                <button onclick="this.closest('.fixed').remove()" class="absolute top-3 right-4 text-slate-400 hover:text-slate-600 text-xl"><i class="fa-solid fa-xmark"></i></button>
                
                <div style="border-bottom:2px solid #000;padding-bottom:6px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-end;">
                    <div><div style="font-size:15px;font-weight:800;">${escapeHtml(s.hall_name || 'eDining Hall')}</div><div style="font-size:11px;font-weight:700;margin-top:2px;">Cycle Billing Statement</div></div>
                    <div style="font-size:10px;text-align:right;color:#555;">Cycle: <b>${ledger.cycle ? ledger.cycle.month : '-'}</b><br>Printed: <b>${new Date().toLocaleDateString()}</b></div>
                </div>
                
                <div style="margin-bottom:8px;display:flex;gap:30px;background:#f5f5f5;padding:6px 10px;border-radius:6px;">
                    <div><span style="color:#555;">Name:</span> <b>${escapeHtml(s.name)}</b></div>
                    <div><span style="color:#555;">ID:</span> <b>${escapeHtml(s.username)}</b></div>
                    <div><span style="color:#555;">Room:</span> <b>${escapeHtml(s.room_number || 'N/A')}</b></div>
                </div>
                
                <div style="display:grid;grid-template-columns:1fr 2fr;gap:10px;">
                    <div>
                        <div style="font-weight:800;font-size:10px;border-bottom:1px solid #ccc;padding-bottom:3px;margin-bottom:5px;">Deposit History</div>
                        <table style="width:100%;border-collapse:collapse;font-size:9px;">
                            <thead><tr style="background:#eee;"><th style="padding:3px 4px;text-align:left;border:1px solid #ccc;">Date</th><th style="padding:3px 4px;text-align:right;border:1px solid #ccc;">Amount</th><th style="padding:3px 4px;text-align:left;border:1px solid #ccc;">Note</th></tr></thead>
                            <tbody>${depRows}</tbody>
                            <tfoot><tr style="background:#f5f5f5;font-weight:bold;"><td style="padding:3px 4px;border:1px solid #ccc;">Total</td><td style="padding:3px 4px;text-align:right;border:1px solid #ccc;">BDT ${(ledger.total_deposits || 0).toFixed(2)}</td><td style="border:1px solid #ccc;"></td></tr></tfoot>
                        </table>
                        
                        <div style="margin-top:10px;border:1px solid #ccc;border-radius:5px;padding:8px;font-size:9px;background:#fafafa;">
                            <div style="font-weight:800;margin-bottom:5px;font-size:10px;border-bottom:1px solid #ddd;padding-bottom:3px;">Billing Summary</div>
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;"><span>Total Deposits:</span><b>BDT ${(ledger.total_deposits || 0).toFixed(2)}</b></div>
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;"><span>Total Bill:</span><b>BDT ${(ledger.total_bill || 0).toFixed(2)}</b></div>
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;"><span>Balance:</span><b>BDT ${bal.toFixed(2)}</b></div>
                            <div style="border-top:1px solid #ccc;margin-top:5px;padding-top:5px;">
                                <div style="display:flex;justify-content:space-between;font-weight:bold;"><span>Cycle Final Rate:</span><span>BDT ${(rt.final_rate || 0).toFixed(2)}</span></div>
                            </div>
                        </div>
                        
                        <div style="margin-top:15px;font-size:9px;">
                            <div style="margin-bottom:8px;">Manager: _____________________</div>
                            <div>Student: _____________________</div>
                        </div>
                    </div>
                    
                    <div>
                        <div style="font-weight:800;font-size:10px;border-bottom:1px solid #ccc;padding-bottom:3px;margin-bottom:5px;">Daily Meal &amp; Rate Log</div>
                        <table style="width:100%;border-collapse:collapse;font-size:9px;">
                            <thead><tr style="background:#eee;"><th style="padding:3px 4px;text-align:left;border:1px solid #ccc;">Date</th><th style="padding:3px 4px;text-align:center;border:1px solid #ccc;">Status</th><th style="padding:3px 4px;text-align:center;border:1px solid #ccc;">L</th><th style="padding:3px 4px;text-align:center;border:1px solid #ccc;">D</th><th style="padding:3px 4px;text-align:right;border:1px solid #ccc;">Day Cost</th></tr></thead>
                            <tbody>${mealRows}</tbody>
                            <tfoot><tr style="background:#f5f5f5;font-weight:bold;"><td colspan="4" style="padding:3px 4px;border:1px solid #ccc;">Total Bill</td><td style="padding:3px 4px;text-align:right;border:1px solid #ccc;">BDT ${(ledger.total_bill || 0).toFixed(2)}</td></tr></tfoot>
                        </table>
                    </div>
                </div>
            </div>
        </div>`;
        
        const wrapper = document.createElement('div');
        wrapper.innerHTML = modalHtml;
        document.body.appendChild(wrapper.firstElementChild);
    } catch (e) {
        showBanner("Failed to load ledger: " + e.message, true);
    }
}

// Select / Deselect all visible rows
function toggleSelectAll(checked) {
    document.querySelectorAll(".sheet-row-chk").forEach(cb => cb.checked = checked);
}

// Apply selected status to checked rows only
async function applyToSelected() {
    const checked = document.querySelectorAll(".sheet-row-chk:checked");
    if (!checked.length) return showBanner("No students selected.", true);
    const status = document.getElementById("sheet-selected-status").value;
    const dStr = document.getElementById("sheet-date-select").value;
    const ids = [...checked].map(cb => parseInt(cb.dataset.user));
    try {
        const result = await apiFetch("/manager/students/bulk-toggle-status", {
            method: "POST",
            body: { user_ids: ids, date: dStr, status: status }
        });
        showBanner(`${result.count} selected student(s) set to "${status}".`);
        await fetchPrintSheet();
    } catch (e) { showBanner(e.message, true); }
}

// Bulk set meal status for all students on current date
async function bulkSetStatus(status) {
    const dStr = document.getElementById("sheet-date-select").value;
    if (!dStr || !managerSheetData.length) return;
    if (!confirm("Set ALL " + managerSheetData.length + " students to \"" + status + "\" for " + dStr + "?")) return;
    try {
        const result = await apiFetch("/manager/students/bulk-toggle-status", {
            method: "POST",
            body: { user_ids: managerSheetData.map(i => i.user_id), date: dStr, status: status }
        });
        showBanner(result.count + "/" + managerSheetData.length + " students updated to \"" + status + "\".");
    } catch (e) { showBanner(e.message, true); }
    await fetchPrintSheet();
}

// Bulk tick/un tick lunch or dinner for all students on current date
async function bulkTick(mealType, ticked) {
    const dStr = document.getElementById("sheet-date-select").value;
    if (!dStr || !managerSheetData.length) return;
    const label = mealType === "lunch" ? "Lunch" : "Dinner";
    const action = ticked ? "Tick" : "Untick";
    if (!confirm(action + " " + label + " for ALL " + managerSheetData.length + " active students?")) return;
    const ids = managerSheetData
        .filter(i => i.status_id && (mealType === "lunch" ? ["both","lunch_only"].includes(i.status) : ["both","dinner_only"].includes(i.status)))
        .map(i => i.status_id);
    if (!ids.length) { showBanner("No eligible students to " + action + ".", true); return; }
    try {
        const result = await apiFetch("/manager/meal-tick/bulk", {
            method: "POST",
            body: { status_ids: ids, meal_type: mealType, ticked: ticked }
        });
        showBanner(result.count + " students " + (ticked ? "ticked" : "unticked") + " for " + label + ".");
    } catch (e) { showBanner(e.message, true); }
    await fetchPrintSheet();
}

// Cycles Management Modal controls
function openCreateCycleModal() {
    document.getElementById("create-cycle-modal").classList.remove("hidden");
    const currentMonth = getLocalMonthString(); // YYYY-MM
    document.getElementById("cycle-month").value = currentMonth;
    document.getElementById("cycle-start-date").value = "";
    document.getElementById("cycle-end-date").value = "";
    document.getElementById("cycle-cutoff").value = "20:00";
}

function closeCreateCycleModal() {
    document.getElementById("create-cycle-modal").classList.add("hidden");
}

async function handleCreateCycle(e) {
    e.preventDefault();
    const month = document.getElementById("cycle-month").value;
    const start_date = document.getElementById("cycle-start-date").value || null;
    const end_date = document.getElementById("cycle-end-date").value || null;
    const cutoff_time = document.getElementById("cycle-cutoff").value;
    
    try {
        await apiFetch("/manager/cycle/start", {
            method: "POST",
            body: { month, cutoff_time, start_date, end_date }
        });
        showBanner(`Dining cycle for ${month} initialized as POLL!`);
        closeCreateCycleModal();
        await loadManagerDashboard();
    } catch (err) {
        showBanner(err.message, true);
    }
}

// Activate dining cycle (move from poll to active)
async function activateCurrentCycle() {
    if (!managerActiveCycle) return;
    try {
        await apiFetch(`/manager/cycle/activate?month=${managerActiveCycle.month}`, {
            method: "POST"
        });
        showBanner(`Dining cycle started for ${managerActiveCycle.month}! Status is now ACTIVE.`);
        await loadManagerDashboard();
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Settle & close dining cycle
async function closeCurrentCycle() {
    if (!managerActiveCycle) return;
    if (!confirm(`WARNING: Closing the cycle for ${managerActiveCycle.month} will execute month-end financial calculations, compute the final meal rate, and deduct costs from all active students' balances. This action is final. Proceed?`)) {
        return;
    }
    
    try {
        const data = await apiFetch(`/manager/cycle/close?month=${managerActiveCycle.month}`, {
            method: "POST"
        });
        showBanner(`Cycle closed! ${data.users_billed} users billed. Final meal rate: BDT ${data.meal_rate}`);
        await loadManagerDashboard();
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Reopen dining cycle
async function reopenCurrentCycle() {
    if (!managerActiveCycle) return;
    if (!confirm(`Are you sure you want to reopen the closed cycle for ${managerActiveCycle.month}? This will reverse the month-end billing deductions, restore student balances to their pre-close states, and reactivate the cycle.`)) {
        return;
    }
    
    try {
        const data = await apiFetch(`/manager/cycle/reopen?month=${managerActiveCycle.month}`, {
            method: "POST"
        });
        showBanner(`Cycle reopened successfully! Balances restored to daily deduction tracking.`);
        await loadManagerDashboard();
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Reset cycle — delete all cycle data and restore balances
async function resetCurrentCycle() {
    if (!managerActiveCycle) return;
    if (!confirm(`DANGER: This will permanently delete the entire cycle for ${managerActiveCycle.month}. All expenses, meal statuses, deposits, and deduction records for this cycle will be removed. Student balances will be restored to their pre-cycle state. This cannot be undone. Proceed?`)) {
        return;
    }
    if (!confirm(`FINAL WARNING: Are you absolutely sure? Type "yes" to confirm.`)) {
        return;
    }
    
    try {
        const data = await apiFetch("/manager/cycle/reset", { method: "POST" });
        showBanner(data.message);
        managerActiveCycle = null;
        await loadManagerDashboard();
    } catch (e) {
        showBanner(e.message, true);
    }
}

// ==========================================
// DJANGO-LIKE SUPERADMIN PANEL LOGIC
// ==========================================
let adminTableData = { columns: [], rows: [] };

async function loadAdminDashboard() {
    try {
        // Fetch financial summary for overview
        const fs = await apiFetch("/manager/financial-summary");
        document.getElementById("admin-total-expenses").textContent = "BDT " + (fs.total_expenses || 0).toFixed(2);
        document.getElementById("admin-total-deposits").textContent = "BDT " + (fs.total_deposits || 0).toFixed(2);
        document.getElementById("admin-remaining").textContent = "BDT " + ((fs.total_deposits || 0) - (fs.total_expenses || 0)).toFixed(2);
        
        // Fetch tables metadata
        const tables = await apiFetch("/admin/tables");
        adminTablesMetadata = tables;
        
        const listDiv = document.getElementById("admin-tables-list");
        listDiv.innerHTML = tables.map(t => `
            <button onclick="selectAdminTable('${t.name}')" class="w-full text-left px-3 py-2 text-xs font-semibold rounded-lg transition ${activeAdminTable === t.name ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/10 shadow-[0_0_10px_rgba(16,185,129,0.02)]' : 'text-slate-400 hover:text-white hover:bg-slate-800/40'}">
                <i class="fa-solid fa-table mr-2 text-[10px]"></i> ${t.name.toUpperCase()}
            </button>
        `).join("");
        
        if (!activeAdminTable && tables.length > 0) {
            selectAdminTable(tables[0].name);
        }
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Feature Control Panel
let studentFeatures = {};

function applySignupLock() {
    const form = document.getElementById("register-form");
    const tabBtn = document.getElementById("tab-register-btn");
    form?.querySelector(".feature-lock-overlay")?.remove();
    const state = checkFeature("signup");
    const locked = !state.enabled || state.locked || state.hidden;
    if (locked) {
        // Lock overlay on form
        if (form) {
            form.style.position = "relative";
            const overlay = document.createElement("div");
            overlay.className = "feature-lock-overlay absolute inset-0 bg-slate-950/80 backdrop-blur-sm flex flex-col items-center justify-center z-10 rounded-2xl";
            overlay.innerHTML = `<i class="fa-solid fa-lock text-amber-400 text-2xl mb-3"></i><p class="text-amber-400 text-sm font-bold text-center px-4">${escapeHtml(state.message || "Registration is currently disabled.")}</p>`;
            form.appendChild(overlay);
            const btn = form.querySelector('button[type="submit"]');
            if (btn) btn.disabled = true;
        }
        // Lock badge on tab button
        if (tabBtn) {
            tabBtn.querySelector(".btn-lock-badge")?.remove();
            tabBtn.style.opacity = "0.5";
            tabBtn.style.pointerEvents = "none";
            tabBtn.title = state.message || "Signup is locked.";
            const badge = document.createElement("span");
            badge.className = "btn-lock-badge";
            badge.innerHTML = '<i class="fa-solid fa-lock text-[8px]"></i>';
            badge.style.cssText = "position:absolute;top:2px;right:2px;background:rgba(251,191,36,0.9);color:#000;border-radius:50%;width:14px;height:14px;display:flex;align-items:center;justify-content:center;z-index:5;";
            tabBtn.style.position = "relative";
            tabBtn.appendChild(badge);
        }
    } else {
        if (form) {
            form.style.position = "";
            const btn = form.querySelector('button[type="submit"]');
            if (btn) btn.disabled = false;
        }
        if (tabBtn) {
            tabBtn.style.opacity = "";
            tabBtn.style.pointerEvents = "";
            tabBtn.title = "";
            tabBtn.querySelector(".btn-lock-badge")?.remove();
        }
    }
}

async function loadStudentFeatureStates() {
    try {
        studentFeatures = await apiFetch("/admin/features/student-check");
    } catch {
        studentFeatures = {};
    }
    // Apply signup lock to registration form regardless of login state
    applySignupLock();
}

function checkFeature(name) {
    return studentFeatures[name] || { enabled: true, locked: false, hidden: false, message: "" };
}

async function openFeaturePanel() {
    try {
        const features = await apiFetch("/admin/features");
        const list = document.getElementById("feature-list");
        const labels = { deposit: "Deposit (bKash/Nagad)", meal_status: "Meal Status Controller",
            calendar: "Calendar Preview", profile: "Dietary Preferences", edit_profile: "Edit Profile Button",
            balance_view: "Balance Display", rate_logs: "Daily Rate Logs", deposit_logs: "Deposit Logs",
            meal_history: "Meal History & Charges", hall_details: "Home Hall Details",
            guest_switcher: "Guest Meal Switcher",
            signup: "Public Registration / Signup",
            transparency_daily_rate: "Transparency: Daily Rate Column",
            transparency_daily_expense: "Transparency: Daily Expense Column",
            transparency_meal_count: "Transparency: Daily Meal Count Column",
            transparency_daily_charge: "Transparency: Daily Charge Column" };
        list.innerHTML = features.map(f => `
            <div class="border border-slate-800 rounded-2xl p-4">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="text-sm font-bold text-white">${labels[f.name] || f.name}</h4>
                    <div class="flex items-center gap-3 text-[10px]">
                        <label class="inline-flex items-center gap-1 cursor-pointer">
                            <input type="checkbox" id="vis-${f.name}" ${!f.hidden ? 'checked' : ''} onchange="updateFeatureFlagSimple('${f.name}')" class="h-3 w-3 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500">
                            <span class="text-slate-400">Visible</span>
                        </label>
                        <label class="inline-flex items-center gap-1 cursor-pointer">
                            <input type="checkbox" id="lock-${f.name}" ${f.locked ? 'checked' : ''} onchange="updateFeatureFlagSimple('${f.name}')" class="h-3 w-3 rounded border-slate-600 bg-slate-800 text-amber-500 focus:ring-amber-500">
                            <span class="text-slate-400">Locked</span>
                        </label>
                    </div>
                </div>
                <div id="msg-row-${f.name}" class="flex items-center gap-2">
                    <i class="fa-solid fa-lock text-[10px] text-amber-400"></i>
                    <input type="text" id="msg-${f.name}" list="lock-msg-${f.name}" placeholder="Type or choose a lock message..." value="${f.message || ''}" oninput="autoSaveLockMessage('${f.name}')" class="flex-1 rounded-xl bg-slate-950 border border-slate-800 py-1.5 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
                    <datalist id="lock-msg-${f.name}">
                        <option value="This feature is currently under maintenance.">
                        <option value="This feature is temporarily disabled.">
                        <option value="Contact your hall manager for access.">
                        <option value="Payment system is offline. Please try again later.">
                        <option value="Meal status changes are locked for today.">
                        <option value="Scheduled maintenance in progress.">
                        <option value="Feature access restricted by administration.">
                    </datalist>
                </div>
            </div>
        `).join("");
        document.getElementById("feature-modal").classList.remove("hidden");
    } catch (e) {
        showBanner(e.message, true);
    }
}

function closeFeaturePanel() {
    document.getElementById("feature-modal").classList.add("hidden");
}

const _debounceTimers = {};
function autoSaveLockMessage(name) {
    clearTimeout(_debounceTimers[name]);
    _debounceTimers[name] = setTimeout(() => saveAllFeatureSettings(name), 400);
}

async function saveAllFeatureSettings(name) {
    const visible = document.getElementById(`vis-${name}`)?.checked ?? true;
    const locked = document.getElementById(`lock-${name}`)?.checked ?? false;
    const msg = document.getElementById(`msg-${name}`)?.value || "";
    try {
        await apiFetch(`/admin/features/${name}?enabled=true&locked=${locked}&hidden=${!visible}&message=${encodeURIComponent(msg)}`, { method: "POST" });
    } catch (e) { /* silent */ }
}

async function updateFeatureFlagSimple(name) {
    await saveAllFeatureSettings(name);
}

async function selectAdminTable(tableName) {
    activeAdminTable = tableName;
    
    // Refresh styles in list
    const listBtns = document.getElementById("admin-tables-list").children;
    for (let btn of listBtns) {
        const isCurrent = btn.textContent.toLowerCase().trim() === tableName;
        btn.className = `w-full text-left px-3 py-2 text-xs font-semibold rounded-lg transition ${isCurrent ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/10 shadow-[0_0_10px_rgba(16,185,129,0.02)]' : 'text-slate-400 hover:text-white hover:bg-slate-800/40'}`;
    }

    document.getElementById("admin-table-title").textContent = `Table: ${tableName.toUpperCase()}`;
    
    const bulkAddBtn = document.getElementById("admin-bulk-add-btn");
    if (bulkAddBtn) {
        if (tableName === "users") {
            bulkAddBtn.classList.remove("hidden");
        } else {
            bulkAddBtn.classList.add("hidden");
        }
    }
    
    await fetchTableData(tableName);
}

// Fetch row data for the selected table
async function fetchTableData(tableName) {
    if (!tableName) return;
    const searchQuery = document.getElementById("admin-table-search").value;
    
    try {
        const data = await apiFetch(`/admin/tables/${tableName}?search=${encodeURIComponent(searchQuery)}`);
        adminTableData = data;
        
        // Render headers with checkbox column
        const theadTr = document.getElementById("admin-thead-tr");
        theadTr.innerHTML = `
            <th class="py-2.5 px-2 w-8"><input type="checkbox" id="admin-select-all" onchange="toggleSelectAllRows(this)" class="h-3.5 w-3.5 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500" title="Select All"></th>
            ${data.columns.map(c => `<th class="py-2.5 px-4 font-semibold uppercase tracking-wider">${c.name}</th>`).join("")}
            <th class="py-2.5 px-4 text-right">Actions</th>
        `;
        
        // Render rows
        const tbody = document.getElementById("admin-tbody");
        const totalCols = data.columns.length + 2;
        if (data.rows.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${totalCols}" class="py-6 text-center text-slate-500">No records found.</td></tr>`;
            document.getElementById("admin-bulk-del-btn").classList.add("hidden");
            return;
        }
        
        document.getElementById("admin-bulk-del-btn").classList.remove("hidden");
        
        tbody.innerHTML = data.rows.map(row => `
            <tr class="hover:bg-slate-900/30">
                <td class="py-2.5 px-2 text-center"><input type="checkbox" class="admin-row-checkbox h-3.5 w-3.5 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500" value="${row.id}" onchange="updateBulkDeleteButton()"></td>
                ${data.columns.map(c => `<td class="py-2.5 px-4 truncate max-w-[150px]" title="${row[c.name] ?? ''}">${row[c.name] ?? '<span class="text-slate-600">null</span>'}</td>`).join("")}
                <td class="py-2.5 px-4 text-right space-x-2">
                    <button onclick="openAdminEditModal(${row.id})" class="text-emerald-400 hover:text-emerald-300 font-bold"><i class="fa-solid fa-pen-to-square"></i> Edit</button>
                    <button onclick="handleAdminDelete(${row.id})" class="text-rose-400 hover:text-rose-300 font-bold"><i class="fa-solid fa-trash"></i> Delete</button>
                </td>
            </tr>
        `).join("");
    } catch (e) {
        showBanner(e.message, true);
    }
}

function toggleSelectAllRows(checkbox) {
    document.querySelectorAll(".admin-row-checkbox").forEach(cb => {
        cb.checked = checkbox.checked;
    });
    updateBulkDeleteButton();
}

function updateBulkDeleteButton() {
    const checked = document.querySelectorAll(".admin-row-checkbox:checked");
    const btn = document.getElementById("admin-bulk-del-btn");
    if (btn) {
        btn.querySelector("span").textContent = `Delete (${checked.length})`;
    }
}

function getSelectedAdminIds() {
    return Array.from(document.querySelectorAll(".admin-row-checkbox:checked")).map(cb => parseInt(cb.value));
}

async function handleAdminBulkDelete() {
    const ids = getSelectedAdminIds();
    if (ids.length === 0) {
        showBanner("No rows selected.", true);
        return;
    }
    if (!confirm(`Delete ${ids.length} selected row(s) from ${activeAdminTable}? This cannot be undone.`)) return;
    try {
        const result = await apiFetch(`/admin/tables/${activeAdminTable}/bulk-delete`, {
            method: "POST",
            body: { ids }
        });
        showBanner(result.message);
        document.getElementById("admin-select-all").checked = false;
        await fetchTableData(activeAdminTable);
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Caching halls for admin select dropdowns
let allHallsCached = [];
async function getAllHallsCached() {
    if (allHallsCached.length === 0) {
        try {
            const response = await fetch(`${API_PREFIX}/student/halls`);
            allHallsCached = await response.json();
        } catch (e) {
            console.error("Failed to fetch halls", e);
        }
    }
    return allHallsCached;
}

// Admin Add & Edit Modals logic
let adminEditingRowId = null;

function closeAdminFormModal() {
    document.getElementById("admin-form-modal").classList.add("hidden");
    adminEditingRowId = null;
}

async function openAdminAddModal() {
    if (!activeAdminTable) return;
    adminEditingRowId = null;
    document.getElementById("admin-modal-title").textContent = `Add new row in ${activeAdminTable.toUpperCase()}`;
    
    const fieldsContainer = document.getElementById("admin-form-fields");
    fieldsContainer.innerHTML = "";
    
    const meta = adminTablesMetadata.find(t => t.name === activeAdminTable);
    if (!meta) return;
    
    for (const c of meta.columns) {
        if (c.name === "id") continue; // Primary key handled by SQLite
        
        const div = document.createElement("div");
        div.className = "space-y-1";
        
        let inputHtml = "";
        
        // Handle select overrides for boolean columns
        if (c.type.startsWith("BOOLEAN")) {
            inputHtml = `
                <select name="${c.name}" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">
                    <option value="true">True</option>
                    <option value="false" selected>False</option>
                </select>
            `;
        } else if (c.name === "role") {
            inputHtml = `
                <select name="${c.name}" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">
                    <option value="student" selected>Student</option>
                    <option value="manager">Manager</option>
                    <option value="assistant_manager">Assistant Manager</option>
                    <option value="superadmin">Superadmin</option>
                </select>
            `;
        } else if (c.name === "hall_id" || c.name === "guest_from_hall_id") {
            const halls = await getAllHallsCached();
            let optionsHtml = '<option value="" selected>None</option>';
            halls.forEach(hall => {
                optionsHtml += `<option value="${hall.id}">${hall.name}</option>`;
            });
            inputHtml = `
                <select name="${c.name}" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">
                    ${optionsHtml}
                </select>
            `;
        } else {
            // Text inputs
            let inputType = "text";
            if (c.type.startsWith("INTEGER") || c.type.startsWith("FLOAT") || c.type.startsWith("NUMERIC")) {
                inputType = "number";
            }
            
            // Custom placeholder for passwords
            let placeholder = "";
            if (c.name === "password_hash" && activeAdminTable === "users") {
                placeholder = "Password (will be automatically hashed)";
            }
            
            inputHtml = `<input type="${inputType}" name="${c.name}" placeholder="${placeholder}" step="any" ${!c.nullable ? 'required' : ''} class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">`;
        }
        
        div.innerHTML = `
            <label class="block text-xs text-slate-400 font-bold uppercase">${c.name}</label>
            ${inputHtml}
        `;
        fieldsContainer.appendChild(div);
    }
    
    document.getElementById("admin-form-modal").classList.remove("hidden");
}

async function openAdminEditModal(rowId) {
    if (!activeAdminTable) return;
    adminEditingRowId = rowId;
    document.getElementById("admin-modal-title").textContent = `Edit row #${rowId} in ${activeAdminTable.toUpperCase()}`;
    
    const fieldsContainer = document.getElementById("admin-form-fields");
    fieldsContainer.innerHTML = "";
    
    const meta = adminTablesMetadata.find(t => t.name === activeAdminTable);
    const row = adminTableData.rows.find(r => r.id === rowId);
    if (!meta || !row) return;
    
    for (const c of meta.columns) {
        if (c.name === "id") continue;
        
        const div = document.createElement("div");
        div.className = "space-y-1";
        
        let inputHtml = "";
        const curVal = row[c.name] ?? "";
        
        if (c.type.startsWith("BOOLEAN")) {
            const isTrue = curVal === true || curVal === "True" || curVal === 1 || curVal === "1";
            inputHtml = `
                <select name="${c.name}" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">
                    <option value="true" ${isTrue ? 'selected' : ''}>True</option>
                    <option value="false" ${!isTrue ? 'selected' : ''}>False</option>
                </select>
            `;
        } else if (c.name === "role") {
            inputHtml = `
                <select name="${c.name}" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">
                    <option value="student" ${curVal === 'student' ? 'selected' : ''}>Student</option>
                    <option value="manager" ${curVal === 'manager' ? 'selected' : ''}>Manager</option>
                    <option value="assistant_manager" ${curVal === 'assistant_manager' ? 'selected' : ''}>Assistant Manager</option>
                    <option value="superadmin" ${curVal === 'superadmin' ? 'selected' : ''}>Superadmin</option>
                </select>
            `;
        } else if (c.name === "hall_id" || c.name === "guest_from_hall_id") {
            const halls = await getAllHallsCached();
            let optionsHtml = `<option value="" ${curVal === "" || curVal === null ? 'selected' : ''}>None</option>`;
            halls.forEach(hall => {
                optionsHtml += `<option value="${hall.id}" ${Number(curVal) === Number(hall.id) ? 'selected' : ''}>${hall.name}</option>`;
            });
            inputHtml = `
                <select name="${c.name}" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">
                    ${optionsHtml}
                </select>
            `;
        } else {
            let inputType = "text";
            if (c.type.startsWith("INTEGER") || c.type.startsWith("FLOAT") || c.type.startsWith("NUMERIC")) {
                inputType = "number";
            }
            
            // For user passwords in admin panel edit, let it be an override field
            if (c.name === "password_hash" && activeAdminTable === "users") {
                inputHtml = `<input type="text" name="password" placeholder="Type new password to change" class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">`;
            } else {
                inputHtml = `<input type="${inputType}" name="${c.name}" value="${curVal}" step="any" ${!c.nullable ? 'required' : ''} class="mt-1 block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-sm focus:outline-none focus:border-emerald-500">`;
            }
        }
        
        div.innerHTML = `
            <label class="block text-xs text-slate-400 font-bold uppercase">${c.name}</label>
            ${inputHtml}
        `;
        fieldsContainer.appendChild(div);
    }
    
    document.getElementById("admin-form-modal").classList.remove("hidden");
}

// Handle Admin Submit Form
async function handleAdminFormSubmit(e) {
    e.preventDefault();
    const form = document.getElementById("admin-row-form");
    const inputs = form.querySelectorAll("input, select");
    
    const payload = {};
    inputs.forEach(inp => {
        if (!inp.name) return;
        let val = inp.value;
        
        // Handle parsing types
        if (inp.type === "number") {
            val = val === "" ? null : parseFloat(val);
        } else if (inp.tagName === "SELECT") {
            if (val === "true" || val === "false") {
                val = val === "true";
            } else if (inp.name === "hall_id" || inp.name === "guest_from_hall_id") {
                val = val === "" ? null : parseInt(val);
            }
        }
        
        payload[inp.name] = val;
    });

    try {
        if (adminEditingRowId) {
            // Edit PUT
            await apiFetch(`/admin/tables/${activeAdminTable}/${adminEditingRowId}`, {
                method: "PUT",
                body: payload
            });
            showBanner(`Updated record #${adminEditingRowId} successfully!`);
        } else {
            // Add POST
            await apiFetch(`/admin/tables/${activeAdminTable}`, {
                method: "POST",
                body: payload
            });
            showBanner(`Added new record successfully!`);
        }
        
        closeAdminFormModal();
        await fetchTableData(activeAdminTable);
    } catch (err) {
        showBanner(err.message, true);
    }
}

// Handle admin deletions
async function handleAdminDelete(rowId) {
    if (!confirm(`Are you sure you want to delete row #${rowId} from ${activeAdminTable}?`)) {
        return;
    }
    try {
        await apiFetch(`/admin/tables/${activeAdminTable}/${rowId}`, {
            method: "DELETE"
        });
        showBanner(`Deleted row #${rowId} successfully!`);
        await fetchTableData(activeAdminTable);
    } catch (e) {
        showBanner(e.message, true);
    }
}

// Autocomplete Student Search for Manager Deposit Form
let depositEntryCount = 0;

function addDepositEntry() {
    const idx = depositEntryCount++;
    const container = document.getElementById("deposit-entries");
    const div = document.createElement("div");
    div.id = `dep-entry-${idx}`;
    div.className = "flex items-start gap-2 p-3 rounded-xl bg-slate-900/40 border border-slate-800";
    div.innerHTML = `
        <div class="flex-1 relative">
            <input id="dep-search-${idx}" type="text" placeholder="Search student..." oninput="handleStudentSearch(this.value, ${idx})" autocomplete="off" class="block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
            <input type="hidden" id="dep-username-${idx}" required>
            <div id="dep-badge-${idx}" class="hidden mt-1 flex items-center justify-between bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-2.5 py-1.5">
                <div>
                    <p id="dep-badge-name-${idx}" class="font-bold text-white text-xs"></p>
                    <p id="dep-badge-meta-${idx}" class="text-[10px] text-slate-400"></p>
                </div>
                <button type="button" onclick="clearDepositEntry(${idx})" class="text-slate-400 hover:text-white bg-slate-900/50 p-1 rounded transition">
                    <i class="fa-solid fa-xmark text-[10px]"></i>
                </button>
            </div>
        </div>
        <div class="w-24 flex-shrink-0">
            <input id="dep-amount-${idx}" type="number" step="any" placeholder="Amount" required class="block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
        </div>
        <div class="w-28 flex-shrink-0">
            <input id="dep-rem-${idx}" type="text" placeholder="Remarks" list="remark-options" class="block w-full rounded-xl bg-slate-950 border border-slate-800 py-2 px-3 text-white text-xs focus:outline-none focus:border-emerald-500">
        </div>
        <button type="button" onclick="removeDepositEntry(${idx})" class="text-rose-400 hover:text-rose-300 bg-rose-500/10 hover:bg-rose-500/20 p-1.5 rounded-lg transition flex-shrink-0 mt-1" title="Remove">
            <i class="fa-solid fa-trash-can text-[10px]"></i>
        </button>
    `;
    container.appendChild(div);
    div.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function removeDepositEntry(idx) {
    const el = document.getElementById(`dep-entry-${idx}`);
    if (el) el.remove();
}

function handleStudentSearch(query, idx) {
    const input = document.getElementById(`dep-search-${idx}`);
    if (!input) return;
    if (!query || query.trim() === "") {
        const timer = window[`_depTimer_${idx}`];
        if (timer) clearTimeout(timer);
        _hideDepResults(idx);
        return;
    }
    
    const term = query.toLowerCase().trim();
    const timer = window[`_depTimer_${idx}`];
    if (timer) clearTimeout(timer);
    window[`_depTimer_${idx}`] = setTimeout(() => _runStudentSearch(term, idx), 180);
}

async function _runStudentSearch(term, idx) {
    const input = document.getElementById(`dep-search-${idx}`);
    if (!input) return;
    _hideDepResults(idx);
    if (!term) return;
    
    let matches = [];
    try {
        matches = await apiFetch(`/manager/students/search?q=${encodeURIComponent(term)}&limit=30`);
    } catch (e) {
        // Fallback: filter the client-side list
        matches = (managerStudents || []).filter(s => {
            return (s.name && s.name.toLowerCase().includes(term)) ||
                   (s.username && s.username.toLowerCase().includes(term)) ||
                   (s.room_number && s.room_number.toLowerCase().includes(term)) ||
                   (s.phone && s.phone.includes(term));
        });
    }
    if (!document.getElementById(`dep-search-${idx}`)) return;
    if (!matches || matches.length === 0) {
        _showDepEmpty(idx);
        return;
    }
    
    // Enrich with balance when available from the already-loaded list
    matches.forEach(m => {
        if (m.balance == null) {
            const ms = (managerStudents || []).find(s => s.id === m.id);
            if (ms) m.balance = ms.balance;
            else m.balance = null;
        }
    });
    
    // Portal: create dropdown as direct child of body to avoid overflow clipping
    const portal = document.createElement("div");
    portal.id = `dep-portal-${idx}`;
    portal.className = "fixed z-[9999]";
    portal.style.minWidth = "250px";
    const rect = input.getBoundingClientRect();
    portal.style.left = rect.left + "px";
    portal.style.top = (rect.bottom + 4) + "px";
    portal.style.width = Math.max(rect.width, 250) + "px";
    
    portal.innerHTML = `
        <div class="max-h-48 overflow-y-auto rounded-xl bg-slate-950/95 border border-slate-800 shadow-2xl backdrop-blur-md">
            ${matches.map((s, mIdx) => `
                <div onclick='selectStudentForDeposit(${mIdx}, ${idx}); _hideDepResults(${idx})' class="p-3 hover:bg-slate-900 border-b border-slate-900/60 last:border-0 cursor-pointer flex items-center justify-between transition text-xs">
                    <div>
                        <p class="font-bold text-white">${s.name} <span class="ml-1 text-[10px] ${s.is_guest ? 'text-amber-400' : 'text-sky-400'}">${s.is_guest ? 'GUEST' : 'NATIVE'}</span></p>
                        <p class="text-[10px] text-slate-400 mt-0.5">Room ${s.room_number || 'N/A'} | ID: ${s.username}</p>
                    </div>
                    <span class="text-[10px] text-slate-500 font-semibold">Bal: BDT ${s.balance != null ? s.balance.toFixed(2) : '—'}</span>
                </div>
            `).join("")}
        </div>`;
    document.body.appendChild(portal);
    window[`_depMatches_${idx}`] = matches;
    
    // Persist dropdown while typing; close only on outside click or selection
    const existing = window[`_depClickHandler_${idx}`];
    if (existing) {
        document.removeEventListener("click", existing);
        window[`_depClickHandler_${idx}`] = null;
    }
    const handler = (e) => {
        if (!portal.contains(e.target) && e.target !== input) {
            _hideDepResults(idx);
        }
    };
    window[`_depClickHandler_${idx}`] = handler;
    setTimeout(() => document.addEventListener("click", handler), 0);
}

function _showDepEmpty(idx) {
    const input = document.getElementById(`dep-search-${idx}`);
    if (!input) return;
    _hideDepResults(idx);
    const portal = document.createElement("div");
    portal.id = `dep-portal-${idx}`;
    portal.className = "fixed z-[9999]";
    portal.style.minWidth = "250px";
    const rect = input.getBoundingClientRect();
    portal.style.left = rect.left + "px";
    portal.style.top = (rect.bottom + 4) + "px";
    portal.style.width = Math.max(rect.width, 250) + "px";
    portal.innerHTML = `<div class="rounded-xl bg-slate-950/95 border border-slate-800 shadow-2xl backdrop-blur-md p-3 text-center text-slate-500 text-xs">No matching users found.</div>`;
    document.body.appendChild(portal);
}

function _hideDepResults(idx) {
    const portal = document.getElementById(`dep-portal-${idx}`);
    if (portal) portal.remove();
    const h = window[`_depClickHandler_${idx}`];
    if (h) {
        document.removeEventListener("click", h);
        window[`_depClickHandler_${idx}`] = null;
    }
}

function selectStudentForDeposit(mIdx, idx) {
    const matches = window[`_depMatches_${idx}`] || [];
    const student = matches[mIdx];
    if (!student) return;
    
    document.getElementById(`dep-username-${idx}`).value = student.username;
    document.getElementById(`dep-search-${idx}`).classList.add("hidden");
    _hideDepResults(idx);
    document.getElementById(`dep-badge-name-${idx}`).textContent = student.name;
    document.getElementById(`dep-badge-meta-${idx}`).textContent = `Room ${student.room_number || 'N/A'} | ID: ${student.username} | Bal: BDT ${student.balance != null ? student.balance.toFixed(2) : '—'}${student.is_guest ? ' | Guest' : ''}`;
    document.getElementById(`dep-badge-${idx}`).classList.remove("hidden");
}

function clearDepositEntry(idx) {
    document.getElementById(`dep-username-${idx}`).value = "";
    document.getElementById(`dep-search-${idx}`).value = "";
    document.getElementById(`dep-search-${idx}`).classList.remove("hidden");
    document.getElementById(`dep-badge-${idx}`).classList.add("hidden");
    _hideDepResults(idx);
}

// Fetch and Populate Manager Cycle summary tab
let managerSummaryData = [];

async function loadCycleSummaryTable() {
    try {
        const data = await apiFetch("/manager/cycle-summary");
        
        const summaryMonth = document.getElementById("summary-month-val");
        const summaryRate = document.getElementById("summary-meal-rate-val");
        const summaryUnits = document.getElementById("summary-total-units-val");
        const summaryExpenses = document.getElementById("summary-net-expenses-val");
        
        if (!data.has_active_cycle) {
            summaryMonth.textContent = "-";
            summaryRate.textContent = "BDT 0.00";
            summaryUnits.textContent = "0.0";
            summaryExpenses.textContent = "BDT 0.00";
            document.getElementById("mgr-summary-tbody").innerHTML = `<tr><td colspan="10" class="py-6 text-center text-xs text-slate-500">No active dining cycle found.</td></tr>`;
            return;
        }
        
        summaryMonth.textContent = data.summary.month;
        summaryRate.textContent = `BDT ${data.summary.running_meal_rate.toFixed(2)}`;
        summaryUnits.textContent = data.summary.total_paying_units.toFixed(1);
        summaryExpenses.textContent = `BDT ${data.summary.net_expenses.toFixed(2)}`;
        
        managerSummaryData = data.students;
        document.getElementById("summary-search").value = "";
        
        renderCycleSummaryData(data.students, data.summary);
    } catch (e) {
        showBanner(e.message, true);
    }
}

function renderCycleSummaryData(students, summary) {
    const tbody = document.getElementById("mgr-summary-tbody");
    
    if (students.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="py-6 text-center text-xs text-slate-500">No student logs found in this cycle.</td></tr>`;
        return;
    }
    
    tbody.innerHTML = students.map(s => {
        const isProjectedNeg = s.projected_balance < 0;
        const studentEscaped = JSON.stringify(s).replace(/'/g, "&apos;").replace(/"/g, "&quot;");
        return `
            <tr class="hover:bg-slate-900/30 text-xs">
                <td class="py-2.5 px-4 font-bold text-white">${s.room_number}</td>
                <td class="py-2.5 px-4 font-semibold text-slate-200">${s.name} (${s.username})</td>
                <td class="py-2.5 px-4">
                    ${s.role === 'Guest' ? `<span class="text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded text-[10px] font-bold">Guest</span>` : `<span class="text-slate-400 text-[10px]">${s.role}</span>`}
                </td>
                <td class="py-2.5 px-4 text-center text-slate-300 font-bold">${s.total_meals_weight.toFixed(1)}</td>
                <td class="py-2.5 px-4 text-center text-emerald-400 font-bold">BDT ${s.total_deposits.toFixed(2)}</td>
                <td class="py-2.5 px-4 text-center text-slate-400">BDT ${s.manager_fees.toFixed(2)}</td>
                <td class="py-2.5 px-4 text-center text-rose-400 font-bold">BDT ${s.current_bill.toFixed(2)}</td>
                <td class="py-2.5 px-4 text-center text-slate-200 font-bold">BDT ${(s.cycle_balance !== undefined ? s.cycle_balance : s.current_balance).toFixed(2)}</td>
                <td class="py-2.5 px-4 text-center font-extrabold ${isProjectedNeg ? 'text-rose-500' : 'text-emerald-400'}">BDT ${s.projected_balance.toFixed(2)}</td>
                <td class="py-2.5 px-4 text-right space-x-2 whitespace-nowrap">
                    <button onclick='printStudentBill(${studentEscaped})' class="text-blue-400 hover:text-blue-300 font-bold" title="Print Bill"><i class="fa-solid fa-print text-[10px] mr-0.5"></i> Print</button>
                    <button onclick='emailStudentBill("${s.username}", "${s.name}")' class="text-emerald-400 hover:text-emerald-300 font-bold" title="Email Bill"><i class="fa-solid fa-envelope text-[10px] mr-0.5"></i> Email</button>
                </td>
            </tr>
        `;
    }).join("");
}

function filterCycleSummary() {
    const query = document.getElementById("summary-search").value.toLowerCase().trim();
    const typeFilter = document.getElementById("summary-type-filter")?.value || "all";
    const filtered = managerSummaryData.filter(s => {
        if (typeFilter === "native" && s.role === "Guest") return false;
        if (typeFilter === "guest" && s.role !== "Guest") return false;
        return (s.name && s.name.toLowerCase().includes(query)) ||
               (s.username && s.username.toLowerCase().includes(query)) ||
               (s.room_number && s.room_number.toLowerCase().includes(query));
    });
    
    const month = document.getElementById("summary-month-val").textContent;
    const rate = parseFloat(document.getElementById("summary-meal-rate-val").textContent.replace("BDT ", ""));
    const units = parseFloat(document.getElementById("summary-total-units-val").textContent);
    const expenses = parseFloat(document.getElementById("summary-net-expenses-val").textContent.replace("BDT ", ""));
    
    renderCycleSummaryData(filtered, {
        month: month,
        running_meal_rate: rate,
        total_paying_units: units,
        net_expenses: expenses
    });
}

async function printStudentBill(student) {
    if (!student) return;

    try {
        const ledger = await apiFetch(`/manager/students/${student.id}/ledger`);

        // Populate header info
        document.getElementById("ledger-hall-name").textContent = ledger.student.hall_name || "eDining Hall";
        document.getElementById("ledger-cycle-month").textContent = ledger.cycle.month || "-";
        document.getElementById("ledger-print-date").textContent = new Date().toLocaleDateString();
        document.getElementById("ledger-student-name").textContent = ledger.student.name;
        document.getElementById("ledger-student-username").textContent = ledger.student.username;
        document.getElementById("ledger-student-room").textContent = ledger.student.room_number || "N/A";

        // Deposits table
        const depTbody = document.getElementById("ledger-deposits-tbody");
        if (ledger.deposits.length === 0) {
            depTbody.innerHTML = `<tr><td colspan="3" style="padding:4px; text-align:center; color:#999; font-size:9px;">No deposits</td></tr>`;
        } else {
            depTbody.innerHTML = ledger.deposits.map(d => `
                <tr>
                    <td style="padding:3px 4px; border:1px solid #ccc;">${d.date}</td>
                    <td style="padding:3px 4px; border:1px solid #ccc; text-align:right;">BDT ${d.amount.toFixed(2)}</td>
                    <td style="padding:3px 4px; border:1px solid #ccc;">${d.description || ''}</td>
                </tr>
            `).join("");
        }
        document.getElementById("ledger-total-deposits").textContent = `BDT ${ledger.total_deposits.toFixed(2)}`;

        // Summary
        document.getElementById("ledger-sum-deposits").textContent = `BDT ${ledger.total_deposits.toFixed(2)}`;
        document.getElementById("ledger-sum-bill").textContent = `BDT ${ledger.total_bill.toFixed(2)}`;
        const balance = ledger.total_deposits - ledger.total_bill;
        document.getElementById("ledger-sum-balance").textContent = `BDT ${balance.toFixed(2)}`;

        // Cycle rates
        document.getElementById("ledger-running-final").textContent = ledger.rates ? `BDT ${ledger.rates.final_rate.toFixed(2)}` : "BDT 0.00";

        // Daily meals table
        const mealsTbody = document.getElementById("ledger-meals-tbody");
        const mealRows = ledger.daily_meals.filter(m => m.status !== 'off');
        if (mealRows.length === 0) {
            mealsTbody.innerHTML = `<tr><td colspan="5" style="padding:4px; text-align:center; color:#999; font-size:9px;">No active meal days</td></tr>`;
        } else {
            const statusLabel = { both: 'Both', lunch_only: 'Lunch', dinner_only: 'Dinner', double: 'Double', triple: 'Triple', off: 'Off' };
            mealsTbody.innerHTML = mealRows.map(m => `
                <tr>
                    <td style="padding:3px 4px; border:1px solid #ccc;">${m.date}</td>
                    <td style="padding:3px 4px; border:1px solid #ccc; text-align:center;">${statusLabel[m.status] || m.status}</td>
                    <td style="padding:3px 4px; border:1px solid #ccc; text-align:center;">${m.ticked_lunch ? '✓' : '-'}</td>
                    <td style="padding:3px 4px; border:1px solid #ccc; text-align:center;">${m.ticked_dinner ? '✓' : '-'}</td>
                    <td style="padding:3px 4px; border:1px solid #ccc; text-align:right; font-weight:bold;">${m.day_cost.toFixed(2)}</td>
                </tr>
            `).join("");
        }
        document.getElementById("ledger-total-bill").textContent = `BDT ${ledger.total_bill.toFixed(2)}`;

        // Add print class to body and print
        document.body.classList.add("print-ledger");
        window.print();
        document.body.classList.remove("print-ledger");
    } catch (err) {
        showBanner("Failed to load student ledger: " + err.message, true);
    }
}

function printDiningSheet() {
    // Set hall name for print header
    const hallName = studentInfo?.user?.hall_name || currentUser?.hall_name || 'eDining Hall';
    document.getElementById("print-hall-name").textContent = `${hallName} \u2014 Daily Meal Sheet`;
    const dStr = document.getElementById("sheet-date-select").value || getLocalDateString();
    document.getElementById("print-date").textContent = `Date: ${dStr}`;
    
    document.body.classList.add("print-sheet");
    window.print();
    document.body.classList.remove("print-sheet");
}

async function emailStudentBill(username, studentName) {
    try {
        const data = await apiFetch("/manager/email-bill", {
            method: "POST",
            body: { username: username, send_all: false }
        });
        showBanner(`Email receipt sent to student ${studentName}!`);
    } catch (e) {
        showBanner(e.message, true);
    }
}

function openEmailProgressModal() {
    document.getElementById("email-progress-modal").classList.remove("hidden");
}

function closeEmailProgressModal() {
    document.getElementById("email-progress-modal").classList.add("hidden");
}

async function emailAllStudentBills(mode) {
    const logsDiv = document.getElementById("email-progress-logs");
    const statusText = document.getElementById("email-progress-status");
    const progressBar = document.getElementById("email-progress-bar");
    
    logsDiv.innerHTML = "";
    progressBar.style.width = "0%";
    statusText.textContent = "Initializing bulk email send...";
    openEmailProgressModal();
    
    const addLog = (msg) => {
        const time = new Date().toLocaleTimeString();
        logsDiv.innerHTML += `<div>[${time}] ${msg}</div>`;
        logsDiv.scrollTop = logsDiv.scrollHeight;
    };
    
    try {
        if (mode === "all_at_once") {
            addLog("Sending all emails at once via backend...");
            const data = await apiFetch("/manager/email-bill", {
                method: "POST",
                body: { send_all: true, mode: "all_at_once" }
            });
            progressBar.style.width = "100%";
            statusText.textContent = "All emails dispatched!";
            addLog(data.message);
            if (data.sent_emails && data.sent_emails.length > 0) {
                addLog(`Dispatched to: ${data.sent_emails.join(", ")}`);
            }
            if (data.skipped_users && data.skipped_users.length > 0) {
                addLog(`Skipped (no email): ${data.skipped_users.join(", ")}`);
            }
        } else if (mode === "one_by_one") {
            addLog(`Dispatched sending mode: One by One (${managerSummaryData.length} students found)...`);
            
            let sentCount = 0;
            let skippedCount = 0;
            const total = managerSummaryData.length;
            
            for (let i = 0; i < total; i++) {
                const s = managerSummaryData[i];
                statusText.textContent = `Sending receipt to student ${i+1} of ${total}: ${s.name}...`;
                
                try {
                    const data = await apiFetch("/manager/email-bill", {
                        method: "POST",
                        body: { username: s.username, mode: "one_by_one" }
                    });
                    
                    if (data.sent_count > 0) {
                        sentCount++;
                        addLog(`SUCCESS: Receipt emailed to ${s.name} (${s.username})`);
                    } else if (data.skipped_users && data.skipped_users.length > 0) {
                        skippedCount++;
                        addLog(`SKIPPED: ${s.name} (${s.username}) - No email address`);
                    }
                } catch (err) {
                    addLog(`ERROR: Failed to email ${s.name} - ${err.message}`);
                }
                
                const pct = Math.round(((i + 1) / total) * 100);
                progressBar.style.width = `${pct}%`;
            }
            
            statusText.textContent = "Bulk emailing process completed!";
            addLog(`Email execution summary: ${sentCount} sent, ${skippedCount} skipped.`);
        }
    } catch (e) {
        addLog(`CRITICAL ERROR: ${e.message}`);
        statusText.textContent = "Failed to execute bulk emailing.";
    }
}

async function loadManagerRates() {
    try {
        const data = await apiFetch("/manager/daily-rates");
        const tbody = document.getElementById("mgr-rates-tbody");
        if (data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-xs text-slate-500">No daily rate data available.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = data.map(r => `
            <tr class="hover:bg-slate-900/40 text-xs">
                <td class="py-2.5 px-3 font-semibold">${r.date}</td>
                <td class="py-2.5 px-3 text-right text-slate-400">BDT ${r.daily_expenses.toFixed(2)}</td>
                <td class="py-2.5 px-3 text-center font-bold text-white">${r.daily_meals}</td>
                <td class="py-2.5 px-3 text-right text-yellow-400 font-bold">BDT ${(r.lunch_rate||0).toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right text-orange-400 font-bold">BDT ${(r.dinner_rate||0).toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right text-emerald-400 font-bold">BDT ${(r.final_rate||0).toFixed(2)}</td>
                <td class="py-2.5 px-3 text-right text-cyan-400 font-bold">BDT ${(r.rate_with_charges||0).toFixed(2)}</td>
            </tr>
        `).join("");
    } catch (e) {
        showBanner(e.message, true);
    }
}

// ==========================================
// BKASH DEPOSIT & SMS SIMULATOR LOGIC
// ==========================================

function openBkashDepositModal() {
    if (!currentUser) return;
    document.getElementById("bkash-ref-username").textContent = currentUser.username;
    document.getElementById("nagad-ref-username").textContent = currentUser.username;
    document.getElementById("bkash-trx-id").value = "";
    const feedback = document.getElementById("bkash-modal-feedback");
    feedback.className = "mt-4 p-3.5 rounded-xl text-xs hidden";
    feedback.textContent = "";
    
    // Load payment numbers
    apiFetch("/manager/public-payment-numbers").then(nums => {
        document.getElementById("pay-bkash-number").textContent = nums.bkash_number || "01700-000000";
        document.getElementById("pay-nagad-number").textContent = nums.nagad_number || "Not configured";
    }).catch(() => {});
    
    document.getElementById("bkash-deposit-modal").classList.remove("hidden");
}

function switchPaymentMethod(method) {
    const bkashTab = document.getElementById("pay-method-bkash");
    const nagadTab = document.getElementById("pay-method-nagad");
    const bkashContent = document.getElementById("pay-bkash-content");
    const nagadContent = document.getElementById("pay-nagad-content");
    const instr = document.getElementById("pay-instructions");
    
    if (method === "bkash") {
        bkashTab.className = "flex-1 py-3 text-sm font-bold text-pink-400 border-b-2 border-pink-500 focus:outline-none flex items-center justify-center gap-2";
        nagadTab.className = "flex-1 py-3 text-sm font-bold text-slate-400 border-b-2 border-transparent hover:text-white focus:outline-none flex items-center justify-center gap-2";
        bkashContent.classList.remove("hidden");
        nagadContent.classList.add("hidden");
        instr.className = "flex-1 bg-[#e2126a]/5 border border-[#e2126a]/15 rounded-2xl p-5 flex flex-col justify-between";
    } else {
        nagadTab.className = "flex-1 py-3 text-sm font-bold text-orange-400 border-b-2 border-orange-500 focus:outline-none flex items-center justify-center gap-2";
        bkashTab.className = "flex-1 py-3 text-sm font-bold text-slate-400 border-b-2 border-transparent hover:text-white focus:outline-none flex items-center justify-center gap-2";
        nagadContent.classList.remove("hidden");
        bkashContent.classList.add("hidden");
        instr.className = "flex-1 bg-orange-500/5 border border-orange-500/15 rounded-2xl p-5 flex flex-col justify-between";
    }
}

function closeBkashDepositModal() {
    document.getElementById("bkash-deposit-modal").classList.add("hidden");
}

async function handleVerifyBkashTrx() {
    const trxIdInput = document.getElementById("bkash-trx-id");
    const trxId = trxIdInput.value.trim().toUpperCase();
    const feedback = document.getElementById("bkash-modal-feedback");
    
    if (!trxId) {
        feedback.className = "mt-4 p-3.5 rounded-xl text-xs bg-rose-500/10 border border-rose-500/25 text-rose-400 block";
        feedback.innerHTML = '<i class="fa-solid fa-circle-xmark mr-1.5"></i> Please enter a Transaction ID.';
        return;
    }
    
    feedback.className = "mt-4 p-3.5 rounded-xl text-xs bg-slate-800 border border-slate-700 text-slate-300 block";
    feedback.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-1.5"></i> Verifying transaction...';
    
    try {
        const data = await apiFetch("/student/bkash/verify-trx", {
            method: "POST",
            body: { trx_id: trxId }
        });
        
        if (data.immediate) {
            feedback.className = "mt-4 p-3.5 rounded-xl text-xs bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 block";
            feedback.innerHTML = '<i class="fa-solid fa-check-circle mr-1.5"></i> ' + (data.message || 'Deposit successful!');
        } else {
            feedback.className = "mt-4 p-3.5 rounded-xl text-xs bg-yellow-500/10 border border-yellow-500/25 text-yellow-400 block";
            feedback.innerHTML = '<i class="fa-solid fa-clock mr-1.5"></i> Transaction submitted for manager approval. Ref: ' + data.trx_id;
        }
        
        setTimeout(() => {
            closeBkashDepositModal();
        }, 3000);
    } catch (e) {
        feedback.className = "mt-4 p-3.5 rounded-xl text-xs bg-rose-500/10 border border-rose-500/25 text-rose-400 block";
        feedback.innerHTML = `<i class="fa-solid fa-circle-xmark mr-1.5"></i> ${e.message}`;
    }
}

function toggleSmsSimulator() {
    const content = document.getElementById("sms-simulator-content");
    const arrow = document.getElementById("sms-sim-arrow");
    const isHidden = content.classList.contains("hidden");
    
    if (isHidden) {
        content.classList.remove("hidden");
        arrow.className = "fa-solid fa-chevron-down text-[10px] transition-transform duration-300";
    } else {
        content.classList.add("hidden");
        arrow.className = "fa-solid fa-chevron-up text-[10px] transition-transform duration-300";
    }
}

function generateRandomTrx() {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    let trx = "";
    for (let i = 0; i < 10; i++) {
        trx += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    document.getElementById("sim-trx").value = trx;
}

async function handleSimulateSms(e) {
    e.preventDefault();
    const sender = document.getElementById("sim-sender").value.trim();
    const amount = parseFloat(document.getElementById("sim-amount").value);
    const trx = document.getElementById("sim-trx").value.trim().toUpperCase();
    
    const logContainer = document.getElementById("sim-log-container");
    const logPre = document.getElementById("sim-log");
    
    logContainer.classList.remove("hidden");
    logPre.className = "bg-slate-900/90 border border-slate-800/80 rounded-xl p-2.5 text-[10px] text-slate-400 font-mono overflow-x-auto whitespace-pre-wrap max-h-24";
    logPre.textContent = "Sending webhook request...";
    
    // Construct simulated SMS message
    const formattedDate = new Date().toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric"
    }) + " " + new Date().toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
    });
    const rawSms = `You have received send money Tk ${amount.toFixed(2)} from ${sender}. TrxID ${trx} at ${formattedDate}`;
    
    try {
        const data = await apiFetch("/student/bkash/webhook", {
            method: "POST",
            body: {
                text: rawSms,
                secret: "edining_bkash_webhook_secret_2026"
            }
        });
        
        logPre.className = "bg-slate-900/90 border border-emerald-500/20 rounded-xl p-2.5 text-[10px] text-emerald-400 font-mono overflow-x-auto whitespace-pre-wrap max-h-24";
        logPre.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
        logPre.className = "bg-slate-900/90 border border-rose-500/20 rounded-xl p-2.5 text-[10px] text-rose-400 font-mono overflow-x-auto whitespace-pre-wrap max-h-24";
        logPre.textContent = `Error: ${err.message}`;
    }
}

// ==========================================
// MOBILE SIDEBAR TOGGLE
// ==========================================
function toggleMobileSidebar() {
    const sidebar = document.getElementById('app-sidebar');
    const overlay = document.getElementById('mobile-overlay');
    if (!sidebar || !overlay) return;
    
    const isOpen = sidebar.classList.contains('open');
    if (isOpen) {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
    } else {
        sidebar.classList.add('open');
        overlay.classList.add('active');
    }
}

function togglePrintOpsMode() {
    const mode = document.getElementById("print-ops-mode").value;
    const single = document.getElementById("print-ops-date-select");
    const rangeWrap = document.getElementById("print-ops-range-wrap");
    const label = document.getElementById("print-ops-date-label");
    const startEl = document.getElementById("print-ops-start-date");
    const endEl = document.getElementById("print-ops-end-date");
    if (mode === "range") {
        label.textContent = "Date Range";
        single.classList.add("hidden");
        rangeWrap.classList.remove("hidden");
        rangeWrap.classList.add("flex");
        if (!startEl.value) startEl.value = single.value || getLocalDateString();
        if (!endEl.value) endEl.value = single.value || getLocalDateString();
    } else {
        label.textContent = "Target Date";
        single.classList.remove("hidden");
        rangeWrap.classList.add("hidden");
        rangeWrap.classList.remove("flex");
        if (!single.value) single.value = startEl.value || getLocalDateString();
    }
}

async function handlePrintOpsLog() {
    const mode = document.getElementById("print-ops-mode").value;
    const typeVal = document.getElementById("print-ops-type-select").value;
    
    let dateVal, endDateVal = null, dateLabelText;
    if (mode === "range") {
        dateVal = document.getElementById("print-ops-start-date").value;
        endDateVal = document.getElementById("print-ops-end-date").value;
        if (!dateVal || !endDateVal) {
            showBanner("Please select a start and end date.", true);
            return;
        }
        if (endDateVal < dateVal) {
            showBanner("End date cannot be before the start date.", true);
            return;
        }
        dateLabelText = `${dateVal} to ${endDateVal}`;
    } else {
        dateVal = document.getElementById("print-ops-date-select").value;
        if (!dateVal) {
            showBanner("Please select a target date.", true);
            return;
        }
        dateLabelText = dateVal;
    }
    
    try {
        const url = endDateVal
            ? `/manager/daily-ops-log?date=${dateVal}&end_date=${endDateVal}`
            : `/manager/daily-ops-log?date=${dateVal}`;
        const data = await apiFetch(url);
        
        // Populate Hall Name, Date, Report Type
        document.getElementById("print-ops-hall-name").textContent = currentUser?.hall_name || 'eDining Hall';
        document.getElementById("print-ops-date").textContent = dateLabelText;
        
        const typeLabels = {
            all: 'All Logs (Expenses + Deposits + Attendance)',
            expenses: 'Expense Records Only',
            deposits: 'Deposit Records Only',
            meals: 'Active Meal Attendance Only'
        };
        document.getElementById("print-ops-report-type").textContent = typeLabels[typeVal];
        
        // Show/hide sections based on selected type
        const expSec = document.getElementById("print-ops-expenses-sec");
        const depSec = document.getElementById("print-ops-deposits-sec");
        const mealsSec = document.getElementById("print-ops-meals-sec");
        
        expSec.style.display = (typeVal === 'all' || typeVal === 'expenses') ? 'block' : 'none';
        depSec.style.display = (typeVal === 'all' || typeVal === 'deposits') ? 'block' : 'none';
        mealsSec.style.display = (typeVal === 'all' || typeVal === 'meals') ? 'block' : 'none';
        
        // Toggle Date column visibility for range reports
        const isRange = !!endDateVal;
        const expDateHdr = document.getElementById("print-ops-exp-date-hdr");
        const depDateHdr = document.getElementById("print-ops-dep-date-hdr");
        const mealsDateHdr = document.getElementById("print-ops-meals-date-hdr");
        if (expDateHdr) expDateHdr.style.display = isRange ? '' : 'none';
        if (depDateHdr) depDateHdr.style.display = isRange ? '' : 'none';
        if (mealsDateHdr) mealsDateHdr.style.display = isRange ? '' : 'none';
        
        // Render Expenses
        const expTbody = document.getElementById("print-ops-expenses-tbody");
        if (data.expenses.length === 0) {
            expTbody.innerHTML = `<tr><td colspan="5" style="padding:4px; text-align:center; color:#777;">No expenses logged for this period.</td></tr>`;
            document.getElementById("print-ops-total-expenses").textContent = "BDT 0.00";
        } else {
            let totalExp = 0.0;
            expTbody.innerHTML = data.expenses.map(e => {
                totalExp += e.amount;
                const mt = (e.meal_type || 'both').toLowerCase();
                const mealLabel = mt.charAt(0).toUpperCase() + mt.slice(1);
                const dateCell = isRange ? `<td style="padding:4px; border:1px solid #ccc; white-space:nowrap;">${e.date}</td>` : '';
                return `
                    <tr>
                        ${dateCell}
                        <td style="padding:4px; border:1px solid #ccc;">${e.description}</td>
                        <td style="padding:4px; border:1px solid #ccc;">${mealLabel}</td>
                        <td style="padding:4px; border:1px solid #ccc; text-align:center;">${e.quantity ? e.quantity + ' ' + (e.unit || '') : '-'}</td>
                        <td style="padding:4px; border:1px solid #ccc; text-align:right;">BDT ${e.amount.toFixed(2)}</td>
                    </tr>
                `;
            }).join("");
            document.getElementById("print-ops-total-expenses").textContent = `BDT ${totalExp.toFixed(2)}`;
        }
        
        // Render Deposits
        const depTbody = document.getElementById("print-ops-deposits-tbody");
        if (data.deposits.length === 0) {
            depTbody.innerHTML = `<tr><td colspan="5" style="padding:4px; text-align:center; color:#777;">No deposits logged for this period.</td></tr>`;
            document.getElementById("print-ops-total-deposits").textContent = "BDT 0.00";
        } else {
            let totalDep = 0.0;
            depTbody.innerHTML = data.deposits.map(d => {
                totalDep += d.amount;
                const dateCell = isRange ? `<td style="padding:4px; border:1px solid #ccc; white-space:nowrap;">${d.date}</td>` : '';
                return `
                    <tr>
                        ${dateCell}
                        <td style="padding:4px; border:1px solid #ccc;">${d.student_username}</td>
                        <td style="padding:4px; border:1px solid #ccc;">${d.student_name}</td>
                        <td style="padding:4px; border:1px solid #ccc;">${d.description || ''}</td>
                        <td style="padding:4px; border:1px solid #ccc; text-align:right;">BDT ${d.amount.toFixed(2)}</td>
                    </tr>
                `;
            }).join("");
            document.getElementById("print-ops-total-deposits").textContent = `BDT ${totalDep.toFixed(2)}`;
        }
        
        // Render Active Meals
        const mealsTbody = document.getElementById("print-ops-meals-tbody");
        if (data.active_meals.length === 0) {
            mealsTbody.innerHTML = `<tr><td colspan="6" style="padding:4px; text-align:center; color:#777;">No active student/guest meals for this period.</td></tr>`;
        } else {
            mealsTbody.innerHTML = data.active_meals.map(m => {
                const statusLabel = { both: 'Both', lunch_only: 'Lunch', dinner_only: 'Dinner', double: 'Double', triple: 'Triple' };
                const label = statusLabel[m.status] || m.status;
                const typeLabel = m.is_guest ? 'Guest' : 'Home Student';
                const dateCell = isRange ? `<td style="padding:4px; border:1px solid #ccc; white-space:nowrap;">${m.date}</td>` : '';
                return `
                    <tr>
                        ${dateCell}
                        <td style="padding:4px; border:1px solid #ccc;">${m.room_number || 'N/A'}</td>
                        <td style="padding:4px; border:1px solid #ccc;">${m.student_username}</td>
                        <td style="padding:4px; border:1px solid #ccc;">${m.student_name}</td>
                        <td style="padding:4px; border:1px solid #ccc; text-align:center;">${label} (L:${m.ticked_lunch ? '✓' : '-'} / D:${m.ticked_dinner ? '✓' : '-'})</td>
                        <td style="padding:4px; border:1px solid #ccc; text-align:center;">${typeLabel}</td>
                    </tr>
                `;
            }).join("");
        }
        
        // Print
        document.body.classList.add("print-ops-log");
        window.print();
        document.body.classList.remove("print-ops-log");
    } catch (err) {
        showBanner("Failed to generate report: " + err.message, true);
    }
}

// PROFILE MODAL FUNCTIONS
function openProfileModal() {
    if (!currentUser) return;
    
    document.getElementById("profile-error").classList.add("hidden");
    document.getElementById("profile-success").classList.add("hidden");
    
    document.getElementById("profile-name").value = currentUser.name || "";
    document.getElementById("profile-phone").value = currentUser.phone || "";
    document.getElementById("profile-email").value = currentUser.email || "";
    document.getElementById("profile-room").value = currentUser.room_number || "";
    document.getElementById("profile-password").value = "";
    
    document.getElementById("profile-modal").classList.remove("hidden");
}

function closeProfileModal() {
    document.getElementById("profile-modal").classList.add("hidden");
}

async function handleProfileUpdate(event) {
    event.preventDefault();
    const errorDiv = document.getElementById("profile-error");
    const successDiv = document.getElementById("profile-success");
    
    errorDiv.classList.add("hidden");
    successDiv.classList.add("hidden");
    
    const payload = {
        name: document.getElementById("profile-name").value.trim(),
        phone: document.getElementById("profile-phone").value.trim() || null,
        email: document.getElementById("profile-email").value.trim() || null,
        room_number: document.getElementById("profile-room").value.trim() || null
    };
    
    const pwd = document.getElementById("profile-password").value;
    if (pwd) {
        payload.password = pwd;
    }
    
    try {
        const updated = await apiFetch("/auth/profile", {
            method: "PUT",
            body: payload
        });
        
        currentUser = updated;
        document.getElementById("sidebar-user-name").textContent = currentUser.name;
        
        successDiv.textContent = "Profile updated successfully!";
        successDiv.classList.remove("hidden");
        
        setTimeout(() => {
            closeProfileModal();
        }, 1500);
        
    } catch (err) {
        errorDiv.textContent = err.message;
        errorDiv.classList.remove("hidden");
    }
}

// Save dietary preference from dashboard dropdown
async function saveDietPreference() {
    const fishEgg = document.getElementById("pref-fish-egg").value;
    const meat = document.getElementById("pref-meat").value;
    try {
        await apiFetch("/auth/profile", {
            method: "PUT",
            body: { fish_egg_pref: fishEgg, meat_pref: meat }
        });
        if (currentUser) {
            currentUser.fish_egg_pref = fishEgg;
            currentUser.meat_pref = meat;
        }
        showBanner("Meal preference saved!");
    } catch (e) {
        showBanner(e.message, true);
    }
}

// ADMIN BULK ADD USERS FUNCTIONS
async function openAdminBulkAddModal() {
    const halls = await getAllHallsCached();
    const select = document.getElementById("bulk-add-hall");
    select.innerHTML = '<option value="">No Hall (nullable)</option>' + 
        halls.map(h => `<option value="${h.id}">${h.name}</option>`).join("");
        
    document.getElementById("bulk-add-error").classList.add("hidden");
    document.getElementById("bulk-add-password").value = "123456";
    document.getElementById("bulk-add-list").value = "";
    
    document.getElementById("admin-bulk-add-modal").classList.remove("hidden");
}

function closeAdminBulkAddModal() {
    document.getElementById("admin-bulk-add-modal").classList.add("hidden");
}

async function handleBulkAddUsers(event) {
    event.preventDefault();
    const errorDiv = document.getElementById("bulk-add-error");
    errorDiv.classList.add("hidden");
    
    const hallIdVal = document.getElementById("bulk-add-hall").value;
    const payload = {
        role: document.getElementById("bulk-add-role").value,
        hall_id: hallIdVal ? parseInt(hallIdVal) : null,
        default_password: document.getElementById("bulk-add-password").value.trim(),
        users_data: document.getElementById("bulk-add-list").value.trim()
    };
    
    try {
        const res = await apiFetch("/admin/users/bulk", {
            method: "POST",
            body: payload
        });
        
        if (res.status === "success") {
            let msg = `Successfully created ${res.created_count} users!`;
            if (res.errors && res.errors.length > 0) {
                msg += ` (Skipped ${res.errors.length} duplicates)`;
                errorDiv.innerHTML = "<strong>Some lines skipped:</strong><br>" + res.errors.join("<br>");
                errorDiv.classList.remove("hidden");
            } else {
                closeAdminBulkAddModal();
            }
            showBanner(msg);
            
            if (res.created_count > 0) {
                await fetchTableData(activeAdminTable);
            }
        }
    } catch (err) {
        errorDiv.textContent = err.message;
        errorDiv.classList.remove("hidden");
    }
}
