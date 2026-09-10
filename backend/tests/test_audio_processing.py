import json
import subprocess

import pytest

import app.services.audio_processing as audio_processing


def _completed_process(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_probe_audio_duration_uses_container_duration(monkeypatch) -> None:
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return _completed_process({"format": {"duration": "60.125"}})

    monkeypatch.setattr(audio_processing, "_require_tool", lambda *_: None)
    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)

    duration = audio_processing.probe_audio_duration(audio_processing.Path("answer.m4a"))

    assert duration == 60.125
    assert len(calls) == 1


def test_probe_audio_duration_falls_back_to_webm_packet_timestamps(
    monkeypatch,
) -> None:
    results = iter(
        [
            _completed_process({"format": {}}),
            _completed_process(
                {
                    "packets": [
                        {
                            "pts_time": "-0.007",
                            "dts_time": "-0.007",
                            "duration_time": "0.020",
                        },
                        {
                            "pts_time": "5.994",
                            "dts_time": "5.994",
                            "duration_time": "0.007",
                        },
                    ]
                }
            ),
        ]
    )
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return next(results)

    monkeypatch.setattr(audio_processing, "_require_tool", lambda *_: None)
    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)

    duration = audio_processing.probe_audio_duration(audio_processing.Path("answer.webm"))

    assert duration == pytest.approx(6.008)
    assert len(calls) == 2
    assert "packet=pts_time,dts_time,duration_time" in calls[1]
