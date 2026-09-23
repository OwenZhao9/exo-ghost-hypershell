"""The picture-to-cue boundary must fail closed before voice or motor output."""
from __future__ import annotations

import pytest
from jev_decide import Choice

from product_features.guide.decision import decide_visual_cue

VISION = {
    'direction': 'right', 'confidence': .92,
    'description': '左侧有箱子，右侧地面可见。',
    'annotations': [{'label': '箱子', 'box': [.1, .2, .3, .4]}],
}


class FakeDecider:
    def __init__(self, choice):
        self.answer = choice
        self.calls = []

    def choice(self, state, question, options, *, rules):
        self.calls.append((state, question, options, rules(state)))
        return self.answer


def answer(value='right', *, confidence=.9, probability=.92,
           backend='jev', degraded=False):
    other = (1 - probability) / 2
    return Choice(value=value, probs={key: probability if key == value else other
                                    for key in ('unknown', 'left', 'right')},
                  confidence=confidence, latency_ms=240,
                  backend=backend, degraded=degraded)


def test_jev_accepts_only_agreeing_confident_photo_result():
    decider = FakeDecider(answer())
    result = decide_visual_cue(VISION, decider=decider)
    assert result['direction'] == 'right' and result['jev_status'] == 'accepted'
    state, question, options, fallback = decider.calls[0]
    assert state['visual_direction'] == 'right'
    assert state['objects'] == ['箱子']
    assert options == ('unknown', 'left', 'right') and fallback == 'unknown'
    assert '导盲' in question


@pytest.mark.parametrize('choice,status', [
    (answer('left'), 'disagreed'),
    (answer(confidence=.5), 'low_confidence'),
    (answer(probability=.6), 'low_confidence'),
    (answer(backend='rules', degraded=True), 'unavailable'),
    (answer(degraded=True), 'unavailable'),
])
def test_jev_disagreement_uncertainty_or_fallback_never_becomes_direction(choice, status):
    result = decide_visual_cue(VISION, decider=FakeDecider(choice))
    assert result['direction'] == 'unknown'
    assert result['jev_status'] == status


def test_uncertain_vision_is_not_sent_to_jev():
    decider = FakeDecider(answer())
    result = decide_visual_cue({**VISION, 'confidence': .8}, decider=decider)
    assert result['direction'] == 'unknown'
    assert result['jev_status'] == 'vision_uncertain'
    assert decider.calls == []


def test_missing_typesafe_key_does_not_use_rules_as_jev(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    result = decide_visual_cue(VISION)
    assert result['direction'] == 'unknown'
    assert result['jev_status'] == 'unavailable'
    assert result['jev_backend'] == 'rules'
