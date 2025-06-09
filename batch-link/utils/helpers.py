import re

def parse_move_command(self, action_string):
    # Use a regex to extract x, y, and z values
    match = re.findall(r'[xyz]:-?\d+', action_string)
    move_values = {}
    
    # Iterate through the matches and assign the values to x, y, z
    for m in match:
        axis, value = m.split(":")
        move_values[axis] = int(value)  # Convert value to int (or float if needed)
    
    # Now you have the x, y, and z values as a dictionary
    x = move_values.get('x', 0)  # Default to 0 if not provided
    y = move_values.get('y', 0)  # Default to 0 if not provided
    z = move_values.get('z', 0)  # Default to 0 if not provided
    
    return x, y, z

def has_significant_difference(self, key, old_value, new_value):
    thresholds = {
        'bed_temperature': 0.7,
        'nozzle_temperature': 0.7,
    }

    if key in thresholds:
        threshold = thresholds[key]
        try:
            difference = abs(float(new_value) - float(old_value))
            return difference >= threshold
        except (ValueError, TypeError):
            return old_value != new_value
    else:
        return old_value != new_value