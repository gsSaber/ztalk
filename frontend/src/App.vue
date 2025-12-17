<template>
  <div class="page">
    <header>
      <div class="container">
        <h1>实时语音演示</h1>
        <div class="metrics">
          <div>语音往返: <span>net:{{ state.networkLatencyMs ?? '--' }}</span> ms</div>
          <div>合成延迟: <span>tts:{{ state.synthesisLatency ?? '--' }}</span> ms</div>
          <span class="state">{{ state.streamState }}</span>
        </div>
        <div class="controls">
          <button id="btn-toggle" @click="toggle">{{ state.loading ? 'loading': state.streaming ? '🛑 停止' : '🎙️ 开始' }}</button>
          <button id="btn-view" @click="toggleHistory">{{ showHistory ? '隐藏记录' : '显示记录' }}</button>
        </div>
      </div>
    </header>

    <main class="container">
      <section class="card messages" :class="{ hidden: !showHistory }"><!--动态绑定类名-->
                <article class="msg" v-for="(msg, idx) in state.messages" :key="idx">
                    <span class="role" :class="msg.role">{{ msg.role }}</span>
                    <span>{{ msg.text }}</span>
        </article>
        <p v-if="!state.messages.length" class="placeholder">等待语音输入...</p>
      </section>
    </main>
  </div>
</template>


<script setup lang="ts">
import { reactive, ref } from 'vue'

let lastClientVadStartTs = ref(null);
let waitingFirstUpdateResp = ref(false);
let finishASRTs = ref(null);
// let onChangeCallback = ref(null)
let ws = null;
let vad= null;
// const streamState = ref<'idle' | 'listening' | 'processing' | 'speaking'>('idle')
const showHistory = ref(true)

async function toggle() {
  if (state.streaming) {
      await stopStreaming();
      state.streamState = 'idle';
  } else {
      state.loading = true;
      await startStreaming();
      state.loading = false;
      state.streamState = 'listening';
  }
}
// Start capture with VAD auto mode
async function startStreaming() {
    if (state.streaming) return;

    await initVAD();

    if (vad) {
        await vad.start();
        state.streaming = true;

    } else {
        throw new Error('VAD not initialized');
    }
}

async function stopStreaming() {
    if (!state.streaming) return;
    state.streaming = false;
    if (vad) {
        try {
            if (typeof vad.stop === 'function') {
                await vad.stop();
            } else {
                if (typeof vad.destroy === 'function') vad.destroy();
                if (vad._micStream && vad._micStream.getTracks) {
                    vad._micStream.getTracks().forEach(track => track.stop());
                }
            }
        } catch (_e) {
        } finally {
            vad = null;
        }
    }
}

function toggleHistory() {
  showHistory.value = !showHistory.value
}

function handleIncomingData(event) {
    if (!state.streaming) return;

    if (typeof event.data === 'string') {
        try {
            const json_data = JSON.parse(event.data);
            if (json_data) {
                onIncomingJson(json_data);
            }
        } catch (_e) { }
    }
}

function initWebSocket(onmessage = handleIncomingData) {
    const webSocketUrl = '/ws';
    ws = new WebSocket(webSocketUrl);
    ws.binaryType = 'arraybuffer';
    ws.addEventListener('message', (event) => {
        onmessage(event);
    });
}

const state = reactive({
    networkLatencyMs: null,
    synthesisLatency: null,
    messages: [],
    streaming: false,
    loading: true,
    streamState: 'idle' // 'idle' | 'listening' | 'processing' | 'speaking'
});
// function subscribe(cb) {
//     onChangeCallback = cb;
//     cb({ ...rawState });
// }
// const state = new Proxy(rawState, {
//     set(target, prop, value) {
//         target[prop] = value;
//         if (onChangeCallback) onChangeCallback({ ...target });
//         return true;
//     }
// });
function sendJson(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify(obj)); } catch (_e) { }
    }
}
function sendPCM(int16) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(int16.buffer); } catch (_e) { }//int16的长度等于字节数
    }
}
  // Init Silero VAD
async function initVAD() {
    let isTransmittingAudio = false;
    function sendFrame(frame) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const int16 = new Int16Array(frame.length);
        for (let i = 0; i < frame.length; i++) {
            const s = Math.max(-1, Math.min(1, frame[i]));
            int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        sendPCM(int16);//在 PCM（Pulse Code Modulation）音频中，Int16 的范围是 [-32768, 32767]
    }
    let preSpeechBuffer = [];//这是一个数组，用来存储“语音开始之前”的音频帧。因为 VAD（语音活动检测）通常会有一点延迟，如果只在检测到语音后才开始传输，可能会丢掉开头几个字。这个缓冲区就是为了在检测到语音开始时，把之前的几帧也一起发送出去，避免开头被截断。
    let nonSpeechFrameCount = 0;//计数器，用来统计连续出现的“非语音帧”的数量。
    const MAX_PRE_SPEECH_FRAMES = 20;//preSpeechBuffer最多保存 20 帧，如果超过就丢掉最早的帧。
    const FRAMES_BEFORE_END = 10;//连续10帧都是非语音帧则表示一次语音片段的结束
    const NOT_SPEECH_THRESHOLD = 0.9;
    // Check VAD lib
    if (!window.vad || !window.vad.MicVAD || typeof window.vad.MicVAD.new !== 'function') {
        throw new Error('VAD library not loaded. Please include the VAD script in your HTML (https://github.com/ricky0123/vad).');
    }
    function onSpeechEnd() {
        nonSpeechFrameCount = 0;
        sendJson({ action: "vad_speech_end", timestamp: Date.now() });
        onIncomingJson({ action: 'client_vad_speech_end', data: { timestamp: Date.now() } });
        isTransmittingAudio = false;
    }
    const myvad = await window.vad.MicVAD.new({
        preSpeechPadFrames: 1,
        positiveSpeechThreshold: 0.3,
        negativeSpeechThreshold: 0.05,
        onSpeechStart: () => {
            // Pause TTS immediately on speech
            // pauseTTSPlayback();

            isTransmittingAudio = true;

            // Notify server
            const nowTs = Date.now();
            sendJson({ action: "vad_speech_start", timestamp: nowTs });
            onIncomingJson({ action: 'client_vad_speech_start', data: { timestamp: nowTs } });
        },
        onFrameProcessed: (_probabilities, frame) => {
            if (isTransmittingAudio) {
                if (_probabilities.notSpeech > NOT_SPEECH_THRESHOLD) {
                    nonSpeechFrameCount++;
                }
                if (nonSpeechFrameCount >= FRAMES_BEFORE_END) {
                    onSpeechEnd();
                }
            }
            if (!isTransmittingAudio) {
                if (preSpeechBuffer.length >= MAX_PRE_SPEECH_FRAMES) preSpeechBuffer.shift();
                preSpeechBuffer.push(frame);
            } else {
                for (const bufferedFrame of preSpeechBuffer) sendFrame(bufferedFrame);
                preSpeechBuffer = [];
            }

            if (isTransmittingAudio) sendFrame(frame);
        },
        onSpeechEnd: (_audio) => {
            onSpeechEnd();
        }
    });
    vad = myvad;
}

//---------------上面是声明和定义，下面是执行--------------------------
initWebSocket();
state.loading = false;

function updateLastMessage(newMsg) {
    const normalized = { role: newMsg.role, text: newMsg.content ?? '' };

    if (state.messages.length === 0) {
        state.messages.push(normalized);
        return;
    }

    const lastMsg = state.messages[state.messages.length - 1];
    if (lastMsg.role === normalized.role) {
        lastMsg.text = normalized.text;
    } else {
        state.messages.push(normalized);
    }
}

function onIncomingJson(json) {
    switch (json.action) {
        case 'client_vad_speech_start': {
            const ts = (json.data && json.data.timestamp) || Date.now();
            lastClientVadStartTs = ts;
            state.networkLatencyMs = null;
            state.streamState = 'listening';
            break;
        }
        case 'client_vad_speech_end':
            state.streamState = 'processing';
            break;
        case 'invalid_asr_result':
            state.streamState = 'listening';
            break;
        case 'update_asr': {
            if (lastClientVadStartTs) {
                const now = Date.now();
                state.networkLatencyMs = Math.max(0, now - lastClientVadStartTs);
                lastClientVadStartTs = null;
            }
            updateLastMessage({ role: "User", content: json.data.text });
            break;
        }
        case 'finish_asr': {
            updateLastMessage({ role: "User", content: json.data.text });
            finishASRTs = Date.now();
            waitingFirstUpdateResp = true;
            state.synthesisLatency = null;
            break;
        }
    }
}


</script>
