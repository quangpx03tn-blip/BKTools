/*
 * static/global-sync.js
 *
 * Đồng bộ toàn hệ thống giữa Tool 0 (index.html) và các Tool 1-7.
 *
 * - Tool 0 bấm "HH-Media tools" -> ghi bk_shared_production_data + bk_gemini_api_key.
 * - Mọi tool khác nạp file này: khi mở trang / khi tab được focus / khi có thay đổi
 *   localStorage (event "storage") -> đọc dữ liệu dùng chung, tự điền Active Profile,
 *   API Key, và các Style Prompt (nếu form có trường tương ứng), rồi chuyển trạng thái
 *   API + nút đồng bộ sang MÀU XANH khi thành công.
 * - Bấm nút đồng bộ trên BẤT KỲ tool nào cũng đẩy dữ liệu hiện tại của tool đó lên
 *   kho dùng chung để tất cả tool còn lại tự cập nhật.
 */
(function () {
    "use strict";

    const SHARED_KEY = "bk_shared_production_data";
    const API_KEY_STORAGE = "bk_gemini_api_key";
    const SYNCED_FLAG = "bk_tools_synced";
    const ACTIVE_ID = "bk_active_profile_id";
    const ACTIVE_NAME = "bk_active_profile_name";
    // Danh sách project & project đang mở — dùng chung cho MỌI tool, nhờ vậy
    // project chỉ cần tạo 1 lần ở bất kỳ tool nào là các tool khác thấy ngay.
    const PROJECTS_LIST = "bk_projects_list";
    const ACTIVE_PROJECT = "bk_last_active_project";

    const GREEN = "#10b981";

    function shared() {
        try { return JSON.parse(localStorage.getItem(SHARED_KEY) || "{}"); }
        catch (e) { return {}; }
    }

    function firstEl(selectors) {
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) return el;
        }
        return null;
    }

    function toast(msg) {
        let host = document.getElementById("bkSyncToastHost");
        if (!host) {
            host = document.createElement("div");
            host.id = "bkSyncToastHost";
            host.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;font-family:system-ui,sans-serif;";
            document.body.appendChild(host);
        }
        const box = document.createElement("div");
        box.style.cssText =
            "background:#14161f;border:1px solid " + GREEN + ";color:#e5e7eb;font-size:12px;" +
            "padding:10px 14px;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.45);opacity:0;transform:translateX(20px);transition:.25s;";
        box.textContent = msg;
        host.appendChild(box);
        requestAnimationFrame(() => { box.style.opacity = "1"; box.style.transform = "translateX(0)"; });
        setTimeout(() => {
            box.style.opacity = "0"; box.style.transform = "translateX(20px)";
            setTimeout(() => box.remove(), 300);
        }, 2600);
    }

    function setApiStatusGreen(el, label) {
        if (!el) return;
        el.style.color = GREEN;
        el.classList && el.classList.remove("text-gray-400", "text-gray-500");
        el.innerHTML = label || "&#10004; Đã cấu hình";
    }

    function getStoredProfileData() {
        try { return JSON.parse(localStorage.getItem("bk_active_profile_data") || "{}"); }
        catch (e) { return {}; }
    }

    function applyProfileArea(data) {
        const profileData = getStoredProfileData();
        const id = data.activeProfileId || profileData.id || localStorage.getItem(ACTIVE_ID) || "";
        const name = data.activeProfileName || profileData.ten_kenh || localStorage.getItem(ACTIVE_NAME) || "";
        if (!id && !name) return;

        const idEl = document.getElementById("activeProfileId") || document.querySelector(".profile-status span");
        const nameEl = document.getElementById("activeProfileName") || (() => {
            const profileStatus = document.querySelector(".profile-status");
            const next = profileStatus && profileStatus.nextElementSibling;
            return next && /chưa chọn profile|profile|^[\s\S]{1,120}$/i.test(next.textContent || "") ? next : null;
        })();

        if (idEl && id) {
            idEl.textContent = id;
            idEl.style.color = GREEN;
        }
        if (nameEl && name && name !== "Chưa chọn profile") {
            nameEl.textContent = name;
            nameEl.style.color = GREEN;
            nameEl.style.fontStyle = "normal";
            nameEl.style.fontWeight = "600";
        }
    }

    function applyApiKey(data) {
        const key = (data.apiKey || localStorage.getItem(API_KEY_STORAGE) || "").trim();
        if (!key) return false;
        const input = firstEl(["#sidebarApiKeyInput", ".api-input"]);
        if (input) input.value = key;

        // Cập nhật trạng thái xanh ở mọi chỗ hiển thị trạng thái API trên trang
        const apiStatus = document.getElementById("apiKeyStatus");
        const apiText = document.getElementById("apiKeyStatusText");
        const apiDot = document.getElementById("apiKeyStatusDot");
        const footerStatus = Array.from(document.querySelectorAll(".sidebar-footer div"))
            .find(el => /trạng thái|đã cấu hình|chưa cấu hình/i.test(el.textContent || ""));

        if (apiStatus) setApiStatusGreen(apiStatus, "&#10004; Đã cấu hình");
        if (apiText) setApiStatusGreen(apiText, "Trạng thái: Đã cấu hình");
        if (apiDot) { apiDot.innerText = "✔"; apiDot.style.color = GREEN; }
        if (!apiStatus && !apiText && footerStatus) setApiStatusGreen(footerStatus, "● Trạng thái: Đã cấu hình");
        return true;
    }

    function setValIfPresent(id, value) {
        if (!value) return;
        const el = document.getElementById(id);
        if (!el || el.dataset.noGlobalSync === "true") return;
        el.value = value;
    }

    function applyPrompts(data) {
        const p = data.prompts || {};
        const ctx = data.context_files || {};
        setValIfPresent("charStyle", p.char_style);
        setValIfPresent("bgStyle", p.bg_style);
        setValIfPresent("sceneStyle", p.scene_style);
        setValIfPresent("newCharStyle", p.char_style);
        setValIfPresent("newBgStyle", p.bg_style);
        setValIfPresent("newSceneStyle", p.scene_style);
        setValIfPresent("styleRef", p.style_ref);
        setValIfPresent("newStyleRef", p.style_ref);
        if (ctx.style_guide) window.activeProfileStyleGuide = ctx.style_guide;
        if (ctx.dna) window.activeProfileDna = ctx.dna;
        if (ctx.topic_bank) window.activeProfileTopicBank = ctx.topic_bank;
    }

    function markSyncButtonGreen(btn) {
        if (!btn) return;
        btn.dataset.synced = "1";
        btn.style.borderColor = GREEN;
        btn.style.color = GREEN;
        if (btn.classList && btn.classList.contains("project-box")) {
            btn.style.backgroundColor = "rgba(6,78,59,.35)";
        }
        btn.title = "Đã đồng bộ toàn hệ thống — Nhấn để đồng bộ lại";
    }

    // ── ĐỒNG BỘ DANH SÁCH PROJECT ────────────────────────────────
    // Mọi tool đọc chung 2 key localStorage nên chỉ cần tạo project một lần.
    // Hàm này dựng lại <select> của tool hiện tại theo danh sách dùng chung.

    function readProjects() {
        try {
            const list = JSON.parse(localStorage.getItem(PROJECTS_LIST) || "[]");
            return Array.isArray(list) && list.length ? list : ["Default_Project"];
        } catch (e) {
            return ["Default_Project"];
        }
    }

    function projectSelectEl() {
        return firstEl(["#projectSelectDropdown", "#projectSelect", ".select-project"]);
    }

    function applyProjects() {
        const projects = readProjects();
        let active = localStorage.getItem(ACTIVE_PROJECT) || projects[0];
        if (!projects.includes(active)) active = projects[0];

        // Tool 1-7: chỉ hiển thị tên project dưới dạng chữ (không cho sửa).
        // Việc tạo/chọn project được gom hết về Tool 0.
        const label = document.getElementById("ctxProjectName");
        if (label) {
            label.textContent = active || "—";
            label.style.color = active ? GREEN : "";
        }

        const dd = projectSelectEl();
        if (!dd || dd.tagName !== "SELECT") return;

        // Giữ nguyên option "tạo mới" mà tool đang dùng (mỗi tool đặt tên khác nhau)
        const newOpt = Array.from(dd.options).find(function (o) {
            return o.value === "__new__" || o.value === "" || /new/i.test(o.textContent);
        });
        const newValue = newOpt ? newOpt.value : "__new__";
        const newLabel = newOpt ? newOpt.textContent : "+ New Project…";

        dd.innerHTML =
            '<option value="' + newValue + '">' + newLabel + "</option>" +
            projects.map(function (p) {
                const sel = p === active ? " selected" : "";
                return '<option value="' + p + '"' + sel + ">" + p + "</option>";
            }).join("");
    }

    function applySyncedData() {
        // Project và Profile là dữ liệu ĐIỀU HƯỚNG — luôn áp dụng, không
        // phụ thuộc cờ đã-đồng-bộ. Trước đây profile bị chặn sau cờ này nên
        // chọn profile ở Tool 0 xong, các tool khác vẫn hiện "Chưa chọn
        // profile" cho tới khi bấm nút HH-Media tools.
        applyProjects();

        const data = shared();
        applyProfileArea(data);

        const hasData = Object.keys(data).length > 0;
        if (!hasData && localStorage.getItem(SYNCED_FLAG) !== "1") return;

        // Prompt style và API key mới là nội dung sản xuất -> giữ nguyên
        // điều kiện cũ để không ghi đè thứ người dùng đang gõ dở.
        applyPrompts(data);
        const ok = applyApiKey(data);
        if (ok && localStorage.getItem(SYNCED_FLAG) === "1") {
            markSyncButtonGreen(firstEl(["#syncGlobalToolsBtn", ".project-box"]));
        }
    }

    // Thu thập dữ liệu hiện tại của tool này để đẩy lên kho dùng chung
    function collectCurrentState() {
        const existing = shared();
        const input = firstEl(["#sidebarApiKeyInput", ".api-input"]);
        const apiKey = (input && input.value.trim()) || existing.apiKey || localStorage.getItem(API_KEY_STORAGE) || "";
        const idEl = document.getElementById("activeProfileId");
        const nameEl = document.getElementById("activeProfileName");
        const prompts = {
            char_style: (document.getElementById("charStyle") || document.getElementById("newCharStyle") || {}).value || (existing.prompts || {}).char_style || "",
            bg_style: (document.getElementById("bgStyle") || document.getElementById("newBgStyle") || {}).value || (existing.prompts || {}).bg_style || "",
            scene_style: (document.getElementById("sceneStyle") || document.getElementById("newSceneStyle") || {}).value || (existing.prompts || {}).scene_style || "",
            style_ref: (document.getElementById("styleRef") || document.getElementById("newStyleRef") || {}).value || (existing.prompts || {}).style_ref || ""
        };
        return Object.assign({}, existing, {
            activeProfileId: (idEl && idEl.textContent.trim()) || existing.activeProfileId || localStorage.getItem(ACTIVE_ID) || null,
            activeProfileName: (nameEl && nameEl.textContent.trim()) || existing.activeProfileName || localStorage.getItem(ACTIVE_NAME) || "",
            apiKey: apiKey,
            prompts: prompts,
            context_files: existing.context_files || {},
            syncedAt: Date.now()
        });
    }

    function bindSyncButton() {
        const btn = firstEl(["#syncGlobalToolsBtn", ".project-box"]);
        if (!btn || btn.dataset.bkSyncBound === "1") return;
        btn.dataset.bkSyncBound = "1";
        btn.style.cursor = "pointer";
        btn.addEventListener("click", function (e) {
            // Không bắt sự kiện nếu đây là select/anchor thật (chỉ bắt khi là nút đồng bộ)
            const state = collectCurrentState();
            if (state.apiKey) localStorage.setItem(API_KEY_STORAGE, state.apiKey);
            localStorage.setItem(SHARED_KEY, JSON.stringify(state));
            localStorage.setItem(SYNCED_FLAG, "1");

            // Đẩy luôn project đang mở ở tool này lên kho dùng chung, để các
            // tool khác mở lên là thấy đúng project — không phải tạo lại.
            const dd = projectSelectEl();
            if (dd && dd.value && dd.value !== "__new__") {
                const projects = readProjects();
                if (!projects.includes(dd.value)) {
                    projects.push(dd.value);
                    localStorage.setItem(PROJECTS_LIST, JSON.stringify(projects));
                }
                localStorage.setItem(ACTIVE_PROJECT, dd.value);
            }

            applySyncedData();
            markSyncButtonGreen(btn);
            toast("Đã đồng bộ Project, Active Profile & API sang toàn bộ tools!");
            e.stopPropagation();
        });
    }

    function init() {
        bindSyncButton();
        applySyncedData();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // Tự cập nhật khi Tool 0 đồng bộ ở tab khác, hoặc khi tab được focus lại
    window.addEventListener("storage", function (e) {
        if (e.key === SHARED_KEY || e.key === API_KEY_STORAGE || e.key === SYNCED_FLAG ||
            e.key === PROJECTS_LIST || e.key === ACTIVE_PROJECT) applySyncedData();
    });
    window.addEventListener("focus", applySyncedData);
})();
