import os
import sys
from pathlib import Path

# Add backend directory to sys.path so voxcpm2 can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import voxcpm2

def main():
    khmer_text = "សួស្តី! នេះគឺជាសំឡេងគំរូសម្រាប់ការអត្ถาធិប្បាយវីដេអូរបស់អ្នក។ ខ្ញុំអាចបញ្ចេញអារម្មណ៍ប្រែប្រួលទៅតាមសាច់រឿង។"
    
    prompts = [
        {
            "prefix": "young_cool",
            "desc": "A young, cool, and highly energetic male voice, speaking at a slightly fast and fluent pace like a professional anime recap YouTuber. The tone should be engaging, expressive, and charismatic, filled with excitement to keep listeners hooked. Ensure the voice identity and pitch remain 100% consistent across all sentences."
        },
        {
            "prefix": "mature_epic",
            "desc": "A mature, powerful, and resonant male voice with a cinematic, epic storytelling tone. The delivery should be confident, bold, and slightly dramatic, drawing the audience into a grand adventure. Maintain a steady, fluent pace, ensuring the voice profile does not shift between lines."
        },
        {
            "prefix": "smooth_warm",
            "desc": "A smooth, warm, and clear male voice with an intelligent and articulate tone. The delivery is calm, friendly, and steady, making complex anime plots easy to understand and pleasant to listen to for long periods. Keep the voice and personality completely identical from start to finish."
        }
    ]
    
    import random
    import numpy as np
    import torch
    
    model = voxcpm2.get_model()
    out_dir = Path(voxcpm2.BASE_DIR) / "voice_samples/male"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    for p in prompts:
        prefix = p["prefix"]
        desc = p["desc"]
        print(f"\nGenerating 2 samples for style: {prefix.upper()}...")
        
        text_with_prompt = f"({desc}) {khmer_text}"
        
        with voxcpm2._generate_lock:
            for i in range(1, 3):
                seed_val = random.randint(1000, 99999)
                torch.manual_seed(seed_val)
                np.random.seed(seed_val)
                random.seed(seed_val)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed_val)

                print(f"Generating {prefix} sample {i} (seed {seed_val})...")
                wav = model.generate(
                    text=text_with_prompt,
                    cfg_value=voxcpm2.VOXCPM2_CFG_VALUE,
                    inference_timesteps=voxcpm2.VOXCPM2_INFERENCE_TIMESTEPS,
                    max_len=voxcpm2._estimate_max_len(text_with_prompt),
                    retry_badcase=voxcpm2.VOXCPM2_RETRY_BADCASE,
                    retry_badcase_max_times=1,
                )
                
                output_path_obj = out_dir / f"{prefix}_sample_{i}_seed_{seed_val}.wav"
                voxcpm2._save_wav_or_convert(wav, output_path_obj, model.tts_model.sample_rate)
                print(f"✅ Saved to: {output_path_obj}")

if __name__ == "__main__":
    main()
