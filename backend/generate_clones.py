import os
import sys
import random
import torch
import numpy as np
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import voxcpm2

def main():
    khmer_text = "នៅក្នុងពិភពលោកមួយដែលពោរពេញទៅដោយវេទមន្ត និងសត្វចម្លែក ក្មេងប្រុសម្នាក់បានងើបឈរឡើងប្រឆាំងនឹងព្រះជាម្ចាស់! នេះគឺជារឿងរ៉ាវរបស់វីរបុរសដែលមិនធ្លាប់មាននរណាស្គាល់ពីមុនមក។ សូមតាមដានទាំងអស់គ្នា!"
    desc = "A mature, cool, and highly energetic male voice, speaking at a slightly fast and fluent pace like a professional anime recap YouTuber. The tone should be engaging, expressive, and charismatic, filled with excitement to keep listeners hooked. Ensure the voice identity and pitch remain 100% consistent across all sentences."
    text_with_prompt = f"({desc}) {khmer_text}"

    # We will use sample 1 and sample 6 from the first batch as references
    ref_1 = r"Z:\year3\projecj video translate backup\backend\voice_samples\anime_recap\voice_sample_1_seed_54123.wav"
    ref_6 = r"Z:\year3\projecj video translate backup\backend\voice_samples\anime_recap\voice_sample_6_seed_72113.wav"

    out_dir = Path("backend/voice_samples/anime_recap_clones")
    out_dir.mkdir(parents=True, exist_ok=True)

    model = voxcpm2.get_model()

    print("Generating 3 variations based on Sample 1...")
    for i in range(1, 4):
        seed_val = random.randint(10000, 99999)
        torch.manual_seed(seed_val)
        np.random.seed(seed_val)
        random.seed(seed_val)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed_val)

        wav = model.generate(
            text=text_with_prompt,
            reference_wav_path=ref_1,
            cfg_value=voxcpm2.VOXCPM2_CFG_VALUE,
            inference_timesteps=voxcpm2.VOXCPM2_INFERENCE_TIMESTEPS,
            max_len=voxcpm2._estimate_max_len(text_with_prompt),
            retry_badcase=voxcpm2.VOXCPM2_RETRY_BADCASE,
            retry_badcase_max_times=1,
        )
        sample_filename = out_dir / f"clone_of_sample1_var_{i}_seed_{seed_val}.wav"
        voxcpm2._save_wav_or_convert(wav, sample_filename, model.tts_model.sample_rate)
        print(f"✅ Generated variation {i} for Sample 1: {sample_filename}")

    print("\nGenerating 3 variations based on Sample 6...")
    for i in range(1, 4):
        seed_val = random.randint(10000, 99999)
        torch.manual_seed(seed_val)
        np.random.seed(seed_val)
        random.seed(seed_val)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed_val)

        wav = model.generate(
            text=text_with_prompt,
            reference_wav_path=ref_6,
            cfg_value=voxcpm2.VOXCPM2_CFG_VALUE,
            inference_timesteps=voxcpm2.VOXCPM2_INFERENCE_TIMESTEPS,
            max_len=voxcpm2._estimate_max_len(text_with_prompt),
            retry_badcase=voxcpm2.VOXCPM2_RETRY_BADCASE,
            retry_badcase_max_times=1,
        )
        sample_filename = out_dir / f"clone_of_sample6_var_{i}_seed_{seed_val}.wav"
        voxcpm2._save_wav_or_convert(wav, sample_filename, model.tts_model.sample_rate)
        print(f"✅ Generated variation {i} for Sample 6: {sample_filename}")

if __name__ == "__main__":
    main()
