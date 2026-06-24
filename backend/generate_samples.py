import os
import sys
from pathlib import Path

# Add backend directory to sys.path so voxcpm2 can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import voxcpm2

def main():
    # Khmer sample text
    khmer_text = "សួស្តី! នេះគឺជាសំឡេងគំរូសម្រាប់ការអត្ថាធិប្បាយវីដេអូរបស់អ្នក។ ខ្ញុំអាចបញ្ចេញអារម្មណ៍ប្រែប្រួលទៅតាមសាច់រឿង។"
    
    descriptions = {
        "male": "A deep, engaging, and clear male voice tailored for anime recap narration. The tone should be energetic and dramatic during action scenes, yet calm and informative during plot explanations. Maintain a steady, fluent, and moderate speaking pace, ensuring the voice remains 100% consistent as the exact same male character across all generated sentences without any tone switching."
    }
    
    all_samples = []
    
    for gender, desc in descriptions.items():
        print(f"\nGenerating 6 {gender.upper()} voice variations using VoxCPM2 Voice Design...")
        samples = voxcpm2.generate_voice_samples(
            description=desc,
            num_samples=6,
            output_dir=f"voice_samples/{gender}",
            sample_text=khmer_text
        )
        all_samples.extend(samples)
        
        print(f"\n--- {gender.capitalize()} Generation Complete ---")
        for sample in samples:
            print(f"- {sample}")
    
    print("\n===========================================")
    print("Please listen to these files in the 'backend/voice_samples' folder.")
    print("Once you select your favorite, note its file path.")

if __name__ == "__main__":
    main()
