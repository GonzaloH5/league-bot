from PIL import Image, ImageEnhance, ImageFilter
import re
from difflib import SequenceMatcher
import pytesseract

"C:\Program Files\Tesseract-OCR\tesseract.exe"

pytesseract.pytesseract.tesseract_cmd = 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'

def do_ocr(image_path: str) -> str:
    try:
        return pytesseract.image_to_string(image_path, lang='eng+spa')
    except pytesseract.TesseractNotFoundError as e:
        logger.error(f"Tesseract no encontrado: {e}")
        raise RuntimeError("Tesseract-OCR no está instalado o no se encuentra en PATH.")

def preprocess_image_for_ocr(img: Image.Image) -> Image.Image:
    """
    Preprocesa la imagen para mejorar la precisión del OCR.
    """
    # 1) Convertir a escala de grises
    img = img.convert('L')
    # 2) Redimensionar para mejorar legibilidad (aumentar 2x)
    img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
    # 3) Aumentar contraste
    img = ImageEnhance.Contrast(img).enhance(2.0)
    # 4) Aplicar nitidez
    img = img.filter(ImageFilter.SHARPEN)
    # 5) Eliminar ruido con filtro de mediana (opcional, si hay mucho ruido)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    # 6) Binarización con umbral adaptativo
    thresh = 160
    img = img.point(lambda x: 255 if x > thresh else 0, mode='1')
    return img

def extract_nicktags(text: str) -> list[str]:
    """
    Extrae patrones como '#TAG nombre' limitándose al nombre.
    Solo captura letras, números, puntos y guiones, deteniéndose en espacios.
    """
    pattern = re.compile(r'#\w+\s+([\w\.\-]+)', re.IGNORECASE)
    matches = pattern.findall(text)
    return [match.strip() for match in matches]
def normalize_name(name: str) -> str:
    """
    Normaliza un nombre eliminando espacios extra y convirtiendo a minúsculas.
    """
    return re.sub(r'\s+', ' ', name.strip().lower())

def fuzzy_match(a: str, b: str, threshold: float = 0.6) -> bool:
    """
    Compara dos cadenas con un umbral de similitud más bajo para mayor flexibilidad.
    """
    score = SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()
    return score >= threshold

def find_best_nicktag(nicktags: list[str], discord_name: str, discord_display: str) -> str | None:
    """
    Busca el mejor nicktag comparando con username y display_name.
    Prioriza coincidencia exacta, luego contención, luego fuzzy match.
    """
    discord_name = normalize_name(discord_name)
    discord_display = normalize_name(discord_display)

    # Coincidencia exacta
    for tag in nicktags:
        tag_norm = normalize_name(tag)
        if tag_norm == discord_name or tag_norm == discord_display:
            return tag

    # Contención (el nombre de Discord está dentro del nicktag o viceversa)
    for tag in nicktags:
        tag_norm = normalize_name(tag)
        if discord_name in tag_norm or discord_display in tag_norm or tag_norm in discord_name or tag_norm in discord_display:
            return tag

    # Coincidencia aproximada
    for tag in nicktags:
        tag_norm = normalize_name(tag)
        if fuzzy_match(tag_norm, discord_name) or fuzzy_match(tag_norm, discord_display):
            return tag

    return None