(function () {
  'use strict';

  // ── 浮动按钮 ──
  const btn = document.createElement('div');
  btn.id = 'tts-read-aloud-btn';
  btn.textContent = '🔊';
  btn.title = 'TTS: 选中文字后点击朗读';
  document.body.appendChild(btn);

  // ── 恢复上次位置 ──
  const savedPos = localStorage.getItem('tts-btn-pos');
  if (savedPos) {
    const { left, top } = JSON.parse(savedPos);
    btn.style.left = left;
    btn.style.top = top;
    btn.style.right = 'auto';
    btn.style.bottom = 'auto';
  }

  // ── 状态提示 ──
  const toast = document.createElement('div');
  toast.id = 'tts-toast';
  toast.style.display = 'none';
  document.body.appendChild(toast);

  function showToast(msg, duration = 2000) {
    toast.textContent = msg;
    toast.style.display = 'block';
    if (duration > 0) setTimeout(() => { toast.style.display = 'none'; }, duration);
  }

  // ── 拖动逻辑 ──
  let isDragging = false, dragMoved = false;
  let offsetX, offsetY, startX, startY;
  const DRAG_THRESHOLD = 5;

  btn.addEventListener('mousedown', e => {
    isDragging = true;
    dragMoved = false;
    startX = e.clientX;
    startY = e.clientY;
    offsetX = e.clientX - btn.getBoundingClientRect().left;
    offsetY = e.clientY - btn.getBoundingClientRect().top;
    btn.classList.add('dragging');
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!isDragging) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) {
      dragMoved = true;
    }
    if (dragMoved) {
      btn.style.left = (e.clientX - offsetX) + 'px';
      btn.style.top = (e.clientY - offsetY) + 'px';
      btn.style.right = 'auto';
      btn.style.bottom = 'auto';
    }
  });

  document.addEventListener('mouseup', () => {
    if (dragMoved) {
      localStorage.setItem('tts-btn-pos', JSON.stringify({
        left: btn.style.left,
        top: btn.style.top,
      }));
    }
    isDragging = false;
    btn.classList.remove('dragging');
  });

  // ── 点击按钮：直接朗读选中文本 ──
  btn.addEventListener('click', e => {
    if (dragMoved) return;
    const text = window.getSelection().toString().trim();
    if (!text) {
      showToast('请先选中文字', 1500);
      return;
    }
    doRead(text);
  });

  // ── 核心朗读逻辑 ──
  let currentAudio = null;

  async function doRead(text) {
    showToast('正在合成...', 0);
    try {
      const resp = await chrome.runtime.sendMessage({ type: 'synthesize', text });
      if (resp.error) {
        showToast('错误: ' + resp.error, 3000);
        return;
      }
      showToast('播放中...', 0);
      playAudioBase64(resp.audioBase64, resp.format);
    } catch (e) {
      showToast('请求失败: ' + e.message, 3000);
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
    currentAudio.play().catch(e => showToast('播放失败: ' + e.message, 3000));
    currentAudio.onended = () => {
      showToast('播放完成', 1500);
      URL.revokeObjectURL(url);
      currentAudio = null;
    };
    currentAudio.onerror = () => {
      showToast('音频错误', 3000);
      currentAudio = null;
    };
  }

  // ── 监听来自 background 的消息（右键菜单朗读全文）──
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'stopped') {
      if (currentAudio) { currentAudio.pause(); currentAudio = null; }
      showToast('已停止', 1500);
    }
    if (msg.type === 'getFullText') {
      sendResponse(document.body.innerText.trim());
    }
    if (msg.type === 'playAudio') {
      if (msg.error) {
        showToast('错误: ' + msg.error, 3000);
      } else {
        showToast('播放中...', 0);
        playAudioBase64(msg.audioBase64, msg.format);
      }
    }
    if (msg.type === 'ttsError') {
      showToast('错误: ' + msg.error, 3000);
    }
  });
})();
