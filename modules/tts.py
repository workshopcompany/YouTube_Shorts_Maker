"""
YouTube 자동화 - TTS 음성 생성 모듈
Groq API를 사용하여 텍스트를 음성으로 변환
"""

import os
import subprocess
from pathlib import Path
from config import (GROQ_API_KEY, OUTPUT_DIR, TTS_LANGUAGE, TTS_SPEED, TTS_VOICE,
                    FFMPEG_OVERRIDE_DIR, SCENE_GAP_MS, TRIM_TTS_SILENCE, TTS_TAIL_SILENCE_MS)

# FFmpeg 경로 설정 (Windows)
import platform
if platform.system() == "Windows":
    # config 지정 경로 우선 (예: FFmpeg 8.x — NVENC 호환)
    if FFMPEG_OVERRIDE_DIR and os.path.exists(FFMPEG_OVERRIDE_DIR):
        os.environ["PATH"] = FFMPEG_OVERRIDE_DIR + os.pathsep + os.environ["PATH"]
    # winget으로 설치된 FFmpeg 경로 (폴백)
    ffmpeg_path = ""  # hardcoded user path removed: ffmpeg is resolved via FFMPEG_DIR / PATH
    if os.path.exists(ffmpeg_path):
        os.environ["PATH"] += os.pathsep + ffmpeg_path


class TTSEngine:
    # Edge TTS 음성 (무료, MS 신경망 — config TTS_VOICE로 선택)
    _EDGE_VOICES = {
        "ko": {"female": "ko-KR-SunHiNeural", "male": "ko-KR-InJoonNeural"},
        "en": {"female": "en-US-JennyNeural", "male": "en-US-GuyNeural"},
    }

    def __init__(self):
        self.output_dir = Path(OUTPUT_DIR) / "audio"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = GROQ_API_KEY

    # ---------- 3) 음성 생성 엔트리: Edge TTS → gTTS 폴백 ----------
    def generate_speech_groq(self, text: str, output_file: str) -> str:
        """
        장면 대사 → 음성. 우선 Edge TTS(무료, 고품질), 실패 시 gTTS 폴백.
        (메서드명은 기존 호환 유지 — 과거 Groq/gTTS 진입점)
        """
        # 1순위: Edge TTS (ko-KR 신경망, VRAM 0, 무료)
        try:
            result = self.generate_speech_edge(text, output_file)
            if result:
                return result
        except Exception as e:
            print(f"⚠️ Edge TTS 실패({e}) → gTTS 폴백")

        # 2순위: gTTS 폴백 (기존 방식)
        try:
            from gtts import gTTS

            tts = gTTS(text=text, lang=TTS_LANGUAGE, slow=False)
            tts.save(output_file)

            return output_file

        except ImportError:
            print("⚠️ gTTS가 설치되지 않았습니다. 설치 중...")
            os.system("pip install gtts")

            from gtts import gTTS
            tts = gTTS(text=text, lang=TTS_LANGUAGE, slow=False)
            tts.save(output_file)

            return output_file

        except Exception as e:
            print(f"❌ TTS 생성 실패: {e}")
            return None

    def generate_speech_edge(self, text: str, output_file: str, voice: str = None) -> str:
        """
        Edge TTS (Microsoft 신경망, 무료·비공식 API) → mp3 저장
        voice 미지정 시 config(TTS_LANGUAGE, TTS_VOICE)에서 자동 선택.
        """
        import asyncio

        import edge_tts

        if voice is None:
            lang = "ko" if TTS_LANGUAGE.lower().startswith("ko") else "en"
            gender = "male" if str(TTS_VOICE).lower() == "male" else "female"
            voice = self._EDGE_VOICES[lang][gender]

        # TTS_SPEED(1.0=보통) → rate 퍼센트 (+10%/-10%)
        rate = f"{int(round((float(TTS_SPEED) - 1.0) * 100)):+d}%"

        async def _gen():
            comm = edge_tts.Communicate(text, voice, rate=rate)
            await comm.save(output_file)

        try:
            asyncio.run(_gen())
        except RuntimeError:
            # 이미 실행 중인 이벤트 루프가 있는 환경 대비
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_gen())
            finally:
                loop.close()

        if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
            return output_file
        raise RuntimeError("출력 파일이 비정상(0바이트 또는 과소)")

    
    def generate_speech_elevenlabs(self, text: str, output_file: str, api_key: str) -> str:
        """ElevenLabs TTS (고품질, API 필요)"""
        try:
            url = "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM"
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": api_key
            }
            
            data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.5
                }
            }
            
            response = requests.post(url, json=data, headers=headers)
            
            if response.status_code == 200:
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                return output_file
            else:
                print(f"❌ ElevenLabs API 오류: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ ElevenLabs TTS 실패: {e}")
            return None
    
    def trim_silence(self, audio_path: str, threshold_db: int = -60,
                     min_silence: float = 0.05) -> str:
        """TTS가 만드는 앞/뒤 무음을 잘라 문장 전환 간극을 줄임 (성공 시 새 경로, 실패 시 원본)
        - 앞 무음: silenceremove
        - 뒤 무음: areverse → silenceremove → areverse (역방향 트릭)
        ※ 임계값 -60dB/0.05초로 보수화 (2026-09-23): -45dB/0.15초였을 때 마지막 음절의
          감쇠(-45~-60dB 구간)를 무음으로 오인해 약 0.16초짜리 말끝이 잘리는 문제가 확인됨
        - 문장 내부의 짧은 틈은 보존 (min_silence 이상의 무음만 제거)
        - 마지막에 꼬리 무음 TTS_TAIL_SILENCE_MS(기본 0.3초)를 다시 붙여 호흡 확보
        """
        if not TRIM_TTS_SILENCE or not audio_path or not os.path.exists(audio_path):
            return audio_path
        p = Path(audio_path)
        out = str(p.with_name(f"{p.stem}_trim{p.suffix}"))
        tail = max(0.0, float(TTS_TAIL_SILENCE_MS or 0) / 1000.0)
        af = (
            f"silenceremove=start_periods=1:start_duration=0:start_threshold={threshold_db}dB,"
            f"areverse,"
            f"silenceremove=start_periods=1:start_duration={min_silence}:"
            f"start_threshold={threshold_db}dB,"
            f"areverse,"
            f"apad=pad_dur={tail}"
        )
        try:
            cmd = ["ffmpeg", "-y", "-i", audio_path, "-af", af,
                   "-c:a", "libmp3lame", "-q:a", "2", out]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                return out
            print(f"   무음 트리밍 건너뜀 (원본 사용): {(r.stderr or '')[-160:]}")
        except Exception as e:
            print(f"   무음 트리 건너뜀 (원본 사용): {e}")
        return audio_path

    def generate_scene_audio(self, script: list) -> list:
        """
        각 장면의 대사를 음성으로 변환
        반환: ["오디오경로1", "오디오경로2", ...]
        """
        audio_paths = []
        
        for i, scene in enumerate(script, 1):
            content = scene.get("content", "")
            # content가 비어있으면 visual 또는 기본 메시지 사용
            if not content:
                content = scene.get("visual", "")
            if not content:
                content = f"장면 {i}"
            
            print(f"🎤 음성 생성 중... [{i}/{len(script)}]")
            
            output_file = str(self.output_dir / f"scene_{i:02d}.mp3")
            result = self.generate_speech_groq(content, output_file)

            # 앞/뒤 무음 제거 → 문장 전환 간극 최소화 (파일 교체로 측정·병합 모두 일관)
            if result and TRIM_TTS_SILENCE:
                trimmed = self.trim_silence(result)
                if trimmed != result and os.path.exists(trimmed):
                    try:
                        os.replace(trimmed, result)
                    except Exception:
                        result = trimmed
            
            if result:
                audio_paths.append(result)
                print(f"   ✅ 완료: {result}")
            else:
                print(f"   ⚠️ 실패: 장면 {i}")
        
        return audio_paths
    
    def merge_audio_files(self, audio_paths: list, output_file: str = "full_narration.mp3") -> str:
        """여러 오디오 파일을 하나로 합치기
        - 장면 사이 간극 = config SCENE_GAP_MS (기본 0.2초 / 기존 0.5초)
        - 마지막 장면 뒤에는 무음을 넣지 않음 (영상 끝 늘어짐 방지)"""
        gap_ms = int(SCENE_GAP_MS) if SCENE_GAP_MS else 0
        valid = [p for p in audio_paths if os.path.exists(p)]
        if gap_ms:
            print(f"   ⏱️ 장면 간 간극 {gap_ms}ms (장면 {len(valid)}개 · 마지막 뒤 무음 없음)")
        try:
            from pydub import AudioSegment
            
            combined = AudioSegment.empty()
            
            for audio_path in audio_paths:
                if os.path.exists(audio_path):
                    sound = AudioSegment.from_mp3(audio_path)
                    combined += sound
                    # 장면 사이 간극만 삽입 (마지막 장면 뒤는 무음 없음)
                    if gap_ms > 0 and audio_path != valid[-1]:
                        combined += AudioSegment.silent(duration=gap_ms)
            
            output_path = str(self.output_dir / output_file)
            combined.export(output_path, format="mp3")
            
            print(f"✅ 전체 음성 합치기 완료: {output_path}")
            return output_path
            
        except ImportError:
            print("⚠️ pydub이 설치되지 않았습니다. 설치 중...")
            os.system("pip install pydub")
            
            from pydub import AudioSegment
            
            combined = AudioSegment.empty()
            for audio_path in audio_paths:
                if os.path.exists(audio_path):
                    sound = AudioSegment.from_mp3(audio_path)
                    combined += sound
                    if gap_ms > 0 and audio_path != valid[-1]:
                        combined += AudioSegment.silent(duration=gap_ms)
            
            output_path = str(self.output_dir / output_file)
            combined.export(output_path, format="mp3")
            
            return output_path
        
        except Exception as e:
            print(f"❌ 오디오 합치기 실패: {e}")
            return None


# 테스트용
if __name__ == "__main__":
    engine = TTSEngine()
    
    test_script = [
        {"content": "안녕하세요! 오늘은 파이썬 자동화에 대해 알아볼게요."},
        {"content": "자동화를 하면 3시간 걸리던 작업이 10분이면 끝납니다."},
        {"content": "지금 바로 시작해볼까요?"},
    ]
    
    audio_files = engine.generate_scene_audio(test_script)
    print(f"\n생성된 오디오: {audio_files}")
