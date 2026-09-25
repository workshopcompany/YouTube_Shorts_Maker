"""GGUF 로드 패치 (공용 모듈)
SD3.5 Large Turbo Q4 GGUF용:
(1) pos_embed: GGUF [36864,2432] -> [1,36864,2432]
(2) QK-norm(ln_q/ln_k): 이 GGUF는 QK-norm도 Q4_0으로 양자화되어 raw가 (36,) uint8.
    diffusers는 Linear만 양자화 처리하므로 norm 모듈은 수동 디퀀타이즈 필요.
apply()를 호출하면 diffusers.models.model_loading_utils.load_gguf_checkpoint가 교체된다.
"""
import diffusers.models.model_loading_utils as mlutils
from diffusers.quantizers.gguf.utils import GGUFParameter, dequantize_gguf_tensor

_applied = False

def apply():
    global _applied
    if _applied:
        return
    _orig_load_gguf = mlutils.load_gguf_checkpoint

    def _patched_load_gguf(gguf_checkpoint_path, return_tensors=False):
        sd = _orig_load_gguf(gguf_checkpoint_path, return_tensors)
        if isinstance(sd, dict):
            n_deq = 0
            for key in list(sd.keys()):
                v = sd[key]
                if isinstance(v, GGUFParameter) and ('ln_q' in key or 'ln_k' in key):
                    sd[key] = dequantize_gguf_tensor(v).float()
                    n_deq += 1
                elif 'pos_embed' in key and hasattr(v, 'ndim') and v.ndim == 2:
                    sd[key] = v.unsqueeze(0)
                    print(f'  [patch] {key}: batch dim 추가')
            if n_deq:
                print(f'  [patch] QK-norm 디퀀타이즈: {n_deq}개 텐서')
        return sd

    mlutils.load_gguf_checkpoint = _patched_load_gguf
    _applied = True
    print('[gguf_patch] applied')
