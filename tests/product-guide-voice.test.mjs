import test from 'node:test';
import assert from 'node:assert/strict';
import {createVoicePlayer} from '../product_features/guide/voice.js';

test('voice cues play in order and stop interrupts the current cue', () => {
  const clips = [];
  const played = [];
  class FakeAudio {
    constructor(url) { this.url = url; this.listeners = {}; clips.push(this); }
    addEventListener(event, callback) { this.listeners[event] = callback; }
    play() { this.played = true; return Promise.resolve(); }
    pause() { this.paused = true; }
    finish() { this.listeners.ended(); }
  }
  const voice = createVoicePlayer({AudioCtor: FakeAudio, onPlayed: cue => played.push(cue)});
  voice.enqueue('left');
  voice.enqueue('right');
  assert.equal(clips.length, 1);
  assert.match(clips[0].url, /left\.wav$/);
  clips[0].finish();
  assert.deepEqual(played, ['left']);
  assert.equal(clips.length, 2);
  assert.match(clips[1].url, /right\.wav$/);
  voice.interrupt('stop');
  assert.equal(clips[1].paused, true);
  assert.match(clips[2].url, /stop\.wav$/);
  clips[1].finish();
  assert.equal(clips.length, 3);
  assert.deepEqual(played, ['left']);
  clips[2].finish();
  assert.deepEqual(played, ['left', 'stop']);
});

test('audio failure is visible and clears pending cues', async () => {
  const errors = [];
  class BlockedAudio {
    constructor(url) { this.url = url; }
    addEventListener() {}
    play() { return Promise.reject(new Error('blocked')); }
    pause() {}
  }
  const voice = createVoicePlayer({AudioCtor: BlockedAudio, onError: error => errors.push(error)});
  voice.enqueue('unknown');
  voice.enqueue('left');
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(errors.length, 1);
  assert.match(errors[0], /未能播放/);
});
