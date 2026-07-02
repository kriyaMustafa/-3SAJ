import os
import sys

# Add backend to path
sys.path.append(os.path.abspath('backend'))

from database import SessionLocal
import models

PROJECT_ID = '757d3433-2453-4478-b497-abc0c1c50fa0'

CORRECT_TEXT = (
    '[Arrogant tone] អា\u200bតិរច្ឆាន\u200bនោះ\u200bងាក\u200bក្បាល\u200bមក\u200b រួច\u200bសួរ\u200bទាំង\u200bឫកពា\u200bខ្ពស់\u200bថា\u200b '
    '"ឯង\u200bចង់\u200bមាន\u200bន័យ\u200bថា\u200bម៉េច?" សិស្ស\u200bគណ\u200bម្នាក់\u200bនោះ\u200bក៏\u200bតប\u200bវិញ\u200bថា\u200b '
    'ក្នុង\u200bពេល\u200bប្រកួត\u200bសាកល្បង\u200b មិន\u200bបាច់\u200bវាយ\u200bធ្វើ\u200bបាប\u200bគូ\u200bប្រកួត\u200bឲ្យ\u200bរបួស\u200b'
    'ធ្ងន់ធ្ងរ\u200bពេក\u200bនោះ\u200bទេ។ អា\u200bក្មេង\u200bនោះ\u200bអង្គុយ\u200bស្តាប់\u200bទាំង\u200bជ្រួញ\u200b'
    'ចិញ្ចើម\u200bចូល\u200bគ្នា\u200b ពេល\u200bត្រូវ\u200bគេ\u200bប្រាប់\u200bថា\u200b នេះ\u200bហើយ\u200bជា\u200b'
    'ហេតុផល\u200bដែល\u200bមិត្តភក្តិ\u200bរបស់\u200bវា\u200bនៅ\u200bមាន\u200bជីវិត។ ទាំង\u200bលាត\u200bដៃ\u200b'
    'ទាំង\u200bពីរ\u200bចេញ\u200b សិស្ស\u200bជំនាន់\u200bទី\u200bពីរ\u200bរបស់\u200bបក្ស\u200bចុងណាន\u200b'
    'និយាយ\u200bមើល\u200bងាយ\u200bថា\u200b "បើ\u200bកាល\u200bណោះ\u200bក្នុង\u200bដៃ\u200bខ្ញុំ\u200bជា\u200b'
    'ដាវ\u200bពិត\u200bប្រាកដ\u200bវិញ\u200bនោះ\u200b អា\u200bម្នាក់\u200bហ្នឹង\u200bដេក\u200bក្នុង\u200b'
    'មឈូស\u200bបាត់\u200bទៅ\u200bហើយ!"  ទាំង\u200bញញឹម\u200bចំអក\u200b ជីមរី\u200b ពោល\u200bពាក្យ\u200b'
    'សុំទោស\u200bបែប\u200bឌឺដង\u200bថា\u200b គាត់\u200bមិន\u200bនឹក\u200bស្មាន\u200bសោះ\u200bថា\u200bសត្រូវ\u200b'
    'របស់\u200bខ្លួន\u200bខ្សោយ\u200bកន្ទ្រើក\u200bដូច\u200bជា\u200bកូន\u200bមាន់\u200bបែប\u200bហ្នឹង\u200b '
    'ស្តាប់\u200bហើយ\u200b បេតស៊ីន\u200b ខាំ\u200bធ្មេញ\u200bក្រទើត\u200bទាំង\u200bកំហឹង។ ងាក\u200bក្បាល\u200b'
    'មក\u200bវិញ\u200b ក្មេង\u200bប្រុស\u200bនោះ\u200bប្រាប់\u200bឲ្យ\u200bគេ\u200bសែង\u200bអ្នក\u200bរង\u200b'
    'របួស\u200bទៅ\u200bបន្ទប់\u200bព្យាបាល\u200bភ្លាម។ ពួក\u200bសិស្ស\u200bគណ\u200bក៏\u200bសែង\u200b'
    'មិត្តភក្តិ\u200bរួម\u200bបក្ស\u200bដើរ\u200bចេញ\u200bទៅ។ ទាំង\u200bសម្លឹង\u200bមើល\u200bទៅ\u200b'
    'ក្រោម\u200b ក្មេង\u200bប្រុស\u200bនោះ\u200bសុំ\u200bសាកល្បង\u200bកម្លាំង\u200bធាតុ\u200bពិត\u200b'
    'នៃ\u200bក្បាច់\u200bដាវ\u200bចុងណាន\u200bមើល\u200bមើល៍។ ជីមរី\u200b បើក\u200bមាត់\u200bព្រម\u200b'
    'ទទួល\u200bការ\u200bប្រកួត\u200bភ្លាម។'
)

def main():
    db = SessionLocal()
    try:
        s = db.query(models.Segment).filter(
            models.Segment.project_id == PROJECT_ID,
            models.Segment.segment_index == 0
        ).first()
        
        if s:
            print(f"Original segment 0 length: {len(s.translated_text or '')}")
            s.translated_text = CORRECT_TEXT
            s.status = 'translated'
            s.audio_path = None
            db.commit()
            print("Successfully updated Segment 0 to correct translation in database.")
        else:
            print("Segment 0 not found.")
            
        # Delete segment 0 audio files if they exist
        project_dir = os.path.join('data', PROJECT_ID)
        s0_tts = os.path.join(project_dir, 'segment_0_tts.wav')
        s0_final = os.path.join(project_dir, 'segment_0_final.wav')
        
        for f in (s0_tts, s0_final):
            if os.path.exists(f):
                try:
                    os.remove(f)
                    print(f"Removed old file: {f}")
                except Exception as e:
                    print(f"Error removing {f}: {e}")
                    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    main()
