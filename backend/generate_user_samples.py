import os
import sys
from pathlib import Path

# Add backend directory to sys.path so voxcpm2 can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import voxcpm2

def main():
    # Khmer sample text for anime recap style
    khmer_text = "នៅក្នុងពិភពលោកមួយដែលពោរពេញទៅដោយវេទមន្ត និងសត្វចម្លែក ក្មេងប្រុសម្នាក់បានងើបឈរឡើងប្រឆាំងនឹងព្រះជាម្ចាស់! នេះគឺជារឿងរ៉ាវរបស់វីរបុរសដែលមិនធ្លាប់មាននរណាស្គាល់ពីមុនមក។ សូមតាមដានទាំងអស់គ្នា!"
    
    desc = "A high-quality studio recording of a gentle male voice. He speaks extremely fast, yet very softly, warmly, and gently. The delivery is very fast-paced, fluent, soothing, and clear. The audio is completely crisp with zero background noise."
    
    print(f"\nGenerating 15 faster and gentle male voice variations using VoxCPM2 Voice Design...")
    print(f"Prompt: {desc}\n")
    
    # We will invoke model.generate directly in a loop to inject better CFG and timesteps
    import random
    import torch
    import numpy as np
    
    model = voxcpm2.get_model()
    text_with_prompt = f"({desc}) {khmer_text}"
    out_dir = Path("backend/voice_samples/faster_gentle_recap")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    samples = []
    for i in range(1, 16):
        seed_val = random.randint(10000, 99999)
        torch.manual_seed(seed_val)
        np.random.seed(seed_val)
        random.seed(seed_val)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed_val)
            
        wav = model.generate(
            text=text_with_prompt,
            cfg_value=1.5,
            inference_timesteps=8,
            max_len=voxcpm2._estimate_max_len(text_with_prompt),
            retry_badcase=True,
            retry_badcase_max_times=2,
        )
        sample_filename = out_dir / f"faster_gentle_var_{i}_seed_{seed_val}.wav"
        voxcpm2._save_wav_or_convert(wav, sample_filename, model.tts_model.sample_rate)
        samples.append(str(sample_filename))
        print(f"✅ Generated clean variation {i}: {sample_filename}")
    
    print(f"\n--- Anime Recap Generation Complete ---")
    for sample in samples:
        print(f"- {sample}")
    
    print("\n===========================================")
    print("Please listen to these files in the 'backend/voice_samples/faster_gentle_recap' folder.")
    print("Once you select your favorite, you can update voxcpm2.py with its path.")

if __name__ == "__main__":
    main()
