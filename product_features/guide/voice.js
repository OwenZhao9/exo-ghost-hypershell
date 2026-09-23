const cueUrls = Object.freeze({
  left: '/features/guide/audio/left.wav',
  right: '/features/guide/audio/right.wav',
  unknown: '/features/guide/audio/unknown.wav',
  stop: '/features/guide/audio/stop.wav',
});

export function createVoicePlayer({AudioCtor = Audio, onError = () => {}, onPlayed = () => {}} = {}) {
  let active = null;
  let pending = [];

  function playNext() {
    if (active || !pending.length) return;
    const cue = pending.shift();
    const clip = new AudioCtor(cueUrls[cue]);
    active = clip;
    clip.preload = 'auto';
    let finished = false;
    const finish = (failed = false) => {
      if (finished || active !== clip) return;
      finished = true;
      active = null;
      if (failed) {
        pending = [];
        onError('声音未能播放，请点击“开启语音并试听”后重试。');
      } else {
        onPlayed(cue);
        playNext();
      }
    };
    clip.addEventListener('ended', () => finish(), {once: true});
    clip.addEventListener('error', () => finish(true), {once: true});
    try {
      Promise.resolve(clip.play()).catch(() => finish(true));
    } catch {
      finish(true);
    }
  }

  function enqueue(cue) {
    if (!(cue in cueUrls)) throw new Error('未知语音提示');
    pending.push(cue);
    playNext();
  }

  function interrupt(cue = null) {
    pending = [];
    if (active) {
      active.pause();
      active = null;
    }
    if (cue) enqueue(cue);
  }

  return {enqueue, interrupt};
}
