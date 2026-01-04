import random
import string


def generate_invite_code(length: int = 8) -> str:
    """
    Generate a unique invite code for a league
    
    Args:
        length: Length of the invite code (default: 8)
    
    Returns:
        Random invite code string (uppercase letters and digits, excluding confusing characters)
    """
    # Exclude confusing characters: 0, O, I, 1
    characters = string.ascii_uppercase.replace('O', '').replace('I', '') + string.digits.replace('0', '').replace('1', '')
    
    invite_code = ''.join(random.choice(characters) for _ in range(length))
    return invite_code
