import urllib.parse
import requests
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from .models import Translation


def translate_text(text, target_lang, source_lang='en'):
    """
    Robust multi-provider translation utility:
    1. LibreTranslate (if configured in settings)
    2. Google Translate Client API (dict-chrome-ex with browser header)
    3. MyMemory Translated API
    4. Google Translate Client API (gtx fallback)
    """
    if not text or not target_lang or target_lang.lower() == source_lang.lower():
        return text

    target_lang = target_lang.lower()
    source_lang = source_lang.lower()
    encoded_text = urllib.parse.quote(str(text))

    # Provider 1: LibreTranslate (if available)
    libre_url = getattr(settings, 'LIBRETRANSLATE_URL', None)
    if libre_url:
        payload = {
            'q': text,
            'source': source_lang,
            'target': target_lang,
            'format': 'text'
        }
        try:
            response = requests.post(libre_url, json=payload, timeout=4)
            if response.status_code == 200:
                tr = response.json().get('translatedText')
                if tr and tr.strip():
                    return tr
        except Exception as e:
            pass

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # Provider 2: Google Translate dict-chrome-ex (highest success rate)
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=dict-chrome-ex&sl={source_lang}&tl={target_lang}&dt=t&q={encoded_text}"
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                translated = ''.join([part[0] for part in data[0] if part and len(part) > 0 and part[0]])
                if translated and translated.strip():
                    return translated
    except Exception as e:
        pass

    # Provider 3: MyMemory API (with valid de email for 10k words daily quota)
    try:
        mm_url = f"https://api.mymemory.translated.net/get?q={encoded_text}&langpair={source_lang}|{target_lang}&de=concierge@luxurybonecarving.com"
        res = requests.get(mm_url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            tr = data.get('responseData', {}).get('translatedText')
            if tr and tr.strip() and not tr.startswith('MYMEMORY WARNING') and tr.strip().lower() != text.strip().lower():
                return tr
    except Exception as e:
        pass

    # Provider 4: Google Translate gtx fallback
    try:
        gtx_url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={encoded_text}"
        res = requests.get(gtx_url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                translated = ''.join([part[0] for part in data[0] if part and len(part) > 0 and part[0]])
                if translated and translated.strip():
                    return translated
    except Exception as e:
        pass

    return text


def save_translation(obj, field_name, language_code, translated_text):
    """
    Create or update a Translation record.
    Never persists empty text or text identical to original source if non-English.
    """
    if not translated_text:
        return None

    source_text = getattr(obj, field_name, None)
    if source_text and language_code != 'en' and translated_text.strip().lower() == source_text.strip().lower():
        # Do not save untranslated English text as a foreign translation
        return None

    try:
        from django.db import connection
        content_type = ContentType.objects.get_for_model(obj)
        translation, _ = Translation.objects.update_or_create(
            content_type=content_type,
            object_id=obj.pk,
            language_code=language_code,
            field_name=field_name,
            defaults={'translated_text': translated_text}
        )
        return translation
    except Exception as e:
        print(f"Warning: could not save translation for {field_name} ({language_code}): {e}")
        return None


def translate_object_to_all_languages(obj, fields_to_translate):
    """Generic function to translate specified fields of an object into all supported languages."""
    source_lang = 'en'
    target_langs = [code for code, _ in getattr(settings, 'SUPPORTED_LANGUAGES', [('hi', 'Hindi')])]
    for field in fields_to_translate:
        source_text = getattr(obj, field, None)
        if not source_text:
            continue
        for lang_code in target_langs:
            if lang_code == source_lang:
                continue
            translated = translate_text(source_text, lang_code, source_lang)
            if translated and translated.strip().lower() != source_text.strip().lower():
                save_translation(obj, field, lang_code, translated)


def translate_product_to_all_languages(product):
    fields = ['title', 'description', 'short_description', 'material', 'dimensions', 'meta_title', 'meta_description']
    translate_object_to_all_languages(product, fields)


def translate_category_to_all_languages(category):
    fields = ['name', 'description']
    translate_object_to_all_languages(category, fields)


def translate_collection_to_all_languages(collection):
    fields = ['name', 'description']
    translate_object_to_all_languages(collection, fields)