from PIL import Image, ImageEnhance, ImageFilter
import re
from difflib import SequenceMatcher
import pytesseract
import os
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger('leaguebot')

TESSERACT_PATH = os.getenv("TESSERACT_PATH", "C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def do_ocr(image_path: str) -> str:
    try:
        return pytesseract.image_to_string(image_path, lang='eng+spa')
    except pytesseract.TesseractNotFoundError as e:
        logger.error(f"Tesseract no encontrado en {TESSERACT_PATH}: {e}")
        raise RuntimeError("Tesseract-OCR no está instalado o la ruta es incorrecta.")

def preprocess_image_for_ocr(img: Image.Image) -> Image.Image:
    img = img.convert('L')
    img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    thresh = 160
    img = img.point(lambda x: 255 if x > thresh else 0, mode='1')
    return img

def extract_nicktags(text: str) -> list[str]:
    pattern = re.compile(r'#\w+\s+([\w\.\-]+)', re.IGNORECASE)
    matches = pattern.findall(text)
    return [match.strip() for match in matches]

def normalize_name(name: str) -> str:
    return re.sub(r'\s+', ' ', name.strip().lower())

def fuzzy_match(a: str, b: str, threshold: float = 0.6) -> bool:
    score = SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()
    return score >= threshold

def find_best_nicktag(nicktags: list[str], discord_name: str, discord_display: str) -> str | None:
    discord_name = normalize_name(discord_name)
    discord_display = normalize_name(discord_display)
    for tag in nicktags:
        tag_norm = normalize_name(tag)
        if tag_norm == discord_name or tag_norm == discord_display:
            return tag
    for tag in nicktags:
        tag_norm = normalize_name(tag)
        if discord_name in tag_norm or discord_display in tag_norm or tag_norm in discord_name or tag_norm in discord_display:
            return tag
    for tag in nicktags:
        tag_norm = normalize_name(tag)
        if fuzzy_match(tag_norm, discord_name) or fuzzy_match(tag_norm, discord_display):
            return tag
    return None
