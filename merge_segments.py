import sqlite3
import sys
import os
import glob

def merge_segments(db_path, start_time_limit, end_time_limit, project_id=None):
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at '{db_path}'")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Get project ID if not provided
    if not project_id:
        cursor.execute("SELECT id, name FROM projects ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            print("Error: No projects found in the database.")
            conn.close()
            return False
        project_id = row[0]
        project_name = row[1]
        print(f"Selected project: '{project_name}' (ID: {project_id})")
    else:
        cursor.execute("SELECT name FROM projects WHERE id = ?", (project_id,))
        row = cursor.fetchone()
        if not row:
            print(f"Error: Project with ID '{project_id}' not found.")
            conn.close()
            return False
        project_name = row[0]
        print(f"Selected project: '{project_name}' (ID: {project_id})")

    # 2. Find segments that overlap with or fall within the specified range [start_time_limit, end_time_limit]
    cursor.execute(
        """
        SELECT id, chunk_index, segment_index, speaker_id, start_time, end_time, 
               original_text, translated_text, detected_voice_type, status 
        FROM segments 
        WHERE project_id = ? 
          AND (
            (start_time >= ? AND start_time < ?) OR 
            (end_time > ? AND end_time <= ?) OR 
            (start_time <= ? AND end_time >= ?)
          )
        ORDER BY start_time
        """,
        (project_id, start_time_limit, end_time_limit, start_time_limit, end_time_limit, start_time_limit, end_time_limit)
    )
    segments_to_merge = cursor.fetchall()

    if not segments_to_merge:
        print(f"No segments found between {start_time_limit}s and {end_time_limit}s for this project.")
        conn.close()
        return False

    print(f"Found {len(segments_to_merge)} segments to merge:")
    for seg in segments_to_merge:
        print(f"  - Seg Index {seg[2]} [{seg[4]:.2f}s - {seg[5]:.2f}s]: \"{seg[6]}\"")

    if len(segments_to_merge) == 1:
        # Update the single segment to span the whole duration if needed
        print("Only 1 segment found in range. Adjusting its timestamps if necessary...")
        seg_id = segments_to_merge[0][0]
        new_start = min(segments_to_merge[0][4], start_time_limit)
        new_end = max(segments_to_merge[0][5], end_time_limit)
        cursor.execute("UPDATE segments SET start_time = ?, end_time = ? WHERE id = ?", (new_start, new_end, seg_id))
        conn.commit()
        print(f"Updated Segment ID {seg_id} to [{new_start:.2f}s - {new_end:.2f}s]")
        conn.close()
        return True

    # 3. Merge data
    first_seg = segments_to_merge[0]
    
    # Combined properties
    merged_start_time = min([seg[4] for seg in segments_to_merge])
    merged_end_time = max([seg[5] for seg in segments_to_merge])
    
    # Text concatenation
    original_texts = []
    translated_texts = []
    
    for seg in segments_to_merge:
        orig = seg[6].strip()
        if orig:
            original_texts.append(orig)
        trans = seg[7].strip() if seg[7] else ""
        if trans:
            translated_texts.append(trans)

    merged_original_text = " ".join(original_texts)
    merged_translated_text = " ".join(translated_texts) if translated_texts else None
    
    # Keep attributes of the first segment
    merged_chunk_index = first_seg[1]
    merged_segment_index = first_seg[2]
    merged_speaker_id = first_seg[3]
    merged_detected_voice_type = first_seg[8]
    
    # Status determination
    merged_status = "translated" if merged_translated_text else "pending"

    # 4. Perform database updates
    target_id = first_seg[0]
    ids_to_delete = [seg[0] for seg in segments_to_merge[1:]]

    print(f"Merging into Segment Index {merged_segment_index} (ID: {target_id}):")
    print(f"  New Range: [{merged_start_time:.2f}s - {merged_end_time:.2f}s]")
    print(f"  New Original Text: \"{merged_original_text}\"")
    if merged_translated_text:
        print(f"  New Translated Text: \"{merged_translated_text}\"")

    cursor.execute(
        """
        UPDATE segments 
        SET start_time = ?, end_time = ?, original_text = ?, 
            translated_text = ?, status = ?, ai_prompt = NULL, audio_path = NULL
        WHERE id = ?
        """,
        (merged_start_time, merged_end_time, merged_original_text, merged_translated_text, merged_status, target_id)
    )

    # Delete the remaining segments
    placeholders = ",".join("?" for _ in ids_to_delete)
    cursor.execute(f"DELETE FROM segments WHERE id IN ({placeholders})", ids_to_delete)
    print(f"Deleted {len(ids_to_delete)} old segments (IDs: {ids_to_delete})")

    # 5. Re-index segment indices sequentially for the project
    cursor.execute("SELECT id FROM segments WHERE project_id = ? ORDER BY start_time", (project_id,))
    all_seg_ids = [row[0] for row in cursor.fetchall()]
    
    for idx, seg_id in enumerate(all_seg_ids):
        cursor.execute("UPDATE segments SET segment_index = ? WHERE id = ?", (idx, seg_id))

    # 6. Reset all segment statuses to 'translated' if they were synthesized to trigger re-rendering
    # since index changes shift segment indices, aligning with the new index files.
    cursor.execute(
        "UPDATE segments SET status = 'translated', audio_path = NULL WHERE project_id = ? AND status = 'synthesized'", 
        (project_id,)
    )

    # 7. Delete old segment audio files to prevent stale voice clips from playing
    project_dir = os.path.join("data", project_id)
    if os.path.exists(project_dir):
        old_tts_files = glob.glob(os.path.join(project_dir, "segment_*_tts.wav"))
        old_final_files = glob.glob(os.path.join(project_dir, "segment_*_final.wav"))
        for f in old_tts_files + old_final_files:
            try:
                os.remove(f)
            except Exception as e:
                print(f"Warning: Could not delete old file {f}: {e}")
        print("Cleaned up old segment audio files on disk.")

    conn.commit()
    print("Merge completed and database/files cleaned successfully!")
    conn.close()
    return True

if __name__ == "__main__":
    db = "./data/pipeline.db"
    start = 10.0
    end = 20.0
    
    if len(sys.argv) > 1:
        try:
            start = float(sys.argv[1])
        except ValueError:
            print("Invalid start time. Using default 10.0")
            
    if len(sys.argv) > 2:
        try:
            end = float(sys.argv[2])
        except ValueError:
            print("Invalid end time. Using default 20.0")

    print(f"Running merge utility for range [{start}s to {end}s]...")
    merge_segments(db, start, end)
