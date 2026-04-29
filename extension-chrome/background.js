// ── 多引擎 TTS 适配层（Chrome 版，Manifest V3 service worker，chrome.* API）──

const DEFAULTS = {
  engine: 'mimo',
  mimo: { server: 'http://localhost:18900', voice: 'Chloe', director: '', autoDirector: false },
  astra: { server: 'http://localhost:5000', avatar: 'chenxing', useV2: false },
  moss: { server: 'http://localhost:18083', refAudio: 'assets/audio/zh_1.wav' },
};

async function getSettings() {
  const data = await chrome.storage.local.get('ttsSettings');
  return { ...DEFAULTS, ...data.ttsSettings };
}

async function synthesizeMiMo(text, cfg) {
  const body = { text, voice: cfg.voice, director_instruction: cfg.director, auto_director: cfg.autoDirector, model: 'mimo-v2.5-tts', audio_format: 'wav' };
  const resp = await fetch(`${cfg.server}/synthesize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!resp.ok) throw new Error(`MiMo ${resp.status}`);
  const data = await resp.json();
  return { audioBase64: data.audio_base64, format: data.audio_format };
}

async function synthesizeAstra(text, cfg) {
  const body = { text, avatarId: cfg.avatar, useV2: cfg.useV2 };
  const resp = await fetch(`${cfg.server}/api/tts/predict`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!resp.ok) throw new Error(`AstraTTS ${resp.status}`);
  const blob = await resp.blob();
  const b64 = await blobToBase64(blob);
  return { audioBase64: b64, format: 'wav' };
}

async function synthesizeMoss(text, cfg) {
  const resp = await fetch(`${cfg.server}/api/predict`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data: [text, cfg.refAudio, 0.5, 0.5, 20] }) });
  if (!resp.ok) throw new Error(`MOSS ${resp.status}`);
  const result = await resp.json();
  const audioData = result.data?.[0];
  if (!audioData) throw new Error('MOSS 返回无音频');
  const b64 = audioData.includes(',') ? audioData.split(',')[1] : audioData;
  return { audioBase64: b64, format: 'wav' };
}

async function synthesize(text) {
  const s = await getSettings();
  switch (s.engine) {
    case 'mimo': return synthesizeMiMo(text, s.mimo);
    case 'astra': return synthesizeAstra(text, s.astra);
    case 'moss': return synthesizeMoss(text, s.moss);
    default: throw new Error('未知引擎: ' + s.engine);
  }
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => { const r = reader.result; resolve(r.includes(',') ? r.split(',')[1] : r); };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function splitText(text, maxChars = 300) {
  if (text.length <= maxChars) return [text];
  const chunks = [];
  let remaining = text;
  while (remaining.length > 0) {
    if (remaining.length <= maxChars) { chunks.push(remaining); break; }
    let cut = -1;
    const area = remaining.slice(0, maxChars);
    for (const ch of ['。', '！', '？', '\n', '；', '，']) { const idx = area.lastIndexOf(ch); if (idx > 0) { cut = idx + 1; break; } }
    if (cut <= 0) cut = maxChars;
    chunks.push(remaining.slice(0, cut).trim());
    remaining = remaining.slice(cut).trim();
  }
  return chunks.filter(Boolean);
}

let shouldStop = false;

// ── 右键菜单：朗读全文 ──
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'tts-read-full',
    title: '🔊 朗读全文',
    contexts: ['page'],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'tts-read-full') {
    shouldStop = false;
    chrome.tabs.sendMessage(tab.id, { type: 'getFullText' }, text => {
      if (text) handleSynthesize(text).then(result => {
        chrome.tabs.sendMessage(tab.id, { type: 'playAudio', ...result });
      }).catch(e => {
        chrome.tabs.sendMessage(tab.id, { type: 'ttsError', error: e.message });
      });
    });
  }
});

// ── 消息监听 ──
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'synthesize') {
    shouldStop = false;
    handleSynthesize(msg.text).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.type === 'stop') {
    shouldStop = true;
    chrome.tabs.query({}, tabs => { tabs.forEach(tab => chrome.tabs.sendMessage(tab.id, { type: 'stopped' }).catch(() => {})); });
  }
});

async function handleSynthesize(text) {
  const chunks = splitText(text);
  if (chunks.length === 1) return synthesize(chunks[0]);
  const allBytes = [];
  for (let i = 0; i < chunks.length; i++) {
    if (shouldStop) throw new Error('用户取消');
    const result = await synthesize(chunks[i]);
    const binary = atob(result.audioBase64);
    const bytes = new Uint8Array(binary.length);
    for (let j = 0; j < binary.length; j++) bytes[j] = binary.charCodeAt(j);
    allBytes.push(i === 0 ? bytes : bytes.slice(44));
  }
  const totalLen = allBytes.reduce((s, b) => s + b.length, 0);
  const merged = new Uint8Array(totalLen);
  let offset = 0;
  for (const b of allBytes) { merged.set(b, offset); offset += b.length; }
  const view = new DataView(merged.buffer);
  view.setUint32(4, totalLen - 8, true);
  view.setUint32(40, totalLen - 44, true);
  let b64 = '';
  for (let i = 0; i < merged.length; i++) b64 += String.fromCharCode(merged[i]);
  return { audioBase64: btoa(b64), format: 'wav' };
}
