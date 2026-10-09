(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const project = localStorage.getItem('bk_last_active_project') || 'Default_Project';
  const storageKey = `bk_video_builder_${project}`;
  const mediaFiles = new Map();
  const previewUrls = new Map();
  const pageSize = 20;
  let page = 0;
  let scenes = [];
  let saveTimer;
  let toastTimer;

  $('projectLabel').textContent = project;
  $('profileLabel').textContent = localStorage.getItem('bk_active_profile_name') || 'Chưa chọn';
  $('apiKeyInput').value = localStorage.getItem('bk_gemini_api_key') || '';

  function toast(message, error = false) {
    const box = $('toast');
    box.textContent = message;
    box.className = error ? 'error' : '';
    box.style.display = 'block';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.style.display = 'none'; }, 4500);
  }

  function timecode(seconds) {
    const n = Math.max(0, Number(seconds) || 0);
    const h = Math.floor(n / 3600), m = Math.floor(n % 3600 / 60), s = Math.floor(n % 60);
    const ms = Math.round((n - Math.floor(n)) * 1000);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(Math.min(ms, 999)).padStart(3, '0')}`;
  }

  function seconds(value) {
    const match = /(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{1,3}/.exec(value || '');
    if (!match) return null;
    const parts = match[0].replace(',', '.').split(':');
    return parts.length === 3 ? Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])
      : Number(parts[0]) * 60 + Number(parts[1]);
  }

  function normalize(scene, index) {
    return {
      id: String(scene.id || index + 1),
      text: String(scene.text || scene.vo || ''),
      start: Math.max(0, Number(scene.start) || 0),
      duration: Math.max(0.2, Number(scene.duration ?? scene.dur) || 4),
      character: String(scene.character || ''),
      background: String(scene.background || ''),
      size: String(scene.size || 'MS'),
      movement: String(scene.movement || scene.mv || 'Static'),
      transition: String(scene.transition || scene.tr || 'Smooth Cut'),
      reason: String(scene.reason || ''),
      image_prompt: String(scene.image_prompt || ''),
      video_prompt: String(scene.video_prompt || ''),
    };
  }

  function parseSrt(raw) {
    const blocks = raw.trim().replace(/\r/g, '').split(/\n\s*\n/);
    const found = [];
    const range = /((?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{1,3})/;
    for (const block of blocks) {
      const lines = block.split('\n').map(line => line.trim()).filter(Boolean);
      const timing = lines.findIndex(line => range.test(line));
      if (timing < 0) continue;
      const match = lines[timing].match(range);
      const start = seconds(match[1]), end = seconds(match[2]);
      const text = lines.slice(timing + 1).join(' ').replace(/<[^>]*>/g, '').trim();
      if (start == null || end == null || end <= start || !text) continue;
      found.push(normalize({id: found.length + 1, text, start, duration: end - start}, found.length));
    }
    return found;
  }

  function readTool2Scenes() {
    let saved;
    try { saved = JSON.parse(localStorage.getItem(`bk_scene_breakdown_data_${project}`) || '{}'); }
    catch { return []; }
    if (!saved.tableHtml) return [];
    const doc = new DOMParser().parseFromString(`<table><tbody>${saved.tableHtml}</tbody></table>`, 'text/html');
    const rows = [];
    let cursor = 0;
    for (const tr of doc.querySelectorAll('tr')) {
      const cells = [...tr.querySelectorAll('td')];
      if (cells.length < 3) continue;
      const val = cell => (cell.querySelector('input,textarea,select')?.value || cell.textContent || '').trim();
      const text = val(cells[2]);
      if (!text || /chưa có phân cảnh/i.test(text)) continue;
      const timing = val(cells[1]);
      const parts = timing.split('-->');
      const start = seconds(parts[0]) ?? cursor;
      const end = seconds(parts[1]) ?? (start + Math.max(2, text.length / 15));
      const duration = Math.max(0.2, end - start);
      rows.push(normalize({id: val(cells[0]), text, start, duration,
        character: cells[3] ? val(cells[3]) : '', background: cells[4] ? val(cells[4]) : ''}, rows.length));
      cursor = start + duration;
    }
    return rows;
  }

  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({scenes, srt: $('srtInput').value,
        style: $('styleInput').value, pace: $('paceSelect').value, updatedAt: Date.now()}));
      $('saveStatus').textContent = 'Đã lưu bản dựng';
    } catch (error) {
      $('saveStatus').textContent = 'Không lưu được';
      toast(`Không lưu được project: ${error.message}`, true);
    }
  }

  function scheduleSave() {
    $('saveStatus').textContent = 'Đang lưu…';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 500);
  }

  function clearMedia() {
    for (const url of previewUrls.values()) URL.revokeObjectURL(url);
    previewUrls.clear();
    mediaFiles.clear();
  }

  function replaceScenes(next, source) {
    if (!next.length) { toast('Nguồn này chưa có cảnh hợp lệ.', true); return; }
    clearMedia();
    scenes = next.map(normalize);
    page = 0;
    $('sourceHint').textContent = `Đã nhập ${scenes.length} cảnh từ ${source}. Hãy duyệt lại trước khi gắn media.`;
    render();
    save();
    toast(`Đã nhập ${scenes.length} cảnh từ ${source}`);
  }

  function promptFor(scene) {
    const style = $('styleInput').value.trim() || 'consistent visual style';
    const context = [scene.background, scene.character].filter(Boolean).join('; ');
    const subject = scene.text.trim().replace(/[.!?。！？]+$/, '');
    const details = [subject, context, style].filter(Boolean).join('. ');
    if (!scene.image_prompt) scene.image_prompt = `${details}. ${scene.size} composition, 16:9, no text overlay.`;
    if (!scene.video_prompt) scene.video_prompt = `${scene.movement} camera movement. ${details}. Duration ${scene.duration.toFixed(1)} seconds, 16:9, no text overlay.`;
  }

  function optionList(select, values, selected) {
    for (const value of values) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
    if (!values.includes(selected)) {
      const option = document.createElement('option');
      option.value = selected;
      option.textContent = selected;
      select.prepend(option);
    }
    select.value = selected;
  }

  function sceneElement(scene, index) {
    const card = document.createElement('article');
    card.className = 'scene';
    card.dataset.index = index;
    card.innerHTML = `<div class="scene-top"><div class="scene-title"><b></b><small></small></div><span class="scene-status"></span></div>
      <div class="scene-grid"><label>LỜI THOẠI<textarea data-field="text" rows="2"></textarea></label>
      <label>BẮT ĐẦU (GIÂY)<input data-field="start" type="number" min="0" step="0.1"></label>
      <label>THỜI LƯỢNG (GIÂY)<input data-field="duration" type="number" min="0.2" step="0.1"></label>
      <label>CỠ CẢNH<select data-field="size"></select></label>
      <label>CHUYỂN ĐỘNG<select data-field="movement"></select></label>
      <label>CHUYỂN CẢNH<select data-field="transition"></select></label>
      <label>NHÂN VẬT<input data-field="character"></label>
      <label>BỐI CẢNH<input data-field="background"></label></div>
      <div class="scene-prompts"><label>PROMPT ẢNH<textarea data-field="image_prompt" rows="3" placeholder="Tạo prompt nền hoặc viết riêng..."></textarea></label>
      <label>PROMPT VIDEO<textarea data-field="video_prompt" rows="3" placeholder="Chuyển động, thời lượng, nhân vật..."></textarea></label></div>
      <div class="scene-asset"><label class="file-button">Gắn ảnh / clip<input class="scene-file" type="file" accept="image/*,video/mp4,video/webm,video/quicktime" hidden></label><span class="asset-name"></span><span class="preview"></span></div>`;
    card.querySelector('.scene-title b').textContent = `CẢNH ${String(index + 1).padStart(3, '0')}`;
    card.querySelector('.scene-title small').textContent = `${timecode(scene.start)} · ${scene.duration.toFixed(1)} giây`;
    for (const field of ['text', 'start', 'duration', 'character', 'background', 'image_prompt', 'video_prompt'])
      card.querySelector(`[data-field="${field}"]`).value = scene[field];
    optionList(card.querySelector('[data-field="size"]'), ['EWS', 'WS', 'MS', 'CU', 'ECU'], scene.size);
    optionList(card.querySelector('[data-field="movement"]'), ['Static', 'Slow Push In', 'Slow Pull Out', 'Pan Left', 'Pan Right', 'Tilt Up', 'Tilt Down', 'Tracking', 'Handheld', 'Rack Focus'], scene.movement);
    optionList(card.querySelector('[data-field="transition"]'), ['Smooth Cut', 'Hard Cut', 'Fade', 'Match Cut', 'Dissolve'], scene.transition);

    const file = mediaFiles.get(index);
    const status = card.querySelector('.scene-status');
    status.textContent = file ? '✓ Đã gắn hình' : '○ Cần ảnh / clip';
    status.classList.toggle('ready', Boolean(file));
    card.querySelector('.asset-name').textContent = file ? file.name : 'Chưa gắn file';
    if (file) {
      let url = previewUrls.get(index);
      if (!url) { url = URL.createObjectURL(file); previewUrls.set(index, url); }
      const preview = document.createElement(file.type.startsWith('video/') ? 'video' : 'img');
      preview.src = url;
      if (preview.tagName === 'VIDEO') { preview.muted = true; preview.controls = true; }
      preview.alt = `Media cảnh ${index + 1}`;
      card.querySelector('.preview').append(preview);
    }
    return card;
  }

  function renderSummary() {
    const duration = scenes.reduce((end, scene) => Math.max(end, scene.start + scene.duration), 0);
    const missing = scenes.length - mediaFiles.size;
    $('metricScenes').textContent = scenes.length;
    $('metricDuration').textContent = `${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, '0')}`;
    $('metricMedia').textContent = `${mediaFiles.size}/${scenes.length}`;
    $('metricMissing').textContent = Math.max(0, missing);
  }

  function render() {
    const list = $('sceneList');
    list.replaceChildren();
    if (!scenes.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'Cảnh sau khi nhập sẽ xuất hiện tại đây.';
      list.append(empty);
    } else {
      const pages = Math.ceil(scenes.length / pageSize);
      page = Math.min(page, pages - 1);
      const start = page * pageSize;
      scenes.slice(start, start + pageSize).forEach((scene, offset) => list.append(sceneElement(scene, start + offset)));
      $('scenePager').hidden = pages <= 1;
      $('pageLabel').textContent = `Trang ${page + 1}/${pages} · cảnh ${start + 1}–${Math.min(start + pageSize, scenes.length)}`;
      $('prevPageBtn').disabled = page === 0;
      $('nextPageBtn').disabled = page >= pages - 1;
    }
    const missing = scenes.length - mediaFiles.size;
    renderSummary();
    $('packageChecklist').replaceChildren();
    for (const [label, done] of [
      ['Cảnh đã nhập', scenes.length > 0], ['Ảnh/clip đầy đủ', scenes.length > 0 && missing === 0],
      ['Giọng đọc', Boolean($('voiceInput').files[0])],
      ['Phụ đề', Boolean($('subtitleInput').files[0] || $('srtInput').value.trim())],
      ['Nhạc nền (tùy chọn)', Boolean($('musicInput').files[0])]]) {
      const badge = document.createElement('span');
      badge.className = done ? 'done' : 'needs';
      badge.textContent = `${done ? '✓' : '○'} ${label}`;
      $('packageChecklist').append(badge);
    }
  }

  $('sceneList').addEventListener('input', event => {
    const card = event.target.closest('.scene');
    const field = event.target.dataset.field;
    if (!card || !field) return;
    const scene = scenes[Number(card.dataset.index)];
    scene[field] = ['start', 'duration'].includes(field) ? Math.max(field === 'duration' ? 0.2 : 0, Number(event.target.value) || 0) : event.target.value;
    if (field === 'start' || field === 'duration') card.querySelector('.scene-title small').textContent = `${timecode(scene.start)} · ${scene.duration.toFixed(1)} giây`;
    if (field === 'start' || field === 'duration') renderSummary();
    scheduleSave();
  });
  $('sceneList').addEventListener('change', event => {
    if (!event.target.classList.contains('scene-file')) return;
    const index = Number(event.target.closest('.scene').dataset.index);
    const file = event.target.files[0];
    if (!file) return;
    if (!/^image\//.test(file.type) && !/^video\//.test(file.type)) { toast('Chỉ nhận ảnh hoặc clip.', true); return; }
    if (previewUrls.has(index)) URL.revokeObjectURL(previewUrls.get(index));
    previewUrls.delete(index);
    mediaFiles.set(index, file);
    render();
  });

  $('importTool2Btn').addEventListener('click', () => replaceScenes(readTool2Scenes(), 'Tool 2'));
  $('importCameraBtn').addEventListener('click', () => {
    let saved;
    try { saved = JSON.parse(localStorage.getItem(`bk_camera_data_${project}`) || '{}'); }
    catch { saved = {}; }
    if (!Array.isArray(saved.shots)) { toast('Chưa có shot được lưu trong Camera Designer.', true); return; }
    let cursor = 0;
    const rows = saved.shots.map((shot, index) => {
      const start = seconds(shot.tc) ?? cursor;
      const normalized = normalize({...shot, start}, index);
      cursor = start + normalized.duration;
      return normalized;
    });
    replaceScenes(rows, 'Camera Designer');
  });
  $('parseSrtBtn').addEventListener('click', () => replaceScenes(parseSrt($('srtInput').value), 'SRT'));
  $('srtFileInput').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    $('srtInput').value = await file.text();
    replaceScenes(parseSrt($('srtInput').value), 'file SRT');
  });
  $('srtInput').addEventListener('input', scheduleSave);
  $('styleInput').addEventListener('input', scheduleSave);
  $('paceSelect').addEventListener('change', scheduleSave);
  $('promptsBtn').addEventListener('click', () => {
    if (!scenes.length) { toast('Hãy nhập cảnh trước.', true); return; }
    scenes.forEach(promptFor);
    render(); save();
    toast(`Đã tạo prompt nền cho ${scenes.length} cảnh. Bạn có thể chỉnh từng prompt.`);
  });
  $('saveKeyBtn').addEventListener('click', () => {
    const key = $('apiKeyInput').value.trim();
    if (key) localStorage.setItem('bk_gemini_api_key', key);
    else localStorage.removeItem('bk_gemini_api_key');
    toast(key ? 'Đã lưu key trong trình duyệt.' : 'Đã xóa key khỏi trình duyệt.');
  });

  $('analyzeBtn').addEventListener('click', async () => {
    if (!scenes.length) { toast('Hãy nhập cảnh trước.', true); return; }
    const button = $('analyzeBtn');
    button.disabled = true;
    button.textContent = 'Đang phân tích…';
    try {
      const response = await fetch('/api/analyze-camera', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          scenes: scenes.map(scene => ({text: scene.text, timecode: `${timecode(scene.start)} --> ${timecode(scene.start + scene.duration)}`, character: scene.character, background: scene.background})),
          api_key: $('apiKeyInput').value.trim(), max_shot_seconds: Number($('paceSelect').value),
          genre: 'explainer', transition_default: 'Smooth Cut',
          style_guide: $('styleInput').value.trim(), constraints: {no_repeat: true, open_wide: true}
        })
      });
      const result = await response.json();
      if (!response.ok || result.status !== 'success') throw new Error(result.message || 'Phân tích thất bại.');
      const shots = result.data?.shots || [];
      shots.forEach((shot, index) => {
        const scene = scenes[index];
        if (!scene) return;
        scene.size = shot.size || scene.size;
        scene.movement = shot.mv || scene.movement;
        scene.transition = shot.tr || scene.transition;
        scene.reason = shot.reason || scene.reason;
      });
      render(); save();
      toast(result.data?.source === 'ai' ? `AI đã thiết kế ${shots.length} cảnh.` : (result.data?.note || 'Đã dùng bộ luật dựng dự phòng.'));
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = 'Phân tích góc máy bằng AI'; }
  });

  $('bulkMediaInput').addEventListener('change', event => {
    const unmatched = [];
    let matched = 0;
    for (const file of event.target.files) {
      const match = /(?:^|[^a-z])(?:scene|shot|canh)?[_\s-]*0*(\d+)(?:[^\d]|$)/i.exec(file.name);
      const index = match ? Number(match[1]) - 1 : -1;
      if (index < 0 || index >= scenes.length || mediaFiles.has(index)) { unmatched.push(file.name); continue; }
      mediaFiles.set(index, file);
      matched++;
    }
    const box = $('unmatchedFiles');
    box.hidden = unmatched.length === 0;
    box.textContent = unmatched.length ? `Chưa ghép ${unmatched.length} file: ${unmatched.slice(0, 6).join(', ')}${unmatched.length > 6 ? '…' : ''}` : '';
    render();
    toast(`Đã ghép ${matched} file theo số cảnh.${unmatched.length ? ` ${unmatched.length} file cần gắn thủ công.` : ''}`);
  });

  for (const [inputId, nameId] of [['voiceInput', 'voiceName'], ['subtitleInput', 'subtitleName'], ['musicInput', 'musicName']]) {
    $(inputId).addEventListener('change', () => { $(nameId).textContent = $(inputId).files[0]?.name || 'Chưa chọn file'; render(); });
  }
  $('prevPageBtn').addEventListener('click', () => { page--; render(); $('sceneCard').scrollIntoView(); });
  $('nextPageBtn').addEventListener('click', () => { page++; render(); $('sceneCard').scrollIntoView(); });

  $('exportBtn').addEventListener('click', async () => {
    if (!scenes.length) { toast('Hãy nhập ít nhất một cảnh trước khi xuất.', true); return; }
    const button = $('exportBtn');
    button.disabled = true;
    button.textContent = 'Đang đóng gói…';
    try {
      save();
      const data = new FormData();
      const assets = [];
      const exported = scenes.map((scene, index) => {
        const item = {...scene};
        if (mediaFiles.has(index)) {
          item.asset_index = assets.length;
          assets.push(mediaFiles.get(index));
        }
        return item;
      });
      const totalBytes = assets.reduce((sum, file) => sum + file.size, 0) +
        ['voiceInput', 'subtitleInput', 'musicInput'].reduce((sum, id) => sum + ($(id).files[0]?.size || 0), 0);
      if (totalBytes > 1024 ** 3) throw new Error('Tổng media vượt 1 GB. Hãy chia thành nhiều gói.');
      data.append('manifest', JSON.stringify({project, profile: $('profileLabel').textContent,
        style: $('styleInput').value, pace_seconds: Number($('paceSelect').value), scenes: exported}));
      assets.forEach(file => data.append('assets', file, file.name));
      if ($('voiceInput').files[0]) data.append('voice', $('voiceInput').files[0]);
      if ($('musicInput').files[0]) data.append('music', $('musicInput').files[0]);
      if ($('subtitleInput').files[0]) data.append('subtitles', $('subtitleInput').files[0]);
      else if ($('srtInput').value.trim()) data.append('subtitles', new Blob([$('srtInput').value], {type: 'text/plain'}), 'voice.srt');
      const response = await fetch('/api/video-builder/package', {method: 'POST', body: data});
      if (!response.ok) { const error = await response.json(); throw new Error(error.message || 'Không đóng gói được.'); }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${project.replace(/[^\w-]/g, '_')}_video_package.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      toast('Đã tải gói dựng. Xem README.txt trong ZIP để tiếp tục.');
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = 'Tải gói dựng ZIP'; }
  });

  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    if (Array.isArray(saved.scenes)) scenes = saved.scenes.map(normalize);
    $('srtInput').value = saved.srt || '';
    $('styleInput').value = saved.style || '';
    $('paceSelect').value = saved.pace || '6';
    if (scenes.length) $('sourceHint').textContent = `Đã khôi phục ${scenes.length} cảnh của project. Hãy gắn lại file media nếu cần.`;
  } catch { toast('Không đọc được bản dựng đã lưu.', true); }
  render();
  window.addEventListener('beforeunload', save);
})();
