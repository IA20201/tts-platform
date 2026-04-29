const $ = id => document.getElementById(id);

// 引擎切换：显示/隐藏对应设置面板
$('engine').addEventListener('change', () => {
  const engine = $('engine').value;
  ['mimo', 'astra', 'moss'].forEach(e => {
    $(`${e}-settings`).classList.toggle('hidden', e !== engine);
  });
});

// 刷新 MiMo 音色列表，返回 Promise
async function refreshMimoVoices(server, selectedVoice) {
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
    // 设置选中的音色
    if (selectedVoice && all.includes(selectedVoice)) {
      sel.value = selectedVoice;
    }
  } catch (e) {
    // 服务器未启动，保持默认选项
  }
}

// 刷新 AstraTTS 音色列表
async function refreshAstraAvatars(server, selectedAvatar) {
  try {
    const resp = await fetch(`${server}/api/tts/fs/avatars?useV2=${$('astra-v2').checked}`);
    const data = await resp.json();
    const sel = $('astra-avatar');
    sel.innerHTML = '';
    const avatars = data.avatars || data || [];
    avatars.forEach(avatar => {
      const opt = document.createElement('option');
      opt.value = avatar.id || avatar;
      opt.textContent = avatar.id || avatar;
      sel.appendChild(opt);
    });
    if (selectedAvatar) sel.value = selectedAvatar;
  } catch (e) {
    // 服务器未启动，保持默认选项
  }
}

// 加载已保存的设置
async function loadSettings() {
  const data = await browser.storage.local.get('ttsSettings');
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
  // 先从服务器获取音色列表，再设置保存的值
  await refreshMimoVoices($('mimo-server').value, s.mimo?.voice);
  await refreshAstraAvatars($('astra-server').value, s.astra?.avatar);
}

// 刷新按钮事件
$('mimo-refresh').addEventListener('click', () => refreshMimoVoices($('mimo-server').value, $('mimo-voice').value));
$('astra-refresh').addEventListener('click', () => refreshAstraAvatars($('astra-server').value, $('astra-avatar').value));

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
  await browser.storage.local.set({ ttsSettings: settings });
  const status = $('save-status');
  status.textContent = '已保存';
  setTimeout(() => { status.textContent = ''; }, 2000);
});

loadSettings();
