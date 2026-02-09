import re
from typing import Optional

def normalize_username(username: Optional[str]) -> Optional[str]:
    """
    Normalizes a Telegram username: lowercase, remove @, remove non-alphanumeric.
    """
    if not username:
        return None
    
    # Strip whitespace and @ prefix
    normalized = username.strip().lstrip("@")
    
    # Basic validation (Telegram usernames are 5-32 chars, a-z, 0-9, _)
    normalized = re.sub(r'[^a-zA-Z0-9_]', '', normalized)
    return normalized.lower() if normalized else None

def normalize_link(link: str) -> Optional[str]:
    """
    Extracts a username from a t.me or telegram.me link.
    """
    if not link:
        return None
        
    # Extract username/invite link from URL
    # Remove protocol and domain
    s = re.sub(r"^https?://", "", link.strip())
    s = re.sub(r"^(www\.)?t\.me/", "", s)
    s = re.sub(r"^(www\.)?telegram\.me/", "", s)
    s = re.sub(r"^joinchat/", "", s)
    
    s = s.split("?")[0] # Remove query params
    s = s.split("/")[0] # Take first segment if multiple
    
    return normalize_username(s)

def transliterate_uz_ru(text: str) -> str:
    """
    Basic transliteration for common Uzbek/Russian Cyrillic characters to Latin.
    """
    mapping = {
        'ш': 'sh', 'ч': 'ch', 'ў': 'o', 'ғ': 'g', 'қ': 'q', 'ҳ': 'h',
        'ю': 'yu', 'я': 'ya', 'ё': 'yo', 'ц': 'ts', 'щ': 'sh', 'ы': 'y',
        'э': 'e', 'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
        'е': 'e', 'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
        'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h'
    }
    text = text.lower()
    res = []
    for char in text:
        res.append(mapping.get(char, char))
    return "".join(res)

def normalize_title(title: str) -> str:
    """
    Robust title normalization: lowercase, transliterate, remove emojis/special chars, collapse spaces.
    """
    if not title:
        return ""
        
    # Lowercase and Transliterate
    text = transliterate_uz_ru(title)
    
    # Remove non-alphanumeric (except space)
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    
    # Collapse spaces
    text = re.sub(r"\s+", " ", text).strip()
    
    return text

