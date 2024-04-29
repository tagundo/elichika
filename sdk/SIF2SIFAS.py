import json
         
original_data = [
  {
    "timing_sec": 2.093,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 1,
    "effect_value": 2,
    "position": 5
  },
  {
    "timing_sec": 2.521,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 4,
    "effect_value": 2,
    "position": 5
  },
  {
    "timing_sec": 4.379,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 1,
    "effect_value": 2,
    "position": 5
  },
  {
    "timing_sec": 4.807,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 2,
    "effect_value": 2,
    "position": 5
  },
  {
    "timing_sec": 6.379,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 4,
    "effect_value": 2,
    "position": 6
  },
  {
    "timing_sec": 6.379,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 4,
    "effect_value": 2,
    "position": 4
  },
  {
    "timing_sec": 6.664,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 3,
    "effect_value": 0.286,
    "position": 5
  },
  {
    "timing_sec": 7.093,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 1,
    "effect_value": 2,
    "position": 7
  },
  {
    "timing_sec": 7.379,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 4,
    "effect_value": 2,
    "position": 3
  },
  {
    "timing_sec": 7.664,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 1,
    "effect_value": 2,
    "position": 7
  },
  {
    "timing_sec": 8.95,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 3,
    "effect_value": 0.286,
    "position": 5
  },
  {
    "timing_sec": 9.379,
    "notes_attribute": 1,
    "notes_level": 1,
    "effect": 1,
    "effect_value": 2,
    "position": 8
  },
]

def check_position(current_position, previous_position):
    if current_position == 5 and previous_position in [6, 7, 8, 9]:
        return 1
    elif current_position == 4:
        return 1
    elif current_position == 3:
        return 1
    elif current_position == 2:
        return 1
    elif current_position == 1:
        return 1
    elif current_position == 5 and previous_position in [1, 2, 3, 4]:
        return 2
    elif current_position == 6:
        return 2
    elif current_position == 7:
        return 2
    elif current_position == 8:
        return 2
    elif current_position == 9:
        return 2
    else:
        return 1
        

def note_position(position):
    return check_position(original_data)

def convert_to_ms(timing_sec):
    # Convert the timing_sec to milliseconds and maintain the trailing zeros
    timing_ms = int(timing_sec * 1000)
    return timing_ms

def convert_timing_to_ms(original_data):
    for entry in original_data:
        entry["timing_ms"] = convert_to_ms(entry["timing_sec"])
        del entry["timing_sec"]
    return original_data

def convert_to_ms1(effect_value):
    # Convert the timing_sec to milliseconds and maintain the trailing zeros
    effect_value_ms = int(effect_value * 1000)
    return effect_value_ms

def convert_timing_to_ms1(original_data):
    for entry in original_data:
        entry["effect_value_ms"] = convert_to_ms1(entry["effect_value"])
        del entry["effect_value"]
    return original_data

convert_timing_to_ms(original_data)
convert_timing_to_ms1(original_data)

# export settings
live_diff_id = 123456789
output_name = "sif2sifas_test"

# DON'T TOUCH THESE!

# Initialize output list and id counter
output_notes = []
id_counter = 1

# Iterate over original data
for i, entry in enumerate(original_data):
    if entry["effect"] == 1: # normal note
        if i > 0:  # Ensure we have a previous entry
            previous_position = original_data[i - 1]["position"]
        else:
            previous_position = None  # No previous position for the first entry
        output_notes.append({
            "id": id_counter,
            "call_time": entry["timing_ms"],
            "note_type": 1,
            "note_position": check_position(entry["position"], previous_position),
            "gimmick_id": 0,
            "note_action": 1,
            "wave_id": 0,
            "note_random_drop_color": 99,
            "auto_judge_type": 14
        })
        id_counter += 1
    elif entry["effect"] == 3 and entry["effect_value_ms"] > 1: # long note
        if i > 0:  # Ensure we have a previous entry
            previous_position = original_data[i - 1]["position"]
        else:
            previous_position = None  # No previous position for the first entry
        output_notes.append({
            "id": id_counter,
            "call_time": entry["timing_ms"],
            "note_type": 2,
            "note_position": check_position(entry["position"], previous_position),
            "gimmick_id": 0,
            "note_action": 1,
            "wave_id": 0,
            "note_random_drop_color": 99,
            "auto_judge_type": 14
        })
        id_counter += 1
        output_notes.append({
            "id": id_counter,
            "call_time": int(entry["timing_ms"]) + int(entry["effect_value_ms"]),
            "note_type": 3,
            "note_position": check_position(entry["position"], previous_position),
            "gimmick_id": 0,
            "note_action": 1,
            "wave_id": 0,
            "note_random_drop_color": 99,
            "auto_judge_type": 14
        })
        id_counter += 1
    else:
        if i > 0:  # Ensure we have a previous entry
            previous_position = original_data[i - 1]["position"]
        else:
            previous_position = None  # No previous position for the first entry
        output_notes.append({
            "id": id_counter,
            "call_time": entry["timing_ms"],
            "note_type": 1,
            "note_position": check_position(entry["position"], previous_position),
            "gimmick_id": 0,
            "note_action": 1,
            "wave_id": 0,
            "note_random_drop_color": 99,
            "auto_judge_type": 14
        })
        id_counter += 1

# Create the final output
output_data = {
    "live_difficulty_id": live_diff_id,
    "live_notes": output_notes,
    "live_wave_settings": [],
    "note_gimmicks": [],
    "stage_gimmick_dict": []
}

output_filename = f"{output_name}.json"
with open(output_filename, "w") as outfile:
    json.dump(output_data, outfile, indent=2)