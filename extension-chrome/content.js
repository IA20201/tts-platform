(function () {
  'use strict';

  // ── 浮动按钮 ──
  const btn = document.createElement('div');
  btn.id = 'tts-read-aloud-btn';
  btn.textContent = '🔊';
  btn.title = 'TTS Read Aloud';
  document.body.appendChild(btn);

  // ── 操作面板 ──
  const panel = document.createElement('div');
  panel.id = 'tts-panel';
  panel.innerHTML = `
    <button class="tts-btn tts-btn-read" id="tts-read-full">📖 朗读全文</button>
    <button class="tts-btn tts-btn-sel" id="tts-read-sel">✂️ 朗读选中</button>
    <button class="tts-btn tts-btn-stop" id="tts-stop" style="display:none">⏹ 停止</button>
    <div class="tts-progress"><div class="tts-progress-bar" id="tts-progress-bar"></div></div>
    <div class="tts-status" id="tts-status"></div>
  `;
  document.body.appendChild(panel);

  // ── 面板定位：始终基于按钮位置 ──
  function updatePanelPosition() {
    const r = btn.getBoundingClientRect();
    panel.style.left = (r.right - 200) + 'px';   // 面板宽 200px，右对齐按钮
    panel.style.top = (r.top - 210) + 'px';       // 面板在按钮上方
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
  }

  // ── 拖动逻辑 ──
  let isDragging = false, offsetX, offsetY, dragMoved = false;
  btn.addEventListener('mousedown', e => {
    isDragging = true;
    dragMoved = false;
    offsetX = e.clientX - btn.getBoundingClientRect().left;
    offsetY = e.clientY - btn.getBoundingClientRect().top;
    btn.classList.add('dragging');
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!isDragging) return;
    dragMoved = true;
    btn.style.left = (e.clientX - offsetX) + 'px';
    btn.style.top = (e.clientY - offsetY) + 'px';
    btn.style.right = 'auto';
    btn.style.bottom = 'auto';
    // 面板跟随拖动
    if (panel.classList.contains('show')) updatePanelPosition();
  });
  document.addEventListener('mouseup', () => {
    isDragging = false;
    btn.classList.remove('dragging');
  });

  // ── 面板切换 ──
  btn.addEventListener('click', e => {
    if (dragMoved) return;  // 拖动结束不触发
    panel.classList.toggle('show');
    if (panel.classList.contains('show')) {
      updatePanelPosition();
      updateSelBtn();
    }
  });

  // 点击外部关闭面板
  document.addEventListener('click', e => {
    if (!btn.contains(e.target) && !panel.contains(e.target)) {
      panel.classList.remove('show');
    }
  });

  // ── 朗读选中按钮状态 ──
  function updateSelBtn() {
    const sel = window.getSelection().toString().trim();
    const selBtn = document.getElementById('tts-read-sel');
    if (sel) {
      selBtn.classList.remove('disabled');
      selBtn.title = sel.slice(0, 50) + (sel.length > 50 ? '...' : '');
    } else {
      selBtn.classList.add('disabled');
      selBtn.title = '请先选中文本';
    }
  }
  document.addEventListener('selectionchange', updateSelBtn);

  // ── 朗读全文 ──
  document.getElementById('tts-read-full').addEventListener('click', () => {
    const text = document.body.innerText.trim();
    if (text) doRead(text);
  });

  // ── 朗读选中 ──
  document.getElementById('tts-read-sel').addEventListener('click', () => {
    const text = window.getSelection().toString().trim();
    if (text) doRead(text);
  });

  // ── 停止 ──
  document.getElementById('tts-stop').addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'stop' });
    hideStop();
  });

  // ── 核心朗读逻辑 ──
  let currentAudio = null;

  async function doRead(text) {
    setStatus('正在合成...');
    showStop();
    try {
      const resp = await chrome.runtime.sendMessage({ type: 'synthesize', text });
      if (resp.error) {
        setStatus('错误: ' + resp.error);
        hideStop();
        return;
      }
      setStatus('播放中...');
      playAudioBase64(resp.audioBase64, resp.format);
    } catch (e) {
      setStatus('请求失败: ' + e.message);
      hideStop();
    }
  }

  function playAudioBase64(b64, format) {
    const mime = format === 'mp3' ? 'audio/mpeg' : 'audio/wav';
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: mime });
    const url = URL.createObjectURL(blob);

    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    currentAudio = new Audio(url);
    currentAudio.play().catch(e => setStatus('播放失败: ' + e.message));
    currentAudio.onended = () => {
      setStatus('播放完成');
      hideStop();
      URL.revokeObjectURL(url);
    };
    currentAudio.onerror = () => {
      setStatus('音频错误');
      hideStop();
    };
  }

  function setStatus(msg) {
    document.getElementById('tts-status').textContent = msg;
  }
  function showStop() {
    document.getElementById('tts-stop').style.display = 'block';
    document.getElementById('tts-read-full').style.display = 'none';
    document.getElementById('tts-read-sel').style.display = 'none';
  }
  function hideStop() {
    document.getElementById('tts-stop').style.display = 'none';
    document.getElementById('tts-read-full').style.display = 'block';
    document.getElementById('tts-read-sel').style.display = 'block';
    currentAudio = null;
  }

  chrome.runtime.onMessage.addListener(msg => {
    if (msg.type === 'stopped') {
      if (currentAudio) { currentAudio.pause(); currentAudio = null; }
      setStatus('已停止');
      hideStop();
    }
  });
})();
