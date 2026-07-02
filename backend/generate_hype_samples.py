import os
import sys
import shutil
import random
import torch
import numpy as np
from pathlib import Path

# Add backend directory to sys.path so voxcpm2 can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import voxcpm2

def main():
    out_dir = Path("backend/voice_samples/hype_recap")
    
    # 1. Delete all existing samples in hype_recap directory to keep it clean
    if out_dir.exists():
        print(f"🗑️ Deleting old voice samples in {out_dir}...")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. 30-second Khmer anime recap intro script (approx. 200+ characters, 25-30s speak duration)
    khmer_text = (
        "សួស្តីហ្វេនៗអានីម៉េទាំងអស់គ្នា! ថ្ងៃនេះខ្ញុំនឹងនាំអ្នកទាំងអស់គ្នាទៅមើលរឿងរ៉ាវរបស់តួឯកយើង "
        "ដែលជាកំពូលអ្នកដាវចាប់ជាតិថ្មីជាក្មេងប្រុសម្នាក់។ ប៉ុន្តែរឿងដែលនឹកស្មានមិនដល់នោះគឺ "
        "គ្រាន់តែចាប់កំណើតភ្លាម គេមានកម្លាំងខ្លាំងកប់ពពកតែម្តង! តើជីវិតថ្មីរបស់គេនឹងទៅជាយ៉ាងណា? "
        "ធានាថាញាក់សាច់ ជក់ចិត្តដិតអារម្មណ៍ហ្មង! តោះទៅទស្សនាទាំងអស់គ្នា!"
    )
    
    # Friendly, fun, engaging YouTuber MC voice profile
    desc = (
        "A high-quality studio recording of a friendly, high-energy male YouTuber. "
        "He narrates an anime recap in an exciting, fun, and engaging MC style, speaking directly to his fans "
        "with warmth, playfulness, and high enthusiasm. The delivery is fast-paced, punchy, conversational, "
        "and extremely clear with zero background noise."
    )
    
    print(f"\nGenerating 15 friendly YouTuber MC voice variations (30s sample length)...")
    print(f"Prompt: {desc}\n")
    print(f"Khmer text: {khmer_text}\n")
    
    model = voxcpm2.get_model()
    text_with_prompt = f"({desc}) {khmer_text}"
    
    samples = []
    for i in range(1, 16):
        seed_val = random.randint(10000, 99999)
        torch.manual_seed(seed_val)
        np.random.seed(seed_val)
        random.seed(seed_val)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed_val)
            
        # Generate with a slightly larger max_len estimation to prevent cutoff for a 30s sample
        max_len_val = int(len(khmer_text) * 4.5) + 200
        
        wav = model.generate(
            text=text_with_prompt,
            cfg_value=1.5,
            inference_timesteps=8,
            max_len=max_len_val,
            retry_badcase=True,
            retry_badcase_max_times=2,
        )
        sample_filename = out_dir / f"hype_var_{i}_seed_{seed_val}.wav"
        voxcpm2._save_wav_or_convert(wav, sample_filename, model.tts_model.sample_rate)
        samples.append(str(sample_filename))
        print(f"✅ Generated clean variation {i} (30s): {sample_filename}")
    
    print(f"\n--- New MC-Style Recap Generation Complete ---")
    for sample in samples:
        print(f"- {sample}")
    
    print("\n===========================================")
    print("Please listen to these files in the 'backend/voice_samples/hype_recap' folder.")
    print("Once you select your favorite, you can update voxcpm2.py with its path.")

if __name__ == "__main__":
    main()
