const $ = id => document.getElementById(id);

// 引擎切换：显示/隐藏对应设置面板
$('engine').addEventListener('change', () => {
  const engine = $('engine').value;
  ['mimo', 'astra', 'moss'].forEach(e => {
    $(`${e}-settings`).classList.toggle('hidden', e !== engine);
  });
});

// 加载已保存的设置
async function loadSettings() {
  const data = await chrome.storage.local.get('ttsSettings');
  const s = data.ttsSettings || {};
  $('engine').value = s.engine || 'mimo';
  $('mimo-server').value = s.mimo?.server || 'http://localhost:18900';
  $('mimo-director').value = s.mimo?.director || '';
  $('mimo-auto-director').checked = s.mimo?.autoDirector || false;
  $('astra-server').value = s.astra?.server || 'http://localhost:5000';
  $('astra-v2').checked = s.astra?.useV2 || false;
  $('moss-server').value = s.moss?.server || 'http://localhost:18083';
  $('moss-ref-audio').value = s.moss?.refAudio || 'assets/audio/zh_1.wav';
  // 触发引擎切换
  $('engine').dispatchEvent(new Event('change'));
  // 加载音色列表
  if (s.mimo?.voice) $('mimo-voice').value = s.mimo.voice;
  if (s.astra?.avatar) $('astra-avatar').value = s.astra.avatar;
}

// 刷新 MiMo 音色列表
$('mimo-refresh').addEventListener('click', async () => {
  const server = $('mimo-server').value;
  try {
    const resp = await fetch(`${server}/voices`);
    const data = await resp.json();
    const sel = $('mimo-voice');
    sel.innerHTML = '';
    const all = [...(data.built_in || []), ...(data.custom || []).map(v => v.name)];
    all.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
  } catch (e) {
    alert('无法连接 MiMo 服务器: ' + e.message);
  }
});

// 刷新 AstraTTS 音色列表
$('astra-refresh').addEventListener('click', async () => {
  const server = $('astra-server').value;
  try {
    const resp = await fetch(`${server}/api/tts/fs/avatars?useV2=${$('astra-v2').checked}`);
    const data = await resp.json();
    const sel = $('astra-avatar');
    sel.innerHTML = '';
    (data.avatars || data || []).forEach(avatar => {
      const opt = document.createElement('option');
      opt.value = avatar.id || avatar;
      opt.textContent = avatar.id || avatar;
      sel.appendChild(opt);
    });
  } catch (e) {
    alert('无法连接 AstraTTS 服务器: ' + e.message);
  }
});

// 保存设置
$('save-btn').addEventListener('click', async () => {
  const settings = {
    engine: $('engine').value,
    mimo: {
      server: $('mimo-server').value,
      voice: $('mimo-voice').value,
      director: $('mimo-director').value,
      autoDirector: $('mimo-auto-director').checked,
    },
    astra: {
      server: $('astra-server').value,
      avatar: $('astra-avatar').value,
      useV2: $('astra-v2').checked,
    },
    moss: {
      server: $('moss-server').value,
      refAudio: $('moss-ref-audio').value,
    },
  };
  await chrome.storage.local.set({ ttsSettings: settings });
  const status = $('save-status');
  status.textContent = '已保存';
  setTimeout(() => { status.textContent = ''; }, 2000);
});

loadSettings();
