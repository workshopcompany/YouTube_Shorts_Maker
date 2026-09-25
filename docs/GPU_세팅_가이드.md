# GTX 1080 Ti (Pascal, sm_6.1) 세팅 가이드
# 최종 확인: 2026-09-12 / 이 PC 실측 기준
# ============================================================

## 1. 내 GPU 사양 (nvidia-smi 실측)

- 모델: NVIDIA GeForce GTX 1080 Ti
- VRAM: 11GB (11264 MiB)
- 드라이버: 576.88
- Compute Capability: 6.1 (Pascal, sm_61)

## 2. 웹 검색 결과 요약

PyTorch 공식 previous-versions 페이지 기준 최신은
torch 2.13 + CUDA 12.6/13.x 라인이다.
하지만 CUDA 12.x부터 Pascal(sm_60/sm_61) 지원이 단계적으로
제거됐고, GTX 1080 Ti에서 안정적으로 동작이 확인된 조합은
`torch 2.5.x + cu118`이다.

- cu118 = CUDA 11.8 빌드 = Pascal sm_61 네이티브 지원
- cu121/cu124/cu126은 1080 Ti에서
  설치는 되지만 커널 호환 문제 보고가 있다
- 결론: **이 PC는 torch 2.5.1+cu118 유지가 정답.
  최신 torch로 업그레이드 금지**

## 3. 현재 venv 상태 (<project>\venv, Python 3.11.9)

| 패키지 | 버전 | 비고 |
|---|---|---|
| torch | 2.5.1+cu118 | CUDA 사용 가능 |
| diffusers | 0.40.0 | SD 3.5 지원 |
| transformers | 5.17.0 | - |
| accelerate | 1.15.0 | CPU 오프로드용 |
| safetensors | 0.8.0 | - |

확인 명령:
```
.\venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability(0))"
# 기대값: 2.5.1+cu118 True (6, 1)
```

## 4. SD 3.5 Large + 1080 Ti 주의사항

- SD 3.5 Large는 8B급이라 11GB VRAM에 그대로 안 올라간다.
  `enable_model_cpu_offload()` 필수 (image_gen.py에 반영됨)
- 1080 Ti는 bf16 미지원 → `torch.float16` 사용 (image_gen.py 반영됨)
- 권장: 576x1024, 28스텝, 장당 수 분 소요 예상
- torch 업그레이드 시 sm_61 커널이 사라져서
  `no kernel image is available` 에러가 난다. 업그레이드 금지.

## 5. 절대 건드리면 안 되는 것

1. `pip install torch --upgrade` 금지 (cu118 고정)
2. CUDA Toolkit 별도 설치 불필요 (torch에 런타임 내장)
3. 드라이버는 576.88 유지 (CUDA 11.8 런타임과 호환됨)

## 6. 문제 발생 시 복구

```
.\venv\Scripts\pip.exe install torch==2.5.1+cu118 --index-url https://download.pytorch.org/whl/cu118
```

## 7. 폴더마다 설치된 것 관리 방법

지금 D:\에 venv/conda가 여러 개 있다
(ai_assistant2, Friend_AI, miniconda3, pinokio 등).
정리 원칙:

1. **이 프로젝트는 <project>\venv 전용으로 고정한다.**
   다른 폴더 venv를 건드리지 않는다.
2. **PATH로 공용 torch를 공유하지 않는다.**
   torch는 프로젝트마다 버전이 달라서 공용화하면 깨진다.
   폴더마다 venv를 두는 현재 방식이 맞다.
3. **용량이 문제면 pip 캐시만 지운다.**
   `pip cache purge` (venv 자체는 삭제 금지)
4. **새 프로젝트 시작 시** 이 venv를 복사하지 말고
   `python -m venv venv`로 새로 만들고
   위 3번 표 버전만 동일하게 설치한다.
5. PATH로 가능한 것: ffmpeg, git 같은 **버전 충돌 없는 도구만**
   시스템 PATH에 둔다. torch/diffusers는 venv 격리 유지.

---

## 8. conda CUDA를 복사해 쓸 때 누락 방지 (2026-09-19 추가)

### 8-1. 전제: 이 PC엔 정식 CUDA Toolkit이 없다
- `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA` → **없음**
- 실제 소스는 **conda**: `D:\pinokio\bin\miniforge\Library` 의 CUDA 12.8.93
- 그래서 `D:\CUDA\v12.8` 로 **복사해서 표준 레이아웃을 조립**해 쓴다
- **문제: 사람이 파일 목록을 적어 복사하면 반드시 빠뜨린다.**
  실제로 이 때문에 빌드가 4번 연속 실패했고, 원인이 전부 “복사 누락”이었다.

### 8-2. 실제로 빠뜨려서 터진 것들 (실측 에러 메시지)

| 빠진 것 | 증상 (실제 나온 에러) |
|---|---|
| `bin\crt\link.stub` | `c1xx: fatal error C1083: 'D:\CUDA\v12.8\bin\crt\link.stub': No such file or directory` → CMake는 `Compiling the CUDA compiler identification source file "CMakeCUDACompilerId.cu" failed` 로만 보여줘서 원인 파악이 어렵다 |
| `bin\nvcc.profile` | `CMake Error at CMakeNVCCParseImplicitInfo.cmake:133: Failed to extract nvcc implicit link line.` (진짜 원인 로그: `no 'LIBRARIES=' string found in nvcc output`, `no 'INCLUDES=' string found`) |
| `lib\x64\cufft.lib` | `Target "engine_runtime" links to: CUDA::cufft but the target was not found` (generate 단계) |
| `lib\x64\cuda.lib` | `Target "ggml-cuda" links to: CUDA::cuda_driver but the target was not found` (generate 단계) |
| 빌드 스크립트가 `LIB` 에 CUDA 경로 미등록 | `LINK : fatal error LNK1181: 'cudadevrt.lib' 파일을 열 수 없습니다` |

**중요:** 이 5개는 증상이 전부 달라 보이지만 원인은 하나다 → **“필요한 파일/경로가 빠짐”**.
특히 `link.stub`, `nvcc.profile` 은 이름이 낯설어서 목록에서 빠지기 쉽다.

### 8-3. 올바른 복사 원칙 (핵심 3가지)

1. **파일 목록을 손으로 나열하지 말고, 패턴으로 전부 복사한다.**
   - bin 도구: `nvcc.exe`, `ptxas.exe`, `nvlink.exe`, `fatbinary.exe`,
     `cudafe++.exe`, `cuobjdump.exe`, `nvdisasm.exe`, `nvprune.exe`
     **+ `nvcc.profile`** ← 이게 핵심
   - `bin\crt\` → **폴더째** 복사 (`link.stub`, `prelink.stub`)
   - `lib\*.lib` 중 CUDA 계열 → **전부**
   - `bin\*.dll` 중 CUDA 계열 → **전부** (cufft64_11.dll 등)
   - `include\`, `nvvm\` → 통째 복사

2. **conda는 `lib\`, 정식 Toolkit은 `lib\x64\` 를 쓴다.**
   → **양쪽에 다** 넣어둔다 (`lib\x64` 와 `lib` 모두에 .lib 복사).
   CMAKE의 `FindCUDAToolkit` 이 `CUDA::*` IMPORTED target 을 못 만들면
   configure 는 통과해도 generate 에서 죽는다.

3. **`Copy-Item` 중첩 함정 주의**
   ```
   Copy-Item "src\crt" "dst\crt" -Recurse       # ✗ dst\crt\crt\link.stub 로 들어감 (조용히 누락)
   Copy-Item "src\crt\*" "dst\crt\" -Recurse    # ✓ 이렇게 쓴다
   ```

### 8-4. 복사 후 검증 체크리스트 (반드시 실행)

```powershell
$dst = 'D:\CUDA\v12.8'
# (1) 컴파일 필수
Test-Path "$dst\bin\nvcc.exe"            # True
Test-Path "$dst\bin\nvcc.profile"        # True  ← 없으면 CMake configure 실패
Test-Path "$dst\bin\crt\link.stub"       # True  ← 없으면 모든 .cu 컴파일 실패
Test-Path "$dst\nvvm\bin\cicc.exe"       # True
# (2) 링크 필수 lib
Test-Path "$dst\lib\x64\cudart.lib"      # True
Test-Path "$dst\lib\x64\cudadevrt.lib"   # True  ← device-link 용
Test-Path "$dst\lib\x64\cufft.lib"       # True  ← CUDA::cufft target
Test-Path "$dst\lib\x64\cuda.lib"        # True  ← CUDA::cuda_driver target
```

### 8-5. nvcc 건강 검진 (가장 확실한 최종 확인)

`nvcc.profile` 이 살아 있으면 `nvcc -v` 출력에 아래 두 줄이 **반드시** 나온다.
안 나오면 CMake 는 100% 실패한다.

```powershell
$vc = 'D:\VS2022BuildTools\VC\Tools\MSVC\14.44.35207'
& 'D:\CUDA\v12.8\bin\nvcc.exe' -ccbin "$vc\bin\Hostx64\x64\cl.exe" `
    -v -c test.cu -o test.obj 2>&1 | Select-String 'LIBRARIES=|INCLUDES='
# 기대값:
# #$ INCLUDES="-ID:\CUDA\v12.8\bin/../include"  "-I.../include/targets/x64"
# #$ LIBRARIES=  "/LIBPATH:D:\CUDA\v12.8\bin/../lib/x64"  "/LIBPATH:D:\CUDA\v12.8\bin/../lib"
```

### 8-6. 빌드 스크립트 쪽 필수 설정 (이것도 빠뜨리면 LNK1181)

`INCLUDE` 에만 CUDA 를 넣으면 **컴파일은 되고 링크에서 죽는다.**
`LIB` 에도 반드시 넣는다.

```powershell
Add-EnvListFront "INCLUDE" @("$env:CUDA_PATH\include")
Add-EnvListFront "LIB"     @("$env:CUDA_PATH\lib\x64", "$env:CUDA_PATH\lib")
```

### 8-7. 재발 방지 스크립트 (복사해서 쓰면 됨)

`D:\likesuno\scripts\prepare_cuda.ps1` 이 위 원칙대로 작성되어 있다.
- 패턴 기반으로 lib/dll 을 **전부** 복사
- `link.stub` / `nvcc.profile` 누락 시 자동 보강(REPAIR)
- 복사 후 `nvcc` 출력에 `LIBRARIES=` 가 나오는지 **자체 검증**까지 수행

→ **새 프로젝트에서 CUDA 를 conda 에서 조립할 때 이 스크립트를 그대로 복사해서 쓴다.**

### 8-8. 빌드 스크립트는 반드시 WMI로 실행 (세션 종료 문제)

```powershell
$cmd = 'cmd /c ""C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File D:\likesuno\scripts\build_runtime.ps1 1>> D:\likesuno\logs\build.log 2>&1"'
([wmiclass]'root\cimv2:Win32_Process').Create($cmd)
```
`Start-Process` 로 띄우면 대화형 세션이 끝날 때 **자식 프로세스가 강제 종료**되어
빌드가 중간에 죽는다(로그가 4KB 버퍼 경계에서 뚝 끊김). WMI 로 띄우면 살아남는다.
