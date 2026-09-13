from pathlib import Path

path = Path(r"F:\Bản đã ok\BK Tools - New\templates\video_metadata.html")
text = path.read_text(encoding='utf-8')

# 1) Sidebar: switchLanguage -> changeLanguage + data-lang
old_sidebar = '''            <div class="api-key-label">Ngôn ngữ giao diện</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 12px;">
                <button class="lang-tab active" onclick="switchLanguage('vi')">Tiếng Việt</button>
                <button class="lang-tab" onclick="switchLanguage('en')">English</button>
                <button class="lang-tab" onclick="switchLanguage('ko')">한국어</button>
                <button class="lang-tab" onclick="switchLanguage('zh')">中文</button>
                <button class="lang-tab" onclick="switchLanguage('ja')">日本語</button>
                <button class="lang-tab" onclick="switchLanguage('de')">Deutsch</button>
                <button class="lang-tab" onclick="switchLanguage('es')">Español</button>
                <button class="lang-tab" onclick="switchLanguage('fr')">Français</button>
            </div>'''

new_sidebar = '''            <div class="api-key-label">Ngôn ngữ đầu ra</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 12px;">
                <button class="lang-tab active" data-lang="vi" onclick="changeLanguage('vi')">Tiếng Việt</button>
                <button class="lang-tab" data-lang="en" onclick="changeLanguage('en')">English</button>
                <button class="lang-tab" data-lang="ko" onclick="changeLanguage('ko')">한국어</button>
                <button class="lang-tab" data-lang="zh" onclick="changeLanguage('zh')">中文</button>
                <button class="lang-tab" data-lang="ja" onclick="changeLanguage('ja')">日本語</button>
                <button class="lang-tab" data-lang="de" onclick="changeLanguage('de')">Deutsch</button>
                <button class="lang-tab" data-lang="es" onclick="changeLanguage('es')">Español</button>
                <button class="lang-tab" data-lang="fr" onclick="changeLanguage('fr')">Français</button>
            </div>'''

if old_sidebar not in text:
    raise SystemExit('sidebar block not found')
text = text.replace(old_sidebar, new_sidebar, 1)

# 2) Keep one result language section; remove duplicate bottom section
old_top_lang = '''                <!-- Tab chọn ngôn ngữ đầu ra -->
                <div style="margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid var(--border-color);">
                    <label style="margin-bottom: 10px; display: block;">Chọn ngôn ngữ & Generate lại metadata:</label>
                    <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                        <button class="lang-tab active" onclick="regenerateWithLanguage('vi', this)">🇻🇳 Tiếng Việt</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('en', this)">🇬🇧 English</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('ko', this)">🇰🇷 한국어</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('zh', this)">🇨🇳 中文</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('ja', this)">🇯🇵 日本語</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('es', this)">🇪🇸 Español</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('pt', this)">🇵🇹 Português</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('de', this)">🇩🇪 Deutsch</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('fr', this)">🇫🇷 Français</button>
                        <button class="lang-tab" onclick="regenerateWithLanguage('th', this)">🇹🇭 ไทย</button>
                    </div>
                </div>'''

new_top_lang = '''                <!-- Tab chọn ngôn ngữ đầu ra -->
                <div style="margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid var(--border-color);">
                    <label style="margin-bottom: 10px; display: block;">Chọn ngôn ngữ đầu ra (màu cam = đang chọn):</label>
                    <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                        <button class="lang-tab active" data-lang="vi" onclick="changeLanguage('vi')">🇻🇳 Tiếng Việt</button>
                        <button class="lang-tab" data-lang="en" onclick="changeLanguage('en')">🇬🇧 English</button>
                        <button class="lang-tab" data-lang="ko" onclick="changeLanguage('ko')">🇰🇷 한국어</button>
                        <button class="lang-tab" data-lang="zh" onclick="changeLanguage('zh')">🇨🇳 中文</button>
                        <button class="lang-tab" data-lang="ja" onclick="changeLanguage('ja')">🇯🇵 日本語</button>
                        <button class="lang-tab" data-lang="es" onclick="changeLanguage('es')">🇪🇸 Español</button>
                        <button class="lang-tab" data-lang="pt" onclick="changeLanguage('pt')">🇵🇹 Português</button>
                        <button class="lang-tab" data-lang="de" onclick="changeLanguage('de')">🇩🇪 Deutsch</button>
                        <button class="lang-tab" data-lang="fr" onclick="changeLanguage('fr')">🇫🇷 Français</button>
                        <button class="lang-tab" data-lang="th" onclick="changeLanguage('th')">🇹🇭 ไทย</button>
                    </div>
                </div>'''

if old_top_lang not in text:
    raise SystemExit('top lang block not found')
text = text.replace(old_top_lang, new_top_lang, 1)

old_bottom_lang = '''
                <!-- Language Selection Tabs -->
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border-color);">
                    <label style="margin-bottom: 12px; display: block;">🌐 Tạo lại metadata với ngôn ngữ khác:</label>
                    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px;">
                        <button class="lang-tab active" data-lang="vi">Tiếng Việt</button>
                        <button class="lang-tab" data-lang="en">English</button>
                        <button class="lang-tab" data-lang="ko">한국어</button>
                        <button class="lang-tab" data-lang="zh">中文</button>
                        <button class="lang-tab" data-lang="ja">日本語</button>
                        <button class="lang-tab" data-lang="es">Español</button>
                        <button class="lang-tab" data-lang="pt">Português</button>
                        <button class="lang-tab" data-lang="de">Deutsch</button>
                        <button class="lang-tab" data-lang="fr">Français</button>
                        <button class="lang-tab" data-lang="th">ไทย</button>
                    </div>
                    <button class="btn-action" style="background: linear-gradient(135deg, var(--accent-orange), #ff9500); width: 100%;" onclick="regenerateWithLanguage()">🔄 Generate lại Metadata bằng ngôn ngữ được chọn</button>
                </div>'''

if old_bottom_lang not in text:
    raise SystemExit('bottom lang block not found')
text = text.replace(old_bottom_lang, '', 1)

# 3) Replace JS helpers for language + generate + autosave + regenerate
old_change = '''        function changeLanguage(lang) {
            currentLanguage = lang;
            localStorage.setItem('bk_meta_ui_language', lang);
            updateUIText();
            updateLanguageTabs();
        }'''

new_change = '''        const LANG_API_MAP = {
            'vi': 'Vietnamese',
            'en': 'English',
            'ko': 'Korean',
            'zh': 'Chinese',
            'ja': 'Japanese',
            'es': 'Spanish',
            'pt': 'Portuguese',
            'de': 'German',
            'fr': 'French',
            'th': 'Thai'
        };

        function changeLanguage(lang) {
            if (!lang) return;
            currentLanguage = lang;
            localStorage.setItem('bk_meta_ui_language', lang);
            updateUIText();
            updateLanguageTabs();
        }'''

if old_change not in text:
    raise SystemExit('changeLanguage not found')
text = text.replace(old_change, new_change, 1)

old_tabs = '''        function updateLanguageTabs() {
            const tabs = document.querySelectorAll('.lang-tab');
            tabs.forEach(tab => {
                const lang = tab.dataset.lang;
                if (lang === currentLanguage) {
                    tab.classList.add('active');
                } else {
                    tab.classList.remove('active');
                }
            });
        }'''

new_tabs = '''        function updateLanguageTabs() {
            document.querySelectorAll('.lang-tab').forEach(tab => {
                const lang = tab.dataset.lang;
                if (!lang) return;
                if (lang === currentLanguage) tab.classList.add('active');
                else tab.classList.remove('active');
            });
        }'''

if old_tabs not in text:
    raise SystemExit('updateLanguageTabs not found')
text = text.replace(old_tabs, new_tabs, 1)

old_autosave = '''        function autoSaveData() {
            localStorage.setItem('bk_meta_subject', document.getElementById('meta-subject').value);
            localStorage.setItem('bk_meta_summary', document.getElementById('meta-summary').value);
            localStorage.setItem('bk_meta_keyword', document.getElementById('meta-keyword').value);
            localStorage.setItem('bk_meta_cta', document.getElementById('meta-cta').value);
            localStorage.setItem('bk_meta_tone', document.getElementById('meta-tone').value);
            localStorage.setItem('bk_meta_language', document.getElementById('meta-language').value);

            const indicator = document.getElementById('save-status');
            if (indicator) {
                indicator.style.opacity = '1';
                setTimeout(() => { indicator.style.opacity = '0.6'; }, 1200);
            }
        }'''

new_autosave = '''        function autoSaveData() {
            localStorage.setItem('bk_meta_subject', document.getElementById('meta-subject').value);
            localStorage.setItem('bk_meta_summary', document.getElementById('meta-summary').value);
            localStorage.setItem('bk_meta_keyword', document.getElementById('meta-keyword').value);
            localStorage.setItem('bk_meta_cta', document.getElementById('meta-cta').value);
            localStorage.setItem('bk_meta_tone', document.getElementById('meta-tone').value);
            localStorage.setItem('bk_meta_ui_language', currentLanguage);

            const indicator = document.getElementById('save-status');
            if (indicator) {
                indicator.style.opacity = '1';
                setTimeout(() => { indicator.style.opacity = '0.6'; }, 1200);
            }
        }'''

if old_autosave not in text:
    raise SystemExit('autoSaveData not found')
text = text.replace(old_autosave, new_autosave, 1)

old_gen_lang = '''                const outputLanguage = document.getElementById('meta-output-lang')?.value || 'vi';
                const response = await fetch('/api/generate-metadata', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        api_key: apiKey,
                        subject: subject,
                        summary: summary,
                        keyword: keyword,
                        cta: cta,
                        tone: tone,
                        output_language: outputLanguage
                    })
                });'''

new_gen_lang = '''                const outputLanguage = LANG_API_MAP[currentLanguage] || 'Vietnamese';
                const response = await fetch('/api/generate-metadata', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        api_key: apiKey,
                        subject: subject,
                        summary: summary,
                        keyword: keyword,
                        cta: cta,
                        tone: tone,
                        output_language: outputLanguage
                    })
                });'''

if old_gen_lang not in text:
    raise SystemExit('generateMetadata language block not found')
text = text.replace(old_gen_lang, new_gen_lang, 1)

old_regen = '''        function regenerateWithLanguage(langCode) {
            document.getElementById('meta-language').value = langCode;
            autoSaveData();
            generateMetadata();
        }'''

new_regen = '''        function regenerateWithLanguage(langCode) {
            if (langCode) changeLanguage(langCode);
            autoSaveData();
            generateMetadata();
        }'''

if old_regen not in text:
    raise SystemExit('regenerateWithLanguage not found')
text = text.replace(old_regen, new_regen, 1)

path.write_text(text, encoding='utf-8')
print('HTML patched OK')
