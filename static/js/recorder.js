// ═══════════════════════════════════════════════
// KLABAUTERMANN — Media Recorder
// Audio/Video capture via MediaRecorder API
// ═══════════════════════════════════════════════

let mediaRecorder = null;
let recordedChunks = [];
let recordingType = null; // 'audio' | 'video'
let timerInterval = null;
let startTime = 0;

function toggleAudioRecording() {
    if (mediaRecorder && recordingType === 'audio') {
        stopRecording();
    } else {
        startRecording('audio');
    }
}

function toggleVideoRecording() {
    if (mediaRecorder && recordingType === 'video') {
        stopRecording();
    } else {
        startRecording('video');
    }
}

function clearPreview() {
    const preview = document.getElementById('media-preview');
    while (preview.firstChild) {
        preview.removeChild(preview.firstChild);
    }
    preview.hidden = true;
}

async function startRecording(type) {
    // Stop any existing recording
    if (mediaRecorder) {
        stopRecording();
        return;
    }

    try {
        const constraints = type === 'video'
            ? { audio: true, video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } } }
            : { audio: true };

        const stream = await navigator.mediaDevices.getUserMedia(constraints);

        recordedChunks = [];
        recordingType = type;

        const mimeType = type === 'video'
            ? (MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus') ? 'video/webm;codecs=vp9,opus' : 'video/webm')
            : (MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm');

        mediaRecorder = new MediaRecorder(stream, { mimeType });

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) {
                recordedChunks.push(e.data);
            }
        };

        mediaRecorder.onstop = () => {
            const blob = new Blob(recordedChunks, { type: mimeType });
            stream.getTracks().forEach(t => t.stop());
            onRecordingComplete(blob, type);
        };

        mediaRecorder.start(100); // collect in 100ms chunks

        // UI updates
        const btn = type === 'audio' ? document.getElementById('btn-audio') : document.getElementById('btn-video');
        btn.classList.add('recording');

        const status = document.getElementById('recording-status');
        status.hidden = false;
        startTime = Date.now();
        timerInterval = setInterval(updateTimer, 1000);

        // Show video preview if recording video
        if (type === 'video') {
            const preview = document.getElementById('media-preview');
            clearPreview();
            preview.hidden = false;
            const videoEl = document.createElement('video');
            videoEl.id = 'video-preview';
            videoEl.autoplay = true;
            videoEl.muted = true;
            videoEl.playsInline = true;
            videoEl.srcObject = stream;
            preview.appendChild(videoEl);
        }

    } catch (err) {
        console.error('Recording failed:', err);
        if (err.name === 'NotAllowedError') {
            alert('Permission denied. Please allow microphone' + (type === 'video' ? '/camera' : '') + ' access.');
        }
    }
}

function stopRecording() {
    if (!mediaRecorder) return;

    mediaRecorder.stop();

    // Reset UI
    const btn = recordingType === 'audio' ? document.getElementById('btn-audio') : document.getElementById('btn-video');
    btn.classList.remove('recording');

    const status = document.getElementById('recording-status');
    status.hidden = true;
    clearInterval(timerInterval);

    mediaRecorder = null;
}

function updateTimer() {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    document.getElementById('recording-timer').textContent =
        `${mins}:${secs.toString().padStart(2, '0')}`;
}

function onRecordingComplete(blob, type) {
    const preview = document.getElementById('media-preview');
    clearPreview();
    preview.hidden = false;

    const url = URL.createObjectURL(blob);

    if (type === 'video') {
        const videoEl = document.createElement('video');
        videoEl.controls = true;
        videoEl.src = url;
        preview.appendChild(videoEl);
    } else {
        const audioEl = document.createElement('audio');
        audioEl.controls = true;
        audioEl.src = url;
        preview.appendChild(audioEl);
    }

    // Set the blob as the file for form submission
    const filename = 'recording.webm';
    const file = new File([blob], filename, { type: blob.type });

    // Use DataTransfer to set the file input
    const dt = new DataTransfer();
    dt.items.add(file);
    document.getElementById('media-file').files = dt.files;
}

// ═══════════════════════════════════════════════
// CAMERA (mobile capture)
// ═══════════════════════════════════════════════

function openCameraMenu() {
    // On mobile, directly open photo capture
    // On desktop, fall back to file picker
    document.getElementById('camera-photo').click();
}

// Camera photo capture → attach to main media input
document.getElementById('camera-photo').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        attachImageFile(file);
    }
    e.target.value = '';
});

// Camera video capture → attach to main media input
document.getElementById('camera-video').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        attachVideoFile(file);
    }
    e.target.value = '';
});

function attachVideoFile(file) {
    const preview = document.getElementById('media-preview');
    clearPreview();
    preview.hidden = false;

    const videoEl = document.createElement('video');
    videoEl.controls = true;
    videoEl.src = URL.createObjectURL(file);
    preview.appendChild(videoEl);

    const dt = new DataTransfer();
    dt.items.add(file);
    document.getElementById('media-file').files = dt.files;
}

// ═══════════════════════════════════════════════
// IMAGE PASTE & FILE UPLOAD HANDLING
// ═══════════════════════════════════════════════

// Handle paste events on the textarea (Ctrl+V / Cmd+V with images)
document.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    for (const item of items) {
        if (item.type.startsWith('image/')) {
            e.preventDefault();
            const file = item.getAsFile();
            if (file) attachImageFile(file);
            return;
        }
    }
});

// Handle file input change (image button click)
document.getElementById('media-file').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file && file.type.startsWith('image/')) {
        attachImageFile(file);
    }
});

function attachImageFile(file) {
    // Show preview
    const preview = document.getElementById('media-preview');
    clearPreview();
    preview.hidden = false;

    const img = document.createElement('img');
    img.src = URL.createObjectURL(file);
    preview.appendChild(img);

    // Set the file on the file input
    const dt = new DataTransfer();
    dt.items.add(file);
    document.getElementById('media-file').files = dt.files;
}

// Reset preview after form submit
document.addEventListener('htmx:afterRequest', (e) => {
    if (e.detail.elt && e.detail.elt.id === 'entry-form') {
        clearPreview();
        document.getElementById('media-file').value = '';
    }
});
