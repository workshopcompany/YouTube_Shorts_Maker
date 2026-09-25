"""SD3.5 Large Turbo GGUF -> PyTorch state_dict 변환"""
import sys, os, time, gc, re, warnings
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

import torch
from pathlib import Path as _Path
_MODEL = _Path(__file__).resolve().parents[1] / 'model'
ckpt_path = str(_MODEL / 'sd3.5_large_turbo-q4_k_4_0.gguf')
out_path = str(_MODEL / 'sd3.5_large_turbo.pt')

from diffusers.models.model_loading_utils import load_gguf_checkpoint
from diffusers.quantizers.gguf.utils import GGUFParameter

print(f'Loading GGUF: {ckpt_path}')
t0 = time.time()
gguf_sd = load_gguf_checkpoint(ckpt_path)
print(f'Loaded {len(gguf_sd)} tensors in {time.time()-t0:.1f}s')

out_sd = {}
for k, v in gguf_sd.items():
    if not k.startswith('model.diffusion_model.'):
        continue
    new_k = k[len('model.diffusion_model.'):]
    new_k = re.sub(r'^joint_blocks\.(\d+)\.x_block\.', r'transformer_blocks.\1.', new_k)
    new_k = re.sub(r'^joint_blocks\.(\d+)\.context_block\.', r'transformer_blocks.\1.context_.', new_k)
    new_k = new_k.replace('final_layer.linear.', 'proj_out.')
    new_k = new_k.replace('final_layer.adaLN_modulation.1.', 'norm_out.linear.')
    new_k = new_k.replace('x_embedder.', 'pos_embed.')
    new_k = new_k.replace('t_embedder.', 'time_text_embed.')
    new_k = new_k.replace('context_embedder.', 'context_embedder.')
    new_k = new_k.replace('attn.ln_q.', 'attn.norm_q.')
    new_k = new_k.replace('attn.ln_k.', 'attn.norm_k.')
    new_k = new_k.replace('.adaLN_modulation.1.', '.linear.')
    if isinstance(v, GGUFParameter):
        v = v.dequantize()
    # Convert to plain Tensor via numpy (bypasses GGUFParameter __torch_function__)
    import numpy as np
    if hasattr(v, 'numpy'):
        v = torch.from_numpy(v.numpy().copy())
    # pos_embed dim fix
    if 'pos_embed' in new_k and v.ndim == 2:
        v = v.unsqueeze(0)
    out_sd[new_k] = v.half().contiguous()
    del v
print(f'Converted {len(out_sd)} tensors')

del gguf_sd; gc.collect()

print(f'Saving to {out_path}...')
t0 = time.time()
torch.save(out_sd, out_path, _use_new_zipfile_serialization=True)
print(f'Saved in {time.time()-t0:.1f}s')
print(f'Size: {os.path.getsize(out_path)/1024**3:.1f} GB')
print('DONE')
