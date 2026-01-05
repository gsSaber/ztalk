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

const playingSources = [];
const audioQueue = [];
let ttsStreamActive = false;
let ttsStreamFinished = false;
let lastClientVadStartTs = ref(null);
let waitingFirstUpdateResp = ref(false);
let finishASRTs = ref(null);
let audioCtx = null;
let ws = null;
let vad= null;
const showHistory = ref(true)
let TTS_SAMPLE_RATE = 48000;
let LOCAL_SAMPLE_RATE = 44100;
// Poll timer for "wait for next chunk" when active
let playPollTimer = null;
let newAudioOutputCallback = (float32, sampleRate) => {
            try {
                ensureAudioContext();
                if (!audioCtx) return;

                // Ensure analyser exists and arrays are sized
                if (!outAnalyser) {
                    outAnalyser = audioCtx.createAnalyser();
                    outAnalyser.fftSize = 1024;
                    outAnalyser.smoothingTimeConstant = 0.7;
                    outBufferLength = outAnalyser.fftSize;
                    outDataArray = new Uint8Array(outBufferLength);
                }
                // Ensure silent pull chain (no audible playback)
                if (!outAnalyserConnected) {
                    if (!silentGain) {
                        silentGain = audioCtx.createGain();
                        silentGain.gain.value = 0;
                        silentGain.connect(audioCtx.destination);
                    }
                    outAnalyser.connect(silentGain);
                    outAnalyserConnected = true;
                }

                // Create and feed a BufferSource from raw PCM (silent due to zero-gain chain)
                const buffer = audioCtx.createBuffer(1, float32.length, sampleRate);
                buffer.getChannelData(0).set(float32);
                const src = audioCtx.createBufferSource();
                src.buffer = buffer;

                // Connect: src -> analyser -> silentGain(0) -> destination
                src.connect(outAnalyser);
                src.start();
                src.addEventListener('ended', () => {
                    try { src.disconnect(); } catch { }
                });
            } catch (e) {
                console.log(e);
            }
        };


function stopAllPlayback() {
    markTTSStreamState('reset');
    
    if (playPollTimer) {
        clearTimeout(playPollTimer);
        playPollTimer = null;
    }

    playingSources.forEach((src) => { try { src.stop(); } catch (_e) { } });
    playingSources.length = 0;
    audioQueue.length = 0;

    if (audioCtx) {
        if (audioCtx.state !== 'suspended') {
            audioCtx.close();
        }
        audioCtx = null;
    }
}

function markTTSStreamState(state) {
    switch (state) {
        case 'active':
            ttsStreamActive = true;
            ttsStreamFinished = false;
            break;
        case 'finished':
            ttsStreamActive = false;
            ttsStreamFinished = true;
            break;
        case 'reset':
        case 'idle':
            ttsStreamActive = false;
            ttsStreamFinished = false;
            break;
        default:
            break;
    }
}

function ensureAudioCtx() {
    if (!audioCtx) {
        try {
            audioCtx = new AudioContext({ sampleRate: LOCAL_SAMPLE_RATE });
        } catch (_e) {
            audioCtx = new AudioContext();
        }
    }
}

// Use a stateless linear resampler per chunk
function resampleChunkPCM(src, fromRate, toRate) {
    if (!src || src.length === 0) return src || new Float32Array(0);
    if (fromRate === toRate) return src;
    const outLen = Math.max(1, Math.round(src.length * toRate / fromRate));
    const out = new Float32Array(outLen);
    const ratio = fromRate / toRate; // input samples per output sample
    for (let j = 0; j < outLen; j++) {
        const pos = j * ratio;
        const i = Math.floor(pos);
        const frac = pos - i;
        const s0 = src[i] ?? 0;
        const i1 = i + 1 < src.length ? i + 1 : i;
        const s1 = src[i1] ?? s0;
        out[j] = s0 + (s1 - s0) * frac;
    }
    return out;
}

// Serial playback
function playNextAudio() {
    // Do not start when AudioContext is paused
    if (audioCtx && audioCtx.state === 'suspended') return;

    if (audioQueue.length === 0) {
        return;
    }

    if (playingSources.length > 0) {
        return; // Wait current source end
    }

    const float32 = audioQueue.shift();
    newAudioOutputCallback && newAudioOutputCallback(float32, audioCtx ? audioCtx.sampleRate : LOCAL_SAMPLE_RATE);
    // Use local AudioContext sample rate for playback
    const buffer = audioCtx.createBuffer(1, float32.length, audioCtx.sampleRate);
    buffer.getChannelData(0).set(float32);
    const src = audioCtx.createBufferSource();
    src.buffer = buffer;
    src.connect(audioCtx.destination);

    src.onended = () => {
        const idx = playingSources.indexOf(src);
        if (idx !== -1) playingSources.splice(idx, 1);

        if (playingSources.length === 0) playNextAudio();

        if (playingSources.length === 0 && audioQueue.length === 0) {
            if (ttsStreamFinished) {
                sendJson({ action: "tts_playback_finished", timestamp: Date.now() });
                // Reset after playback drain
                markTTSStreamState('reset');
                onIncomingJson({ action: 'client_tts_playback_finished', data: { timestamp: Date.now() } });
            }
        }
    };

    src.onerror = () => {
        const idx = playingSources.indexOf(src);
        if (idx !== -1) playingSources.splice(idx, 1);
        if (playingSources.length === 0) playNextAudio();
    };

    playingSources.push(src);
    src.start();
}

function enableAllPlayback() {
        // Guard when stream marked finished/reset
        if (ttsStreamFinished) return;

        ensureAudioCtx();

        // 如果 audioCtx 被暂停，需要恢复它才能播放
        if (audioCtx && audioCtx.state === 'suspended') {
            audioCtx.resume().then(() => {
                playNextAudio();
            }).catch(() => { });
        } else {
            playNextAudio();
        }
}

// function resumeTTSPlayback() {
//     ensureAudioCtx();
//     if (audioCtx.state === 'suspended') {
//         audioCtx.resume().then(() => {
//             if (playingSources.length === 0 && audioQueue.length > 0) {
//                 playNextAudio();
//             }
//         }).catch(() => { });
//     } else if (playingSources.length === 0 && audioQueue.length > 0) {
//         playNextAudio();
//     }
// }
function pauseTTSPlayback() {
    if (audioCtx && audioCtx.state === 'running') {
        audioCtx.suspend().catch(() => {
            playingSources.forEach((src) => { try { src.stop(); } catch (_e2) { } });
            playingSources.length = 0;
        });
    } else {
        playingSources.forEach((src) => { try { src.stop(); } catch (_e) { } });
        playingSources.length = 0;
    }
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
        return;
    }
    if (event.data instanceof ArrayBuffer) {
        if (ttsStreamFinished) return;

        const int16 = new Int16Array(event.data);
        if (int16.length === 0) return;

        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

        ensureAudioCtx();
        const targetRate = audioCtx ? audioCtx.sampleRate : LOCAL_SAMPLE_RATE;
        const resampled = resampleChunkPCM(float32, TTS_SAMPLE_RATE, targetRate);

        audioQueue.push(resampled);
        enableAllPlayback();
        return;
    }
}

// Start capture with VAD auto mode
async function startStreaming() {
    if (state.streaming) return;

    await initVAD();

    if (vad) {
        await vad.start();
        state.streaming = true;

        sendJson({ action: "conversation_start", timestamp: Date.now() });
    } else {
        throw new Error('VAD not initialized');
    }
}

async function stopStreaming() {
    // Reset TTS flags and stop playback first
        markTTSStreamState('reset');
        stopAllPlayback();

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

        sendJson({ action: "conversation_end", timestamp: Date.now() });
}

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
function toggleHistory() {
  showHistory.value = !showHistory.value
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
            // Stop TTS immediately on speech and clear audio queue
            stopAllPlayback();

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
function initWebSocket(onmessage = handleIncomingData) {
    const webSocketUrl = '/ws';
    ws = new WebSocket(webSocketUrl);
    ws.binaryType = 'arraybuffer';
    ws.addEventListener('message', (event) => {
        onmessage(event);
    });
}

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

function  onIncomingJson(json) {
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
        case 'start_tts':
            markTTSStreamState('active');
            state.streamState = 'speaking';
            break;
        case 'stop_tts':
            stopAllPlayback();
            break;
        case 'finish_resp': {
            updateLastMessage({ role:"Ai", content: json.data.text });
            markTTSStreamState('finished');
            break;
        }
        case 'update_resp': {
            if (waitingFirstUpdateResp && finishASRTs) {
                const now = Date.now();
                state.synthesisLatency = Math.max(0, now - finishASRTs);
                waitingFirstUpdateResp = false;
            }
            updateLastMessage({ role:"Ai", content: json.data.text });
            break;
        }
        case 'client_tts_playback_finished':
            state.streamState = 'idle';
            break;
    }
}
//---------------上面是声明和定义，下面是执行--------------------------
initWebSocket();
state.loading = false;






</script>
