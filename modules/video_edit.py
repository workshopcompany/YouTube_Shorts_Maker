"""
YouTube 자동화 - 영상 편집 모듈
FFmpeg를 사용하여 이미지와 음성을 합성
"""

import os
import subprocess
from pathlib import Path
from config import (OUTPUT_DIR, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS, VIDEO_DURATION,
                    VIDEO_PLAYBACK_SPEED, FFMPEG_OVERRIDE_DIR, VIDEO_END_PAD_MS)

# FFmpeg 우선 경로 적용 (예: FFmpeg 8.x — 드라이버 610 미만에서도 NVENC 사용 가능)
if FFMPEG_OVERRIDE_DIR and os.path.exists(FFMPEG_OVERRIDE_DIR):
    os.environ["PATH"] = FFMPEG_OVERRIDE_DIR + os.pathsep + os.environ["PATH"]


class VideoEditor:
    def __init__(self):
        self.output_dir = Path(OUTPUT_DIR)
        self.images_dir = self.output_dir / "images"
        self.audio_dir = self.output_dir / "audio"
        self.videos_dir = self.output_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def check_ffmpeg(self) -> bool:
        """FFmpeg 설치 여부 확인"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace'
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def probe_duration(self, path) -> float:
        """ffprobe로 미디어 길이(초) 측정. 실패 시 0.0"""
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    def measure_scene_durations(self, audio_paths: list, n_images: int,
                                audio_path=None) -> list:
        """장면별 표시 시간 = 장면 음성 실제 길이 (음성 없는 장면은 평균으로 보정)
        - 각 장면 음성은 앞/뒤 무음이 트리밍된 상태 (tts.trim_silence)
        - 병합 음성은 장면 사이 간극(config SCENE_GAP_MS)을 포함 → 앞 장면에 배분
        - audio_path(병합 음성)가 장면 합계보다 길면 마지막 장면을 연장해 끝까지 유지
        - 측정 불가 시 None 반환 → 호출부가 균등 분할로 폴백"""
        if not audio_paths:
            return None
        durs = [0.0] * n_images
        for i in range(min(len(audio_paths), n_images)):
            durs[i] = self.probe_duration(audio_paths[i])
        measured = [d for d in durs if d > 0]
        if not measured:
            return None
        default = sum(measured) / len(measured)
        durs = [d if d > 0 else default for d in durs]
        if audio_path and os.path.exists(audio_path):
            total_audio = self.probe_duration(audio_path)
            diff = total_audio - sum(durs)
            n = len(durs)
            if diff > 0.05 and n > 0:
                # 병합 음성은 장면 사이 간극(config SCENE_GAP_MS, 기본 0.15초)을 포함하므로
                # 그 시간을 앞 장면들에 배분 → 각 장면 시작이 내레이션 시작과 정확히 정렬
                if n > 1:
                    per = diff / (n - 1)
                    if per <= 1.0:
                        durs = [d + per for d in durs[:-1]] + [durs[-1]]
                        print(f"   ⏱️ 장면 간 간극 반영: 앞 {n - 1}개 장면 +{per:.2f}초 (내레이션 정렬)")
                    else:
                        per = diff / n
                        durs = [d + per for d in durs]
                        print(f"   ⏱️ 장면 간 무음 분배: 장면당 +{per:.2f}초")
                else:
                    durs = [durs[0] + diff]
            elif diff < -0.5:
                # 장면 합계가 음성보다 긴 드문 경우 → 비율 축소
                scale = total_audio / sum(durs)
                durs = [d * scale for d in durs]
                print(f"   ⏱️ 길이 축소 적용 (x{scale:.3f})")
        return [round(d, 3) for d in durs]

    # ---------- 자막 (ASS) 생성 ----------
    def build_subtitles_ass(self, scene_texts: list, durations: list, out_path: str) -> str:
        """장면별 텍스트를 타이밍이 맞는 .ass 자막 파일로 생성. 실패 시 None.
        - 표시 구간: 각 장면 시작부터 (길이 - 0.3초)까지, 최소 1.0초 보장
        - 긴 문장은 2줄로 분할 (한 줄 최대 24자)"""
        try:
            def ts(t: float) -> str:
                h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
                return f"{h}:{m:02d}:{s:05.2f}"

            def wrap(text: str, width: int = 24) -> str:
                text = text.strip()
                if len(text) <= width:
                    return text
                mid = text.rfind(" ", 0, width + 6)
                mid = mid if mid > width // 2 else width
                return text[:mid].rstrip() + r"\N" + text[mid:].lstrip()

            lines = [
                "[Script Info]", "ScriptType: v4.00+",
                f"PlayResX: {VIDEO_WIDTH}", f"PlayResY: {VIDEO_HEIGHT}",
                "[V4+ Styles]",
                "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
                "Style: Shorts,맑은 고딕,60,&H00FFFFFF,&H00000000,&H7F000000,1,1,3,1,2,40,40,90,1",
                "[Events]",
                "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
            ]
            t = 0.0
            for text, dur in zip(scene_texts, durations):
                if text and str(text).strip():
                    start, end = t, t + max(dur - 0.3, 1.0)
                    body = str(text).strip().replace("\n", " ")
                    lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},Shorts,,0,0,0,,{wrap(body)}")
                t += float(dur)
            with open(out_path, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines) + "\n")
            return out_path
        except Exception as e:
            print(f"⚠️ 자막 파일 생성 실패 (자막 없이 진행): {e}")
            return None

    def burn_subtitles(self, video_path: str, ass_path: str) -> str:
        """완성 영상 위에 ASS 자막을 굽기(오버레이) — MoviePy 폴백 경로용"""
        tmp = video_path.replace(".mp4", "_sub.mp4")
        ass_ff = str(ass_path).replace("\\", "/").replace(":", "\\:")
        cmd = ["ffmpeg", "-y", "-i", video_path,
               "-vf", f"ass='{ass_ff}'",
               "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-c:a", "copy", tmp]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0 and os.path.exists(tmp):
                os.replace(tmp, video_path)
                return video_path
            print(f"⚠️ 자막 굽기 실패: {r.stderr[-300:]}")
        except Exception as e:
            print(f"⚠️ 자막 굽기 실패: {e}")
        return video_path

    def _normalize_rgb_images(self, image_paths: list) -> list:
        """이미지 픽셀 포맷을 RGB로 통일한 경로 목록 반환.

        - FFmpeg concat demuxer는 입력 픽셀 포맷(rgb24/rgba)이 중간에 바뀌면
          필터 그래프를 재구성하고, 재구성 시점 '이전' 프레임을 전부 누락시킴
          → 장면 1~4가 검은 화면으로 나오던 원인
        - RGB 이미지는 원본 경로 그대로, RGBA/기타 포맷은 output/images/_rgb/ 에
          RGB 복본(투명부분은 검정 = 영상 pad 배경과 동일) 생성 후 그 경로 사용
        """
        try:
            from PIL import Image
        except ImportError:
            return image_paths
        out, norm_dir, changed = [], self.images_dir / "_rgb", False
        for p in image_paths:
            try:
                with Image.open(p) as im:
                    if im.mode == "RGB":
                        out.append(str(p))
                        continue
                    norm_dir.mkdir(parents=True, exist_ok=True)
                    dst = norm_dir / Path(p).name
                    if dst.exists() and os.path.getmtime(dst) >= os.path.getmtime(p):
                        out.append(str(dst))
                        continue
                    if im.mode in ("RGBA", "LA", "PA"):
                        rgba = im.convert("RGBA")
                        conv = Image.new("RGB", rgba.size, (0, 0, 0))
                        conv.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        conv = im.convert("RGB")
                    conv.save(dst, "PNG")
                    changed = True
                    out.append(str(dst))
            except Exception as e:
                print(f"⚠️ 픽셀 포맷 통일 실패 (원본 사용): {p}: {e}")
                out.append(str(p))
        if changed:
            print(f"🎨 픽셀 포맷 통일: RGBA/기타 → RGB 복본 생성 ({norm_dir})")
        return out

    def speedup_audio(self, audio_path: str, speed: float) -> str:
        """내레이션 오디오를 atempo로 배속 처리 (피치 유지). 성공 시 새 파일 경로, 실패 시 원본 반환"""
        if not audio_path or not os.path.exists(audio_path):
            return audio_path
        p = Path(audio_path)
        out = str(p.with_name(f"{p.stem}_x{speed}{p.suffix}"))
        try:
            cmd = ["ffmpeg", "-y", "-i", audio_path,
                   "-filter:a", f"atempo={speed}",
                   "-c:a", "libmp3lame", "-q:a", "2", out]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
            if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                return out
            print(f"⚠️ 오디오 배속 처리 실패: {r.stderr[-200:] if r.stderr else '알 수 없음'}")
        except Exception as e:
            print(f"⚠️ 오디오 배속 처리 실패: {e}")
        return audio_path

    def _pad_audio_end(self, audio_path: str, pad_sec: float) -> str:
        """오디오 끝에 여유 무음을 붙임 (마지막 말 잘림 방지). 성공 시 새 경로, 실패 시 원본.

        -shortest 가 오디오/비디오 중 짧은 쪽에서 끊을 때 잘리는 것이
        '실제 말'이 아니라 '여유 무음'이 되도록 미리 덧대는 용도.
        """
        if not audio_path or not os.path.exists(audio_path) or pad_sec <= 0:
            return audio_path
        p = Path(audio_path)
        out = str(p.with_name(f"{p.stem}_pad{p.suffix}"))
        try:
            cmd = ["ffmpeg", "-y", "-i", audio_path,
                   "-af", f"apad=pad_dur={pad_sec:.3f}",
                   "-c:a", "libmp3lame", "-q:a", "2", out]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                return out
            print(f"⚠️ 끝 여유 무음 추가 실패 (원본 사용): {(r.stderr or '')[-160:]}")
        except Exception as e:
            print(f"⚠️ 끝 여유 무음 추가 실패 (원본 사용): {e}")
        return audio_path

    def _apply_playback_speed(self, durations: list, audio_path: str, speed: float) -> tuple:
        """배속 적용: 장면 표시시간 단축 + 내레이션 배속. 반환 (durations, audio_path, 적용여부)"""
        if abs(float(speed) - 1.0) <= 0.001:
            return durations, audio_path, False
        if audio_path and os.path.exists(audio_path):
            sped = self.speedup_audio(audio_path, speed)
            if sped == audio_path:
                print("⚠️ 오디오 배속 실패 → 영상도 원본 속도(1.0x)로 생성 (음성 싱크 보장)")
                return durations, audio_path, False
            audio_path = sped
        durations = [round(d / speed, 3) for d in durations]
        total = sum(durations)
        print(f"⚡ 재생 배속 {speed}x 적용 (내레이션 atempo + 장면 시간 단축, 피치 유지)")
        print(f"   ⏱️ 배속 후 총 길이: {total:.1f}초")
        return durations, audio_path, True

    def _encoder_args(self) -> tuple:
        """NVENC(1080Ti 하드웨어 가속) 우선, 실패 시 CPU libx264로 폴백.
        반환: (인코더 인자 리스트, 인코더 이름)"""
        probe = ["ffmpeg", "-v", "error", "-hide_banner",
                 "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
                 "-c:v", "h264_nvenc", "-f", "null", "-"]
        try:
            r = subprocess.run(probe, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0:
                return (["-c:v", "h264_nvenc", "-preset", "p4",
                         "-cq", "23", "-pix_fmt", "yuv420p"], "h264_nvenc(GPU)")
        except Exception:
            pass
        return (["-c:v", "libx264", "-preset", "fast",
                 "-crf", "23", "-pix_fmt", "yuv420p"], "libx264(CPU)")

    def create_video_from_images(self, image_paths: list, audio_path: str = None,
                                 output_file: str = "final_video.mp4",
                                 scene_durations: list = None,
                                 scene_texts: list = None,
                                 playback_speed: float = None) -> str:
        """
        이미지들을 슬라이드쇼 영상으로 변환
        """
        if not self.check_ffmpeg():
            self.install_ffmpeg()
            return None

        if not image_paths:
            print("❌ 사용할 이미지가 없습니다.")
            return None

        # 안전장치: 동일 이미지 경로가 중복되면 정상 슬라이드쇼가 아님
        # (과거 버그: 모든 장면이 scene_01.png에 덮여쓰여져 한 장으로 고정된 영상이 만들어짐)
        if len(set(image_paths)) != len(image_paths):
            from collections import Counter
            counts = Counter(image_paths)
            print("❌ 동일한 이미지 경로가 중복되어 영상 생성을 중단합니다:")
            for p, c in counts.items():
                if c > 1:
                    print(f"   - {p} (x{c})")
            print("   👉 이미지가 한 파일에 덮여쓰여진 경우일 수 있으니 이미지를 다시 생성하세요.")
            return None

        output_path = str(self.videos_dir / output_file)

        # 이미지 픽셀 포맷 통일 — concat 도중 rgb24↔rgba가 섞이면 FFmpeg가 필터
        # 그래프를 재구성하면서 마지막 포맷 변경 지점 '이전'의 프레임을 전부 버림
        # (= 앞 장면들이 검게 나오는 2026-09-23 버그). RGB는 원본, 그 외는 RGB 복본 사용.
        image_paths = self._normalize_rgb_images(image_paths)

        # 이미지 목록 파일 생성 (장면별 음성 길이 동기화 지원)
        list_file = str(self.output_dir / "image_list.txt")
        base_dir = Path(list_file).parent  # image_list.txt가 있는 폴더 기준

        if scene_durations and len(scene_durations) == len(image_paths):
            durations = [float(d) for d in scene_durations]
            print("⏱️ 장면-음성 동기화: 장면별 음성 길이 적용")
        else:
            durations = [VIDEO_DURATION / len(image_paths)] * len(image_paths)
            print("⏱️ 장면-음성 동기화: 음성 정보 없음 → 균등 분할")

        # 재생 배속 (config VIDEO_PLAYBACK_SPEED, 예: 1.2 → 영상+내레이션+자막 함께 1.2배속)
        speed = float(playback_speed if playback_speed is not None else (VIDEO_PLAYBACK_SPEED or 1.0))
        durations, audio_path, _ = self._apply_playback_speed(durations, audio_path, speed)
        # 끝 여유 무음: -shortest 가 잘라도 마지막 말은 보존 (잘리는 건 여유 무음)
        end_pad = max(0.0, float(VIDEO_END_PAD_MS or 0) / 1000.0)
        if audio_path and os.path.exists(audio_path) and end_pad > 0:
            padded = self._pad_audio_end(audio_path, end_pad)
            if padded != audio_path:
                audio_path = padded
                durations = [d + end_pad if i == len(durations) - 1 else d
                             for i, d in enumerate(durations)]

        with open(list_file, 'w', encoding='utf-8') as f:
            for img_path, dur in zip(image_paths, durations):
                # image_list.txt 위치 기준 상대경로 계산
                rel_path = os.path.relpath(img_path, start=base_dir)
                rel_path = rel_path.replace('\\', '/').replace("'", "'\\''")
                f.write(f"file '{rel_path}'\n")
                f.write(f"duration {dur}\n")

            last_rel = os.path.relpath(image_paths[-1], start=base_dir).replace('\\', '/').replace("'", "'\\''")
            f.write(f"file '{last_rel}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
        ]

        if audio_path and os.path.exists(audio_path):
            cmd.extend(["-i", audio_path])

        # 하단 자막(ASS) 비활성화 — 말풍선 이미지에 대사가 이미 포함되어 중복됨.
        # 다시 켜려면 아래 주석 해제 (subtitles.ass 생성 + ass 필터 삽입).
        subs_filter = ""
        # if scene_texts:
        #     ass_path = str(self.output_dir / "subtitles.ass")
        #     if self.build_subtitles_ass(scene_texts, durations, ass_path):
        #         ass_ff = ass_path.replace("\\", "/").replace(":", "\\:")
        #         subs_filter = f",ass='{ass_ff}'"
        #         print(f"💬 자막 {len(scene_texts)}개 생성 완료 → 영상에 삽입")

        # 인코더: NVENC(GPU) 우선, 실패 시 libx264(CPU)
        enc_args, enc_name = self._encoder_args()
        print(f"🎬 인코더: {enc_name}")

        cmd.extend([
            "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={VIDEO_FPS}{subs_filter}",
            *enc_args,
        ])

        if audio_path and os.path.exists(audio_path):
            cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

        cmd.append(output_path)

        print("🎬 영상 생성 중...")
        print(f"   이미지 수: {len(image_paths)}")
        print(f"   오디오: {'있음' if audio_path else '없음'}")
        t = 0.0
        for i, d in enumerate(durations, 1):
            print(f"   장면{i:02d}: {t:6.2f} ~ {t + d:6.2f}초")
            t += d

        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace')
            if result.returncode == 0:
                print(f"✅ 영상 생성 완료: {output_path}")
                return output_path
            else:
                print(f"❌ FFmpeg 오류 (코드 {result.returncode}):")
                print(f"   stderr: {result.stderr}")
                return None
        except Exception as e:
            print(f"❌ 영상 생성 실패: {e}")
            return None

    def create_video_with_moviepy(self, image_paths: list, audio_path: str = None,
                                  output_file: str = "final_video.mp4",
                                  scene_durations: list = None,
                                  scene_texts: list = None,
                                  playback_speed: float = None) -> str:
        """MoviePy를 사용한 영상 생성 (FFmpeg 대안)"""
        try:
            from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, ColorClip

            clips = []
            used_imgs = []
            if scene_durations and len(scene_durations) == len(image_paths):
                durations = [float(d) for d in scene_durations]
                print("⏱️ 장면-음성 동기화: 장면별 음성 길이 적용")
            else:
                durations = [VIDEO_DURATION / len(image_paths)] * len(image_paths)
                print("⏱️ 장면-음성 동기화: 음성 정보 없음 → 균등 분할")

            # 재생 배속 (FFmpeg 경로와 동일 방식)
            speed = float(playback_speed if playback_speed is not None else (VIDEO_PLAYBACK_SPEED or 1.0))
            durations, audio_path, _ = self._apply_playback_speed(durations, audio_path, speed)
            # 끝 여유 무음 (마지막 말 잘림 방지) — 패딩분만큼 마지막 장면도 연장
            end_pad = max(0.0, float(VIDEO_END_PAD_MS or 0) / 1000.0)
            if audio_path and os.path.exists(audio_path) and end_pad > 0:
                padded = self._pad_audio_end(audio_path, end_pad)
                if padded != audio_path:
                    audio_path = padded

            for idx, img_path in enumerate(image_paths):
                if os.path.exists(img_path):
                    clip = ImageClip(img_path, duration=durations[idx])
                    clip = clip.resized(height=VIDEO_HEIGHT)
                    clip = clip.with_position('center')
                    clips.append(clip)
                    used_imgs.append(idx)

            if not clips:
                print("❌ 사용 가능한 이미지가 없습니다.")
                return None

            audio = None
            if audio_path and os.path.exists(audio_path):
                audio = AudioFileClip(audio_path)
                clip_durs = [durations[i] for i in used_imgs]
                total = sum(clip_durs)
                if audio.duration and audio.duration > total + 0.05:
                    pad = audio.duration - total
                    clip_durs[-1] += pad
                    last_img = image_paths[used_imgs[-1]]
                    clips[-1] = (ImageClip(last_img, duration=clip_durs[-1])
                                 .resized(height=VIDEO_HEIGHT)
                                 .with_position('center'))
                    print(f"   ⏱️ 음성 길이 보정: 마지막 장면 +{pad:.2f}초")

            video = concatenate_videoclips(clips, method="compose")

            bg = ColorClip(size=(VIDEO_WIDTH, VIDEO_HEIGHT), color=(0, 0, 0))
            bg = bg.with_duration(video.duration)
            video = CompositeVideoClip([bg, video.with_position('center')])

            if audio is not None:
                video = video.with_audio(audio)

            output_path = str(self.videos_dir / output_file)
            video.write_videofile(output_path, fps=VIDEO_FPS, codec='libx264', audio_codec='aac')

            # 하단 자막(ASS) 비활성화 — 말풍선 이미지에 대사가 이미 포함되어 중복됨.
            # if scene_texts:
            #     ass_path = str(self.output_dir / "subtitles.ass")
            #     if self.build_subtitles_ass(scene_texts, durations, ass_path):
            #         print("💬 자막 삽입 중...")
            #         self.burn_subtitles(output_path, ass_path)

            print(f"✅ 영상 생성 완료: {output_path}")
            return output_path

        except ImportError:
            print("⚠️ MoviePy가 설치되지 않았습니다. pip install moviepy")
            return None
        except Exception as e:
            print(f"❌ MoviePy 영상 생성 실패: {e}")
            return None

    def install_ffmpeg(self):
        """FFmpeg 설치 안내"""
        print("⚠️ FFmpeg가 설치되지 않았습니다.")
        print("👉 다음 링크에서 설치하세요: https://ffmpeg.org/download.html")
        print("또는 다음 명령어로 설치:")
        print("  - Windows (winget): winget install FFmpeg")
        print("  - Windows (choco): choco install ffmpeg")
        print("  - Windows (scoop): scoop install ffmpeg")
