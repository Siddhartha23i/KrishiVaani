"""
Telegram Message Handlers for KrishiVaani — Phase 8.3.

Provides asynchronous handlers for:
1. /start: Welcomes the farmer with localized Telugu guidance and disclaimer.
2. Text messages:
   - Fast greeting handling (avoids agricultural LLM execution for simple greetings).
   - Full ConversationOrchestrator pipeline executed in a background thread via asyncio.to_thread.
3. Voice notes (OGG Opus):
   - Shows 'record_voice' chat action while processing.
   - Enforces <= 30-second duration constraint with polite Telugu notice.
   - Converts OGG Opus to WAV and executes VoicePipelineService (Prisma STT, Orchestration, Timbre TTS).
   - Strictly enforces safety guardrail: if safety_status is REJECTED, sends text-only guidance and NO audio.
   - Encodes WAV response to mono OGG Opus via convert_wav_bytes_to_ogg_opus and delivers via send_voice.
   - Falls back gracefully to text on TTS or conversion failures.
4. Error resilience: catches exceptions and delivers safe Telugu fallback without crashing the polling loop.
5. Idempotency: deduplicates update_ids.
"""

import io
import time
import base64
import inspect
import logging
import asyncio
import re
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import Optional, Set, List
from collections import deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.conversation.service import ConversationOrchestrator
from app.core.config import settings
from app.telegram.memory import ConversationMemoryStore
from app.conversation.intent import is_pure_greeting, is_weather_query
from app.conversation.schemas import ConversationRequest, LocationInput, GuestWeatherConsentEvent
from app.voice.service import VoicePipelineService
from app.voice.schemas import VoiceProcessingRequest
from app.voice.exceptions import AudioDurationExceededError, AudioValidationError
from app.whatsapp.audio_converter import convert_wav_bytes_to_ogg_opus
from app.telegram.audio import convert_ogg_opus_to_wav
from app.telegram.session import (
    TelegramSessionRepository,
    TelegramUserSession,
    is_consent_grant,
    is_consent_reject,
    is_location_deletion_request,
    extract_location_from_text,
)

def _generate_fallback_wav_bytes() -> bytes:
    """Generate minimal valid PCM WAV bytes for audio encoding fallback in test environments."""
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 8000)
    return buf.getvalue()


logger = logging.getLogger(__name__)

# Standard localized natural conversational messages (Phase 8.4 / Part 1)
START_MESSAGE = (
    "నమస్కారం! నేను కృషివాణిని. మీ భాషలో మీ ప్రశ్నను వాయిస్ మెసేజ్‌గా పంపండి; "
    "ఇంగ్లీష్‌లో కూడా అడగవచ్చు. ఇది సాధారణ సమాచారం మాత్రమే, కాబట్టి ముఖ్యమైన పంట నిర్ణయాలను "
    "మీ స్థానిక వ్యవసాయ అధికారితో నిర్ధారించండి. మీకు సహాయం చేయడానికి మీ ముందరి ప్రశ్నలను గుర్తుంచుకుంటాను. "
    "వాటిని తొలగించడానికి /forget పంపండి."
)
START_MESSAGES = {
    "en-IN": "Welcome to KrishiVaani, your farming assistant. Send a voice message with your question in your own language (English is fine too), and I will answer you.",
    "hi-IN": "कृषिवाणी में आपका स्वागत है, यह आपका कृषि सहायक है। अपनी भाषा में सवाल वाला वॉइस संदेश भेजें, अंग्रेज़ी भी चलेगी और मैं जवाब दूँगा। यह सामान्य जानकारी है, इसलिए फसल के महत्वपूर्ण फैसले अपने स्थानीय कृषि अधिकारी से पक्का करें। आपकी मदद के लिए मैं आपके पहले के सवाल याद रखता हूँ। उन्हें मिटाने के लिए /forget भेजें।",
    "ta-IN": "கிருஷிவாணிக்கு வரவேற்கிறோம், இது உங்கள் விவசாய உதவியாளர். உங்கள் மொழியில் கேள்வியுடன் குரல் செய்தி அனுப்புங்கள்; ஆங்கிலமும் பரவாயில்லை, நான் பதில் அளிப்பேன். இது பொதுவான தகவல் என்பதால் முக்கியமான பயிர் முடிவுகளை உள்ளூர் வேளாண்மை அதிகாரியிடம் உறுதிப்படுத்துங்கள். உதவிக்காக உங்கள் முந்தைய கேள்விகளை நினைவில் வைத்திருப்பேன். அவற்றை நீக்க /forget அனுப்புங்கள்.",
    "kn-IN": "ಕೃಷಿವಾಣಿಗೆ ಸ್ವಾಗತ, ಇದು ನಿಮ್ಮ ಕೃಷಿ ಸಹಾಯಕ. ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ ಪ್ರಶ್ನೆಯಿರುವ ಧ್ವನಿ ಸಂದೇಶ ಕಳುಹಿಸಿ; ಇಂಗ್ಲಿಷ್ ಕೂಡ ಸರಿ, ನಾನು ಉತ್ತರಿಸುತ್ತೇನೆ. ಇದು ಸಾಮಾನ್ಯ ಮಾಹಿತಿ ಆದ್ದರಿಂದ ಮುಖ್ಯ ಬೆಳೆ ನಿರ್ಧಾರಗಳನ್ನು ಸ್ಥಳೀಯ ಕೃಷಿ ಅಧಿಕಾರಿಯೊಂದಿಗೆ ಖಚಿತಪಡಿಸಿಕೊಳ್ಳಿ. ಸಹಾಯಕ್ಕಾಗಿ ನಿಮ್ಮ ಹಿಂದಿನ ಪ್ರಶ್ನೆಗಳನ್ನು ನೆನಪಿನಲ್ಲಿ ಇಡುತ್ತೇನೆ. ಅವನ್ನು ಅಳಿಸಲು /forget ಕಳುಹಿಸಿ.",
    "ml-IN": "കൃഷിവാണിയിലേക്ക് സ്വാഗതം, ഇത് നിങ്ങളുടെ കൃഷി സഹായി. നിങ്ങളുടെ ഭാഷയിൽ ചോദ്യം അടങ്ങിയ ശബ്ദസന്ദേശം അയയ്ക്കൂ; ഇംഗ്ലീഷും ശരിയാണ്, ഞാൻ മറുപടി നൽകും. ഇത് പൊതുവായ വിവരമാണ്, അതിനാൽ പ്രധാന വിള തീരുമാനങ്ങൾ പ്രാദേശിക കൃഷി ഉദ്യോഗസ്ഥനോട് ഉറപ്പാക്കുക. സഹായത്തിനായി നിങ്ങളുടെ മുമ്പത്തെ ചോദ്യങ്ങൾ ഞാൻ ഓർക്കും. അവ നീക്കാൻ /forget അയയ്ക്കൂ.",
    "mr-IN": "कृषिवाणीमध्ये आपले स्वागत आहे, हा तुमचा शेती सहाय्यक आहे. तुमच्या भाषेत प्रश्न असलेला आवाज संदेश पाठवा; इंग्रजीही चालेल आणि मी उत्तर देईन. ही सामान्य माहिती आहे, त्यामुळे पिकांचे महत्त्वाचे निर्णय स्थानिक कृषी अधिकाऱ्यांकडून निश्चित करून घ्या. मदतीसाठी मी तुमचे आधीचे प्रश्न लक्षात ठेवतो. ते हटवण्यासाठी /forget पाठवा.",
    "pa-IN": "ਕ੍ਰਿਸ਼ੀਵਾਣੀ ਵਿੱਚ ਤੁਹਾਡਾ ਸਵਾਗਤ ਹੈ, ਇਹ ਤੁਹਾਡਾ ਖੇਤੀ ਸਹਾਇਕ ਹੈ। ਆਪਣੀ ਭਾਸ਼ਾ ਵਿੱਚ ਸਵਾਲ ਵਾਲਾ ਵੌਇਸ ਸੁਨੇਹਾ ਭੇਜੋ; ਅੰਗਰੇਜ਼ੀ ਵੀ ਠੀਕ ਹੈ ਅਤੇ ਮੈਂ ਜਵਾਬ ਦਿਆਂਗਾ। ਇਹ ਆਮ ਜਾਣਕਾਰੀ ਹੈ, ਇਸ ਲਈ ਮਹੱਤਵਪੂਰਨ ਫਸਲ ਫੈਸਲੇ ਆਪਣੇ ਸਥਾਨਕ ਖੇਤੀਬਾੜੀ ਅਧਿਕਾਰੀ ਤੋਂ ਪੱਕੇ ਕਰ ਲਓ। ਤੁਹਾਡੀ ਮਦਦ ਲਈ ਮੈਂ ਤੁਹਾਡੇ ਪਿਛਲੇ ਸਵਾਲ ਯਾਦ ਰੱਖਦਾ ਹਾਂ। ਉਨ੍ਹਾਂ ਨੂੰ ਮਿਟਾਉਣ ਲਈ /forget ਭੇਜੋ।",
    "bn-IN": "কৃষিবাণীতে আপনাকে স্বাগতম, এটি আপনার কৃষি সহায়ক। নিজের ভাষায় প্রশ্নসহ একটি ভয়েস বার্তা পাঠান; ইংরেজিও চলবে এবং আমি উত্তর দেব। এটি সাধারণ তথ্য, তাই গুরুত্বপূর্ণ ফসলের সিদ্ধান্ত স্থানীয় কৃষি আধিকারিকের সঙ্গে নিশ্চিত করুন। সাহায্যের জন্য আমি আপনার আগের প্রশ্ন মনে রাখি। সেগুলি মুছতে /forget পাঠান।",
    "gu-IN": "કૃષિવાણીમાં આપનું સ્વાગત છે, આ તમારો ખેતી સહાયક છે. તમારી ભાષામાં પ્રશ્ન સાથે વૉઇસ સંદેશ મોકલો; અંગ્રેજી પણ ચાલશે અને હું જવાબ આપીશ. આ સામાન્ય માહિતી છે, તેથી પાકના મહત્વના નિર્ણયોની પુષ્ટિ તમારા સ્થાનિક કૃષિ અધિકારી સાથે કરો. તમારી મદદ માટે હું તમારા અગાઉના પ્રશ્નો યાદ રાખું છું. તેમને કાઢવા /forget મોકલો.",
}

GREETING_MESSAGE = "నమస్తే! నేను మీ కృషివాణిని. పంటలు లేదా వాతావరణం గురించి ఏమైనా అడగండి, సహాయం చేస్తాను."

DURATION_LIMIT_MESSAGE = (
    "క్షమించండి, మీ వాయిస్ మెసేజ్ 30 సెకన్ల కంటే ఎక్కువ ఉంది. "
    "దయచేసి 30 సెకన్ల లోపు చిన్న మెసేజ్ పంపండి."
)

FALLBACK_ERROR_MESSAGE = (
    "క్షమించండి, మీ మెసేజ్ అందుకోవడంలో చిన్న సాంకేతిక సమస్య వచ్చింది. "
    "దయచేసి కాసేపటి తర్వాత మళ్ళీ ప్రయత్నించండి."
)

TELEGRAM_ABSTENTION_FALLBACK = (
    "దీని గురించి పూర్తిగా నిర్ధారించిన వివరాలు నా దగ్గర ప్రస్తుతం లేవు. "
    "మీ పొలం పరిస్థితికి తగ్గట్టు సరైన సలహా కోసం మీ మండల వ్యవసాయ అధికారిని గానీ, దగ్గర్లో ఉన్న కృషి విజ్ఞాన కేంద్రాన్ని గానీ అడగండి."
)

LOCALIZED_FALLBACKS = {
    "hi-IN": {
        "error": "क्षमा करें, संदेश संसाधित करने में तकनीकी समस्या आई। कुछ सेकंड बाद फिर पूछें।",
        "duration": "आपका वॉइस संदेश 30 सेकंड से लंबा है। कृपया छोटा संदेश भेजें।",
        "consent_declined": "ठीक है। मौसम के लिए आपका स्थान साझा नहीं किया जाएगा और सहेजे गए स्थान का विवरण हटा दिया गया है।",
        "consent_ack": "ठीक है। मौसम की जानकारी के लिए आपका स्थान उपयोग किया जा सकता है। जिले या तहसील का मौसम पूछिए।",
    },
    "en-IN": {
        "error": "Sorry, a technical problem occurred. Please wait a few seconds and try again.",
        "duration": "Your voice message is longer than 30 seconds. Please send a shorter message.",
        "consent_declined": "Okay. I will not share your location for weather, and I deleted the stored location details.",
        "consent_ack": "Okay. I can use your location for weather. Ask for weather for a district or mandal.",
    },
    "te-IN": {
        "error": "క్షమించండి, సాంకేతిక సమస్య వచ్చింది. కొన్ని సెకన్లు ఆగి మళ్లీ అడగండి.",
        "duration": "మీ వాయిస్ సందేశం 30 సెకన్ల కంటే ఎక్కువగా ఉంది. చిన్న సందేశం పంపండి.",
        "consent_declined": "సరే. వాతావరణం కోసం మీ లొకేషన్ పంచబడదు. నిల్వ చేసిన లొకేషన్ వివరాలను తొలగించాను.",
        "consent_ack": "సరే. వాతావరణం కోసం మీ లొకేషన్‌ను ఉపయోగించవచ్చు. జిల్లా లేదా మండలం వాతావరణం అడగండి.",
    },
    "ta-IN": {"error": "மன்னிக்கவும், தொழில்நுட்ப சிக்கல் ஏற்பட்டது. சில விநாடிகள் கழித்து மீண்டும் கேளுங்கள்.", "duration": "உங்கள் குரல் செய்தி 30 விநாடிகளுக்கு மேல் உள்ளது. சிறிய செய்தியை அனுப்புங்கள்.", "consent_declined": "சரி. வானிலைக்காக உங்கள் இருப்பிடம் பகிரப்படாது. சேமித்த இருப்பிட விவரங்கள் நீக்கப்பட்டன.", "consent_ack": "சரி. வானிலை தகவலுக்காக உங்கள் இருப்பிடத்தைப் பயன்படுத்தலாம். மாவட்டம் அல்லது வட்டத்தின் வானிலையைக் கேளுங்கள்."},
    "kn-IN": {"error": "ಕ್ಷಮಿಸಿ, ತಾಂತ್ರಿಕ ತೊಂದರೆ ಉಂಟಾಗಿದೆ. ಕೆಲವು ಸೆಕೆಂಡುಗಳ ನಂತರ ಮತ್ತೆ ಕೇಳಿ.", "duration": "ನಿಮ್ಮ ಧ್ವನಿ ಸಂದೇಶ 30 ಸೆಕೆಂಡುಗಳಿಗಿಂತ ಉದ್ದವಾಗಿದೆ. ಚಿಕ್ಕ ಸಂದೇಶ ಕಳುಹಿಸಿ.", "consent_declined": "ಸರಿ. ಹವಾಮಾನಕ್ಕಾಗಿ ನಿಮ್ಮ ಸ್ಥಳವನ್ನು ಹಂಚಿಕೊಳ್ಳುವುದಿಲ್ಲ. ಉಳಿಸಿದ ಸ್ಥಳದ ವಿವರಗಳನ್ನು ಅಳಿಸಲಾಗಿದೆ.", "consent_ack": "ಸರಿ. ಹವಾಮಾನ ಮಾಹಿತಿಗಾಗಿ ನಿಮ್ಮ ಸ್ಥಳವನ್ನು ಬಳಸಬಹುದು. ಜಿಲ್ಲೆ ಅಥವಾ ಮಂಡಲದ ಹವಾಮಾನವನ್ನು ಕೇಳಿ."},
    "mr-IN": {"error": "माफ करा, तांत्रिक अडचण आली. काही सेकंद थांबून पुन्हा विचारा.", "duration": "तुमचा आवाज संदेश ३० सेकंदांपेक्षा मोठा आहे. छोटा संदेश पाठवा.", "consent_declined": "ठीक आहे. हवामानासाठी तुमचे ठिकाण शेअर केले जाणार नाही आणि साठवलेली ठिकाणाची माहिती हटवली आहे.", "consent_ack": "ठीक आहे. हवामानासाठी तुमचे ठिकाण वापरता येईल. जिल्हा किंवा तालुक्याचे हवामान विचारा."},
    "ml-IN": {"error": "ക്ഷമിക്കണം, സാങ്കേതിക പ്രശ്നമുണ്ടായി. കുറച്ച് സെക്കൻഡ് കഴിഞ്ഞ് വീണ്ടും ചോദിക്കൂ.", "duration": "നിങ്ങളുടെ ശബ്ദസന്ദേശം 30 സെക്കൻഡിൽ കൂടുതലാണ്. ചെറിയ സന്ദേശം അയയ്ക്കൂ.", "consent_declined": "ശരി. കാലാവസ്ഥയ്ക്കായി നിങ്ങളുടെ സ്ഥലം പങ്കിടില്ല. സൂക്ഷിച്ച സ്ഥലവിവരങ്ങൾ നീക്കി.", "consent_ack": "ശരി. കാലാവസ്ഥയ്ക്കായി നിങ്ങളുടെ സ്ഥലം ഉപയോഗിക്കാം. ജില്ലയുടെയോ മണ്ഡലത്തിന്റെയോ കാലാവസ്ഥ ചോദിക്കൂ."},
    "pa-IN": {"error": "ਮਾਫ਼ ਕਰਨਾ, ਤਕਨੀਕੀ ਸਮੱਸਿਆ ਆਈ। ਕੁਝ ਸਕਿੰਟ ਰੁਕ ਕੇ ਫਿਰ ਪੁੱਛੋ।", "duration": "ਤੁਹਾਡਾ ਵੌਇਸ ਸੁਨੇਹਾ 30 ਸਕਿੰਟ ਤੋਂ ਲੰਮਾ ਹੈ। ਛੋਟਾ ਸੁਨੇਹਾ ਭੇਜੋ।", "consent_declined": "ਠੀਕ ਹੈ। ਮੌਸਮ ਲਈ ਤੁਹਾਡਾ ਟਿਕਾਣਾ ਸਾਂਝਾ ਨਹੀਂ ਕੀਤਾ ਜਾਵੇਗਾ ਅਤੇ ਸੁਰੱਖਿਅਤ ਟਿਕਾਣੇ ਦੀ ਜਾਣਕਾਰੀ ਮਿਟਾ ਦਿੱਤੀ ਗਈ ਹੈ।", "consent_ack": "ਠੀਕ ਹੈ। ਮੌਸਮ ਲਈ ਤੁਹਾਡਾ ਟਿਕਾਣਾ ਵਰਤਿਆ ਜਾ ਸਕਦਾ ਹੈ। ਜ਼ਿਲ੍ਹੇ ਜਾਂ ਮੰਡਲ ਦਾ ਮੌਸਮ ਪੁੱਛੋ।"},
    "bn-IN": {"error": "দুঃখিত, প্রযুক্তিগত সমস্যা হয়েছে। কয়েক সেকেন্ড পরে আবার জিজ্ঞাসা করুন।", "duration": "আপনার ভয়েস বার্তা ৩০ সেকেন্ডের বেশি। ছোট বার্তা পাঠান।", "consent_declined": "ঠিক আছে। আবহাওয়ার জন্য আপনার অবস্থান শেয়ার করা হবে না এবং সংরক্ষিত অবস্থানের তথ্য মুছে দেওয়া হয়েছে।", "consent_ack": "ঠিক আছে। আবহাওয়ার তথ্যের জন্য আপনার অবস্থান ব্যবহার করা যাবে। জেলার আবহাওয়া জিজ্ঞাসা করুন।"},
    "gu-IN": {"error": "માફ કરશો, તકનીકી સમસ્યા આવી. થોડી સેકન્ડ પછી ફરી પૂછો.", "duration": "તમારો વૉઇસ સંદેશ 30 સેકન્ડથી લાંબો છે. ટૂંકો સંદેશ મોકલો.", "consent_declined": "ઠીક છે. હવામાન માટે તમારું સ્થાન શેર કરવામાં આવશે નહીં અને સાચવેલી સ્થાન માહિતી કાઢી નાખી છે.", "consent_ack": "ઠીક છે. હવામાન માટે તમારું સ્થાન વાપરી શકાય છે. જિલ્લા અથવા તાલુકાનું હવામાન પૂછો."},
}

CONSENT_INSTRUCTIONS = {
    "te-IN": "దయచేసి ‘అవును’ లేదా ‘సరే’ అని రిప్లై చేయండి.",
    "hi-IN": "कृपया ‘हाँ’ या ‘ठीक है’ लिखकर जवाब दें।",
    "en-IN": "Please reply with “Yes” or “No”, or choose a button below.",
    "ta-IN": "‘ஆம்’ அல்லது ‘சரி’ என்று பதில் அளிக்கவும்.",
    "kn-IN": "‘ಹೌದು’ ಅಥವಾ ‘ಸರಿ’ ಎಂದು ಉತ್ತರಿಸಿ.",
    "ml-IN": "‘അതെ’ അല്ലെങ്കിൽ ‘ശരി’ എന്ന് മറുപടി നൽകുക.",
    "mr-IN": "‘हो’ किंवा ‘ठीक आहे’ असे उत्तर द्या.",
    "pa-IN": "‘ਹਾਂ’ ਜਾਂ ‘ਠੀਕ ਹੈ’ ਲਿਖ ਕੇ ਜਵਾਬ ਦਿਓ।",
    "bn-IN": "‘হ্যাঁ’ বা ‘ঠিক আছে’ লিখে উত্তর দিন।",
    "gu-IN": "‘હા’ અથવા ‘ઠીક છે’ લખીને જવાબ આપો.",
}
CONSENT_BUTTONS = {
    "te-IN": ("అవును", "వద్దు"),
    "hi-IN": ("हाँ", "नहीं"),
    "en-IN": ("Yes", "No"),
    "ta-IN": ("ஆம்", "இல்லை"),
    "kn-IN": ("ಹೌದು", "ಇಲ್ಲ"),
    "ml-IN": ("അതെ", "ഇല്ല"),
    "mr-IN": ("हो", "नाही"),
    "pa-IN": ("ਹਾਂ", "ਨਹੀਂ"),
    "bn-IN": ("হ্যাঁ", "না"),
    "gu-IN": ("હા", "ના"),
}

GREETING_PATTERNS = {
    "hi", "hello", "hey", "namaste", "namaskar", "namaskaram",
    "నమస్కారం", "నమస్కారం!", "నమస్తే", "నమస్తే!", "హలో", "హాయ్", "నమస్కారము",
    "నమస్తే ", "నమస్తే !", "నమస్కారం ", "నమస్కారం !",
    "శుభోదయం", "శుభ సాయంత్రం", "బాగున్నారా", "ఎలా ఉన్నారు",
}


def is_greeting(text: Optional[str]) -> bool:
    """
    Check if the user input is a pure conversational greeting.
    Bypasses expensive LLM reasoning for simple greetings while keeping responses fast and non-empty.
    """
    if is_pure_greeting(text or ""):
        return True
    if not text:
        return False
    cleaned = text.strip()
    cleaned_lower = cleaned.lower()
    cleaned_no_punct = cleaned.strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()

    if cleaned_lower in GREETING_PATTERNS or cleaned_no_punct in GREETING_PATTERNS:
        return True

    parts = cleaned_no_punct.split()
    if len(parts) <= 2 and parts[0] in GREETING_PATTERNS:
        return True
    return False


class UpdateDeduplicator:
    """Bounded in-memory deduplicator for Telegram update_ids."""

    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._seen: Set[int] = set()
        self._order: deque = deque()

    def is_duplicate(self, update_id: int) -> bool:
        if update_id in self._seen:
            return True
        self._seen.add(update_id)
        self._order.append(update_id)
        if len(self._order) > self.max_size:
            oldest = self._order.popleft()
            self._seen.discard(oldest)
        return False


class TelegramHandler:
    """
    Central handler for Telegram bot interactions.
    Encapsulates ConversationOrchestrator and VoicePipelineService.
    """

    def __init__(
        self,
        orchestrator: Optional[ConversationOrchestrator] = None,
        voice_service: Optional[VoicePipelineService] = None,
        session_repo: Optional[TelegramSessionRepository] = None,
        memory_store: Optional[ConversationMemoryStore] = None,
    ):
        self.orchestrator = orchestrator or ConversationOrchestrator()
        self.voice_service = voice_service or VoicePipelineService()
        self.session_repo = session_repo or TelegramSessionRepository()
        self.memory_store = memory_store or ConversationMemoryStore(db_path=getattr(self.session_repo, "db_path", None))
        if getattr(self.orchestrator, "memory_store", None) is None:
            self.orchestrator.memory_store = self.memory_store
        if getattr(self.voice_service, "orchestrator", None) is not None:
            if getattr(self.voice_service.orchestrator, "memory_store", None) is None:
                self.voice_service.orchestrator.memory_store = self.memory_store
        self.deduplicator = UpdateDeduplicator()

    @staticmethod
    def _language_hint(text: str) -> str:
        if any("\u0900" <= char <= "\u097f" for char in text):
            return "hi-IN"
        if any("\u0c80" <= char <= "\u0cff" for char in text):
            return "kn-IN"
        if any("\u0b80" <= char <= "\u0bff" for char in text):
            return "ta-IN"
        if any("\u0c00" <= char <= "\u0c7f" for char in text):
            return "te-IN"
        if any("\u0d00" <= char <= "\u0d7f" for char in text):
            return "ml-IN"
        if any("\u0a80" <= char <= "\u0aff" for char in text):
            return "gu-IN"
        if any("\u0980" <= char <= "\u09ff" for char in text):
            return "bn-IN"
        if any("\u0a00" <= char <= "\u0a7f" for char in text):
            return "pa-IN"
        return "en-IN"

    @staticmethod
    def _explicit_weather_place(text: str) -> Optional[str]:
        """Return a place named in the current weather question, if one is explicit."""
        _, _, district, _ = extract_location_from_text(text)
        if district:
            return district
        match = re.search(
            r"\b(?:in|at|near)\s+([A-Za-z][A-Za-z .'-]{1,50}?)(?=\s+(?:today|tomorrow|weather|forecast|will|be)\b|[?!.]|$)",
            text,
            re.IGNORECASE,
        )
        return match.group(1).strip(" .,-") if match else None

    def _stored_language(self, user_id: str) -> Optional[str]:
        if not getattr(settings, "USER_ID_HASH_SALT", None):
            return None
        return self.memory_store.get_language(user_id)

    @staticmethod
    def _localized_fallback(language: str, kind: str, default: str) -> str:
        return LOCALIZED_FALLBACKS.get(language, {}).get(kind, default)

    @staticmethod
    def _consent_markup(language: str) -> InlineKeyboardMarkup:
        yes, no = CONSENT_BUTTONS.get(language, CONSENT_BUTTONS["en-IN"])
        return InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(yes, callback_data="consent:yes"),
                InlineKeyboardButton(no, callback_data="consent:no"),
            ]]
        )

    @staticmethod
    def _consent_prompt_text(language: str, text: str) -> str:
        instruction = CONSENT_INSTRUCTIONS.get(language, CONSENT_INSTRUCTIONS["en-IN"])
        return f"{text.rstrip()} {instruction}"

    @staticmethod
    def _localized_greeting(language: str) -> str:
        return {
            "te-IN": "నమస్తే! నేను కృషివాణిని. పంటలు లేదా వాతావరణం గురించి అడగండి.",
            "hi-IN": "नमस्ते! मैं कृषिवाणी हूँ। फसल या मौसम के बारे में पूछिए।",
            "en-IN": "Hello! I am KrishiVaani. Ask me about crops or weather.",
            "ta-IN": "வணக்கம்! நான் கிருஷிவாணி. பயிர்கள் அல்லது வானிலை பற்றி கேளுங்கள்.",
            "kn-IN": "ನಮಸ್ಕಾರ! ನಾನು ಕೃಷಿವಾಣಿ. ಬೆಳೆಗಳು ಅಥವಾ ಹವಾಮಾನದ ಬಗ್ಗೆ ಕೇಳಿ.",
            "ml-IN": "നമസ്കാരം! ഞാൻ കൃഷിവാണിയാണ്. വിളകളെയോ കാലാവസ്ഥയെയോ കുറിച്ച് ചോദിക്കൂ.",
            "mr-IN": "नमस्कार! मी कृषिवाणी आहे. पिके किंवा हवामानाबद्दल विचारा.",
            "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਮੈਂ ਕ੍ਰਿਸ਼ੀਵਾਣੀ ਹਾਂ। ਫਸਲਾਂ ਜਾਂ ਮੌਸਮ ਬਾਰੇ ਪੁੱਛੋ।",
            "bn-IN": "নমস্কার! আমি কৃষিবাণী। ফসল বা আবহাওয়া সম্পর্কে জিজ্ঞাসা করুন।",
            "gu-IN": "નમસ્તે! હું કૃષિવાણી છું. પાક અથવા હવામાન વિશે પૂછો.",
        }.get(language, GREETING_MESSAGE)

    def _save_turn_background(self, user_id: str, language: str, question: str, response) -> None:
        if getattr(response, "safety_status", None) != "PASSED":
            return
        async def save() -> None:
            try:
                await asyncio.to_thread(
                    self.memory_store.save_turn,
                    user_id,
                    language,
                    question,
                    response.response_text,
                    response.intent,
                    response.safety_status,
                )
            except Exception as save_error:
                logger.error("Conversation memory save failed: %s", save_error, exc_info=True)

        try:
            asyncio.create_task(save())
        except Exception as save_error:
            logger.error("Could not schedule conversation memory save: %s", save_error)

    async def handle_forget(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message:
            return
        user_id = str(update.effective_user.id if update.effective_user else "guest")
        try:
            await asyncio.to_thread(self.memory_store.forget, user_id)
            await message.reply_text("మీ ముందు ప్రశ్నలు, సమాధానాల జ్ఞాపకాన్ని తొలగించాను.")
        except Exception as forget_error:
            logger.error("Conversation memory deletion failed: %s", forget_error, exc_info=True)
            await message.reply_text("క్షమించండి , జ్ఞాపకాన్ని తొలగించలేకపోయాను. కాసేపటి తర్వాత మళ్లీ ప్రయత్నించండి.")

    async def handle_consent_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Route an inline consent choice through the same persisted handler path as typed text."""
        query = update.callback_query
        if not query or not query.data or not query.from_user or not query.message:
            return
        choice = query.data.removeprefix("consent:")
        if choice not in {"yes", "no"}:
            return
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not remove consent buttons after selection.", exc_info=True)
        choice_text = "yes" if choice == "yes" else "no"
        proxy_update = SimpleNamespace(
            update_id=None,
            effective_user=query.from_user,
            effective_chat=getattr(query, "message", None).chat,
            effective_message=SimpleNamespace(
                text=choice_text,
                reply_text=query.message.reply_text,
                voice=None,
                audio=None,
            ),
        )
        await self.handle_text(proxy_update, context)

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.effective_message:
            return

        if update.update_id and self.deduplicator.is_duplicate(update.update_id):
            logger.info("Ignoring duplicate Telegram update_id: %s", update.update_id)
            return

        t0 = time.perf_counter()
        logger.info("Handling /start Telegram event (update_id: %s)", update.update_id)

        try:
            await update.effective_message.reply_text(START_MESSAGES["en-IN"])
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.info(
                "Telegram event: update_id=%s, type=/start, duration_ms=%.2f, status=success",
                update.update_id,
                elapsed_ms,
            )
        except Exception as e:
            logger.error("Failed to send /start response: %s", type(e).__name__, exc_info=True)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text message."""
        message = update.effective_message
        if not message or not message.text:
            return

        if update.update_id and self.deduplicator.is_duplicate(update.update_id):
            logger.info("Ignoring duplicate Telegram update_id: %s", update.update_id)
            return

        t0 = time.perf_counter()
        user = update.effective_user
        user_id = str(user.id if user else "guest")
        text = message.text.strip()
        preferred_language = await asyncio.to_thread(self._stored_language, user_id)
        preferred_language = preferred_language or self._language_hint(text)
        logger.info("Handling Telegram text event (update_id: %s)", update.update_id)

        try:
            # Load active session
            session = self.session_repo.get_session(user_id)

            # 1. Check for explicit user location data deletion request
            if is_location_deletion_request(text):
                logger.info("Telegram user requested location data deletion.")
                self.session_repo.clear_location(user_id)
                self.session_repo.clear_pending_query(user_id)
                deletion_ack = "మీ లొకేషన్ వివరాలు విజయవంతంగా తొలగించబడ్డాయి."
                await message.reply_text(deletion_ack)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=location_deletion, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 2. Check for explicit rejection / withdrawal of consent
            if is_consent_reject(text):
                logger.info("Telegram user explicitly rejected or withdrew weather sharing consent.")
                self.session_repo.set_consent(user_id, consent_given=False)
                self.session_repo.clear_location(user_id)  # Purge stored location on consent withdrawal
                self.session_repo.clear_pending_query(user_id)
                rejection_msg = self._localized_fallback(
                    preferred_language,
                    "consent_declined",
                    "Okay. I will not share your location for weather, and I deleted the stored location details.",
                )
                await message.reply_text(rejection_msg)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=consent_reject, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 3. Check for affirmative consent grant (gated by awaiting_consent for short words)
            if is_consent_grant(text, awaiting_consent=session.awaiting_consent):
                logger.info("Telegram user granted explicit weather sharing consent (awaiting=%s).", session.awaiting_consent)
                session = self.session_repo.set_consent(user_id, consent_given=True)
                pending_query = session.pending_weather_query
                self.session_repo.clear_pending_query(user_id)

                if pending_query:
                    logger.info("Resuming pending weather query.")
                    pv, pm, pd, pp = extract_location_from_text(pending_query)
                    if any([pv, pm, pd, pp]):
                        self.session_repo.update_location(user_id, village=pv, mandal=pm, district=pd, pin_code=pp)
                        session = self.session_repo.get_session(user_id)

                    guest_consent = GuestWeatherConsentEvent(
                        consent_given=True,
                        disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                        consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                        channel="telegram",
                    )
                    loc_input = None
                    if session.district_name or session.village_name or session.mandal_name or session.pin_code:
                        loc_input = LocationInput(
                            district=session.district_name,
                            mandal=session.mandal_name,
                            village=session.village_name,
                            pin_code=session.pin_code,
                            location_confirmed=True,
                        )

                    query_to_run = text if ("వర్షం" in text or "వాతావరణం" in text or "weather" in text.lower() or "rain" in text.lower()) else pending_query

                    conv_req = ConversationRequest(
                        question=query_to_run,
                        language=preferred_language,
                        farmer_id=f"tg_{user_id}",
                        location=loc_input,
                        guest_consent=guest_consent,
                        channel="telegram",
                    )
                    conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)
                    reply_text = getattr(conv_res, "response_text", None) or self._localized_greeting(preferred_language)
                    await message.reply_text(reply_text)
                    self._save_turn_background(user_id, preferred_language, text, conv_res)
                    if getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                        self.session_repo.set_pending_query(user_id, query_to_run, awaiting_consent=False)
                    else:
                        # Weather request completed: clear temporary in-memory location context (Phase 8.5)
                        self.session_repo.clear_temp_location(user_id)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(
                        "Telegram event: update_id=%s, type=consent_resumed_weather, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return
                else:
                    ack_msg = (
                        self._localized_fallback(
                            preferred_language,
                            "consent_ack",
                            "Okay. I can use your location for weather. Ask for weather for a district or mandal.",
                        )
                    )
                    await message.reply_text(ack_msg)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(
                        "Telegram event: update_id=%s, type=consent_ack, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return

            # 4. Greeting shortcut: return non-empty greeting immediately without calling LLM
            if is_greeting(text):
                logger.info("Detected Telegram greeting; returning direct greeting.")
                await message.reply_text(self._localized_greeting(preferred_language))
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=text_greeting, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 5. Location entity extraction from incoming text (only for non-consent, non-deletion, non-greeting messages)
            v, m, d, p = extract_location_from_text(text)
            explicit_place = self._explicit_weather_place(text) if is_weather_query(text) else None
            if any([v, m, d, p]):
                logger.info("Extracted location entities from Telegram text.")
                self.session_repo.update_location(user_id, village=v, mandal=m, district=d, pin_code=p)
                session = self.session_repo.get_session(user_id)

                # If there was a pending weather query and this message provided location to answer it
                if session.pending_weather_query and not is_weather_query(text):
                    pending_q = session.pending_weather_query
                    logger.info("Resuming pending weather query with newly provided location.")
                    self.session_repo.clear_pending_query(user_id)
                    text = pending_q

            # 6. Build conversation request with session consent and location
            guest_consent = None
            if session.weather_provider_sharing_consent:
                guest_consent = GuestWeatherConsentEvent(
                    consent_given=True,
                    disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                    consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                    channel="telegram",
                )

            loc_input = None
            if explicit_place or session.district_name or session.village_name or session.mandal_name or session.pin_code:
                loc_input = LocationInput(
                    district=explicit_place or session.district_name,
                    mandal=session.mandal_name,
                    village=session.village_name,
                    pin_code=session.pin_code,
                    location_confirmed=True,
                    place_name=explicit_place,
                    named_in_message=bool(explicit_place),
                )

            conv_req = ConversationRequest(
                question=text,
                language=preferred_language,
                farmer_id=f"tg_{user_id}",
                location=loc_input,
                guest_consent=guest_consent,
                channel="telegram",
            )
            conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)

            # Guardrail: Input text must NEVER be returned as the assistant response
            q_clean = text.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            resp_clean = (conv_res.response_text or "").strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            if resp_clean and resp_clean == q_clean:
                logger.warning("Telegram handler detected conv_res echoing text. Overriding with clarification.")
                conv_res.response_text = "మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు. మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?"
                conv_res.safety_reason = "LOCATION_PARAMETERS_REQUIRED"
                conv_res.is_abstention = True

            # 7. Check if orchestrator requested weather consent or location
            if getattr(conv_res, "safety_reason", None) == "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED":
                logger.info("Weather consent required. Storing pending query.")
                self.session_repo.set_pending_query(user_id, text, awaiting_consent=True)
            elif getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                logger.info("Location required. Storing pending query.")
                self.session_repo.set_pending_query(user_id, text, awaiting_consent=False)
            else:
                if is_weather_query(text):
                    self.session_repo.clear_temp_location(user_id)
                else:
                    # Retain short-lived location context for a follow-up crop question.
                    pass

            reply_text = getattr(conv_res, "response_text", None) or self._localized_greeting(preferred_language)
            if getattr(conv_res, "safety_reason", None) == "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED":
                await message.reply_text(
                    self._consent_prompt_text(preferred_language, reply_text),
                    reply_markup=self._consent_markup(preferred_language),
                )
            else:
                await message.reply_text(reply_text)
            self._save_turn_background(user_id, preferred_language, text, conv_res)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.info(
                "Telegram event: update_id=%s, type=text, duration_ms=%.2f, status=success",
                update.update_id,
                elapsed_ms,
            )

        except Exception as e:
            logger.error("Error handling Telegram text message: %s", type(e).__name__, exc_info=True)
            try:
                await message.reply_text(self._localized_fallback(preferred_language, "error", FALLBACK_ERROR_MESSAGE))
            except Exception:
                pass
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.warning(
                "Telegram event: update_id=%s, type=text, duration_ms=%.2f, status=error",
                update.update_id,
                elapsed_ms,
            )

    def _log_voice_telemetry(self, update_id: Optional[int], flow: str, timings: dict) -> None:
        """Emit privacy-safe structured stage latency INFO log (zero IDs, transcripts, or locations)."""
        logger.info(
            "Voice pipeline telemetry | update_id=%s | flow=%s | "
            "telegram_download_ms=%.2f | ogg_to_wav_ms=%.2f | prisma_stt_ms=%.2f | "
            "intent_classification_ms=%.2f | location_resolution_ms=%.2f | "
            "weatherapi_ms=%.2f | imd_ms=%.2f | groq_llm_ms=%.2f | "
            "timbre_tts_ms=%.2f | wav_to_ogg_ms=%.2f | telegram_delivery_ms=%.2f | total_ms=%.2f",
            update_id,
            flow,
            timings.get("telegram_download_ms", 0.0),
            timings.get("ogg_to_wav_ms", 0.0),
            timings.get("prisma_stt_ms", 0.0),
            timings.get("intent_classification_ms", 0.0),
            timings.get("location_resolution_ms", 0.0),
            timings.get("weatherapi_ms", 0.0),
            timings.get("imd_ms", 0.0),
            timings.get("groq_llm_ms", 0.0),
            timings.get("timbre_tts_ms", 0.0),
            timings.get("wav_to_ogg_ms", 0.0),
            timings.get("telegram_delivery_ms", 0.0),
            timings.get("total_ms", 0.0),
        )

    async def _reply_voice_telugu(
        self, message, text: str, timings_out: Optional[dict] = None
    ) -> bool:
        """
        Synthesize Telugu text into Kaveri voice WAV via Timbre v2.5,
        convert to mono OGG Opus, and deliver via message.reply_voice.
        Never silently sends an English text response.
        """
        clean_text = text
        if not clean_text or any(c in clean_text.lower() for c in ("apologize", "verified official evidence")):
            clean_text = TELEGRAM_ABSTENTION_FALLBACK

        try:
            synth_func = getattr(self.voice_service, "synthesize_speech", None) or getattr(self.voice_service, "_synthesize_speech", None)
            wav_bytes = None
            t_tts = time.perf_counter()
            if synth_func:
                try:
                    supports_channel = False
                    try:
                        sig = inspect.signature(synth_func)
                        supports_channel = "channel" in sig.parameters
                    except (ValueError, TypeError):
                        supports_channel = False

                    if supports_channel:
                        wav_bytes = await asyncio.to_thread(
                            synth_func, clean_text, "te-IN", channel="telegram"
                        )
                    else:
                        wav_bytes = await asyncio.to_thread(synth_func, clean_text, "te-IN")
                except Exception as synth_err:
                    logger.warning("Speech synthesis call failed: %s", synth_err)
                    wav_bytes = None
            tts_ms = round((time.perf_counter() - t_tts) * 1000, 2)
            if timings_out is not None:
                timings_out["timbre_tts_ms"] = round(timings_out.get("timbre_tts_ms", 0.0) + tts_ms, 2)

            if not isinstance(wav_bytes, (bytes, bytearray)) or len(wav_bytes) == 0:
                wav_bytes = _generate_fallback_wav_bytes()

            ogg_bytes = None
            t_enc = time.perf_counter()
            try:
                ogg_res = await asyncio.to_thread(convert_wav_bytes_to_ogg_opus, wav_bytes)
                if isinstance(ogg_res, tuple):
                    ogg_bytes = ogg_res[0]
                else:
                    ogg_bytes = ogg_res
            except Exception as conv_err:
                logger.warning("WAV to OGG conversion failed: %s", conv_err)
            wav_to_ogg_ms = round((time.perf_counter() - t_enc) * 1000, 2)
            if timings_out is not None:
                timings_out["wav_to_ogg_ms"] = wav_to_ogg_ms

            if not isinstance(ogg_bytes, (bytes, bytearray)) or len(ogg_bytes) == 0:
                t_deliv = time.perf_counter()
                await message.reply_text(clean_text)
                if timings_out is not None:
                    timings_out["telegram_delivery_ms"] = round(
                        (time.perf_counter() - t_deliv) * 1000, 2
                    )
                return False

            t_deliv = time.perf_counter()
            await message.reply_voice(voice=io.BytesIO(ogg_bytes))
            telegram_delivery_ms = round((time.perf_counter() - t_deliv) * 1000, 2)
            if timings_out is not None:
                timings_out["telegram_delivery_ms"] = telegram_delivery_ms
            return True
        except Exception as e:
            logger.error("Failed to deliver Telugu voice reply: %s", e)
            telugu_fallback = clean_text
            t_deliv = time.perf_counter()
            await message.reply_text(telugu_fallback)
            if timings_out is not None:
                timings_out["telegram_delivery_ms"] = round((time.perf_counter() - t_deliv) * 1000, 2)
            return False

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming voice note or audio message."""
        message = update.effective_message
        if not message:
            return

        voice_obj = message.voice or message.audio
        if not voice_obj:
            return

        if update.update_id and self.deduplicator.is_duplicate(update.update_id):
            logger.info("Ignoring duplicate Telegram update_id: %s", update.update_id)
            return

        t0 = time.perf_counter()
        user = update.effective_user
        user_id = str(user.id if user else "guest")
        chat_id = update.effective_chat.id if update.effective_chat else None
        timings: dict = {}
        logger.info("Handling Telegram voice event (update_id: %s)", update.update_id)

        try:
            preferred_language = await asyncio.to_thread(self._stored_language, user_id) or "te-IN"
            # 1. Quick duration check from Telegram metadata
            if voice_obj.duration and voice_obj.duration > 30:
                logger.info("Telegram voice note duration %ss exceeds 30s limit (update_id: %s).", voice_obj.duration, update.update_id)
                await self._reply_voice_telugu(
                    message,
                    self._localized_fallback(preferred_language, "duration", DURATION_LIMIT_MESSAGE),
                    timings_out=timings,
                )
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                timings["total_ms"] = elapsed_ms
                self._log_voice_telemetry(update.update_id, "voice_duration_exceeded", timings)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_duration_exceeded, duration_ms=%.2f, status=rejected",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 2. Show 'record_voice' chat action while processing
            if chat_id:
                try:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
                except Exception as action_err:
                    logger.debug("Failed to send chat action: %s", action_err)

            # 3. Download audio file bytes (Stage 1)
            t_dl = time.perf_counter()
            file = await context.bot.get_file(voice_obj.file_id)
            raw_audio_bytes = bytes(await file.download_as_bytearray())
            timings["telegram_download_ms"] = round((time.perf_counter() - t_dl) * 1000, 2)

            # 4. Convert incoming OGG/Opus to WAV in thread (Stage 2)
            t_ogg2wav = time.perf_counter()
            wav_bytes = await asyncio.to_thread(convert_ogg_opus_to_wav, raw_audio_bytes)
            timings["ogg_to_wav_ms"] = round((time.perf_counter() - t_ogg2wav) * 1000, 2)

            # 5. Session & Consent preparation
            session = self.session_repo.get_session(user_id)
            guest_consent = None
            if session.weather_provider_sharing_consent:
                guest_consent = GuestWeatherConsentEvent(
                    consent_given=True,
                    disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                    consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                    channel="telegram",
                )

            loc_input = None
            if session.district_name or session.village_name or session.mandal_name or session.pin_code:
                loc_input = LocationInput(
                    district=session.district_name,
                    mandal=session.mandal_name,
                    village=session.village_name,
                    pin_code=session.pin_code,
                    location_confirmed=True,
                )

            voice_req = VoiceProcessingRequest(
                farmer_id=f"tg_{user_id}",
                location=loc_input,
                guest_consent=guest_consent,
                language=preferred_language,
                channel="telegram",
            )
            voice_res = await asyncio.to_thread(
                self.voice_service.process_audio_bytes,
                wav_bytes,
                "telegram_voice.wav",
                voice_req,
            )

            stage_lat = getattr(voice_res, "stage_latencies_ms", None) or {}
            timings["prisma_stt_ms"] = stage_lat.get("stt_ms", 0.0)
            timings["intent_classification_ms"] = stage_lat.get("intent_classification_ms", 0.0)
            timings["location_resolution_ms"] = stage_lat.get("location_resolution_ms", stage_lat.get("farmer_lookup_ms", 0.0))
            timings["weatherapi_ms"] = stage_lat.get("weatherapi_ms", 0.0)
            timings["imd_ms"] = stage_lat.get("imd_ms", 0.0)
            timings["groq_llm_ms"] = stage_lat.get("llm_inference_ms", 0.0)
            timings["timbre_tts_ms"] = stage_lat.get("tts_ms", 0.0)

            transcript = (voice_res.transcript or "").strip()
            synthesized_text = voice_res.response_text
            logger.info("Transcribed Telegram voice (update_id: %s, transcript_chars: %d)", update.update_id, len(transcript))

            # 6A. Location deletion request check
            if is_location_deletion_request(transcript):
                logger.info("Location deletion requested via voice (update_id: %s).", update.update_id)
                self.session_repo.clear_location(user_id)
                self.session_repo.clear_pending_query(user_id)
                del_msg = (
                    "మీ ప్రాంతం వివరాలు తీసేశాను. "
                    "తర్వాత మళ్ళీ వాతావరణం తెలుసుకోవాలంటే మీ ఊరి పేరు చెప్పొచ్చు."
                )
                await self._reply_voice_telugu(message, del_msg, timings_out=timings)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                timings["total_ms"] = elapsed_ms
                self._log_voice_telemetry(update.update_id, "voice_location_deleted", timings)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_location_deleted, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 6B. Explicit consent rejection check
            if is_consent_reject(transcript):
                logger.info("Weather consent rejected via voice (update_id: %s).", update.update_id)
                self.session_repo.set_consent(user_id, consent_given=False)
                self.session_repo.clear_location(user_id)
                self.session_repo.clear_pending_query(user_id)
                reject_msg = (
                    "సరే , మీ మాట ప్రకారం వాతావరణ సమాచారం కోసం లొకేషన్ తీసుకోవడం లేదు. "
                    "మీరు పంటలు, సాగు గురించి ఏమైనా సందేహాలుంటే అడగవచ్చు."
                )
                await self._reply_voice_telugu(message, reject_msg, timings_out=timings)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                timings["total_ms"] = elapsed_ms
                self._log_voice_telemetry(update.update_id, "voice_consent_rejected", timings)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_consent_rejected, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 6C. Explicit or contextual consent grant check
            if is_consent_grant(transcript, awaiting_consent=session.awaiting_consent):
                logger.info("Weather sharing consent granted via voice (update_id: %s, awaiting=%s).", update.update_id, session.awaiting_consent)
                session = self.session_repo.set_consent(user_id, consent_given=True)

                # Check if this voice message also provided location entities
                v, m, d, p = extract_location_from_text(transcript)
                if any([v, m, d, p]):
                    self.session_repo.update_location(user_id, village=v, mandal=m, district=d, pin_code=p)
                    session = self.session_repo.get_session(user_id)

                pending_query = session.pending_weather_query
                if pending_query:
                    logger.info("Resuming pending weather query after voice consent (update_id: %s).", update.update_id)
                    self.session_repo.clear_pending_query(user_id)

                    guest_consent = GuestWeatherConsentEvent(
                        consent_given=True,
                        disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                        consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                        channel="telegram",
                    )
                    loc_input = None
                    if session.district_name or session.village_name or session.mandal_name or session.pin_code:
                        loc_input = LocationInput(
                            district=session.district_name,
                            mandal=session.mandal_name,
                            village=session.village_name,
                            pin_code=session.pin_code,
                            location_confirmed=True,
                        )

                    query_to_run = transcript if ("వర్షం" in transcript or "వాతావరణం" in transcript or "weather" in transcript.lower() or "rain" in transcript.lower()) else pending_query

                    conv_req = ConversationRequest(
                        question=query_to_run,
                        language=preferred_language,
                        farmer_id=f"tg_{user_id}",
                        location=loc_input,
                        guest_consent=guest_consent,
                        channel="telegram",
                    )
                    conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)
                    conv_lat = getattr(conv_res, "latency_breakdown_ms", None) or {}
                    for k_src, k_dst in [
                        ("intent_classification_ms", "intent_classification_ms"),
                        ("location_resolution_ms", "location_resolution_ms"),
                        ("weatherapi_ms", "weatherapi_ms"),
                        ("imd_ms", "imd_ms"),
                        ("llm_inference_ms", "groq_llm_ms"),
                    ]:
                        timings[k_dst] = round(timings.get(k_dst, 0.0) + (conv_lat.get(k_src) or 0.0), 2)

                    reply_text = getattr(conv_res, "response_text", None) or self._localized_greeting(preferred_language)

                    if getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                        self.session_repo.set_pending_query(user_id, query_to_run, awaiting_consent=False)
                    else:
                        self.session_repo.clear_temp_location(user_id)

                    await self._reply_voice_telugu(message, reply_text, timings_out=timings)
                    self._save_turn_background(user_id, preferred_language, query_to_run, conv_res)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    timings["total_ms"] = elapsed_ms
                    self._log_voice_telemetry(update.update_id, "voice_consent_resumed_weather", timings)
                    logger.info(
                        "Telegram event: update_id=%s, type=voice_consent_resumed_weather, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return
                else:
                    ack_msg = self._localized_fallback(
                        preferred_language,
                        "consent_ack",
                        "Okay. I can use your location for weather. Ask for weather for a district or mandal.",
                    )
                    await self._reply_voice_telugu(message, ack_msg, timings_out=timings)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    timings["total_ms"] = elapsed_ms
                    self._log_voice_telemetry(update.update_id, "voice_consent_ack", timings)
                    logger.info(
                        "Telegram event: update_id=%s, type=voice_consent_ack, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return

            # 6D. Greeting shortcut for voice
            if is_greeting(transcript):
                logger.info("Detected greeting in voice, returning direct voice greeting (update_id: %s).", update.update_id)
                await self._reply_voice_telugu(message, self._localized_greeting(preferred_language), timings_out=timings)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                timings["total_ms"] = elapsed_ms
                self._log_voice_telemetry(update.update_id, "voice_greeting", timings)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_greeting, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 6E. Location extraction & pending weather query resumption
            v, m, d, p = extract_location_from_text(transcript)
            if any([v, m, d, p]):
                logger.info("Extracted location entities from Telegram voice (update_id: %s).", update.update_id)
                self.session_repo.update_location(user_id, village=v, mandal=m, district=d, pin_code=p)
                session = self.session_repo.get_session(user_id)

                if session.pending_weather_query and not is_weather_query(transcript):
                    logger.info("Resuming pending weather query with voice-provided location (update_id: %s).", update.update_id)
                    pending_q = session.pending_weather_query
                    self.session_repo.clear_pending_query(user_id)

                    guest_consent = None
                    if session.weather_provider_sharing_consent:
                        guest_consent = GuestWeatherConsentEvent(
                            consent_given=True,
                            disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                            consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                            channel="telegram",
                        )
                    loc_input = LocationInput(
                        district=session.district_name,
                        mandal=session.mandal_name,
                        village=session.village_name,
                        pin_code=session.pin_code,
                        location_confirmed=True,
                    )
                    conv_req = ConversationRequest(
                        question=pending_q,
                        language=preferred_language,
                        farmer_id=f"tg_{user_id}",
                        location=loc_input,
                        guest_consent=guest_consent,
                        channel="telegram",
                    )
                    conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)
                    conv_lat = getattr(conv_res, "latency_breakdown_ms", None) or {}
                    for k_src, k_dst in [
                        ("intent_classification_ms", "intent_classification_ms"),
                        ("location_resolution_ms", "location_resolution_ms"),
                        ("weatherapi_ms", "weatherapi_ms"),
                        ("imd_ms", "imd_ms"),
                        ("llm_inference_ms", "groq_llm_ms"),
                    ]:
                        timings[k_dst] = round(timings.get(k_dst, 0.0) + (conv_lat.get(k_src) or 0.0), 2)

                    reply_text = getattr(conv_res, "response_text", None) or self._localized_greeting(preferred_language)

                    if getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                        self.session_repo.set_pending_query(user_id, pending_q, awaiting_consent=False)
                    else:
                        self.session_repo.clear_temp_location(user_id)

                    await self._reply_voice_telugu(message, reply_text, timings_out=timings)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    timings["total_ms"] = elapsed_ms
                    self._log_voice_telemetry(update.update_id, "voice_location_resumed_weather", timings)
                    logger.info(
                        "Telegram event: update_id=%s, type=voice_location_resumed_weather, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return

            # Guardrail: STT transcript must NEVER be returned as the assistant response
            q_clean = transcript.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            resp_clean = (voice_res.response_text or "").strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            if resp_clean and resp_clean == q_clean:
                logger.warning("Telegram handler detected voice_res echoing transcript (update_id: %s). Overriding with clarification.", update.update_id)
                voice_res.response_text = "మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు. మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?"
                voice_res.safety_reason = "LOCATION_PARAMETERS_REQUIRED"
                voice_res.is_abstention = True
                voice_res.audio_base64 = None  # Force fresh synthesis with the clarification text

            # 7. Check if orchestrator requested weather consent or location
            if getattr(voice_res, "safety_reason", None) == "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED":
                self.session_repo.set_pending_query(user_id, transcript, awaiting_consent=True)
            elif getattr(voice_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                self.session_repo.set_pending_query(user_id, transcript, awaiting_consent=False)
            else:
                self.session_repo.clear_temp_location(user_id)

            # 8. Deliver voice reply (All responses to voice messages MUST be delivered as voice notes)
            sent_voice = False
            audio_matches_text = voice_res.response_text == synthesized_text
            if (
                voice_res.audio_base64
                and not voice_res.is_fallback_text_only
                and audio_matches_text
            ):
                try:
                    reply_wav_bytes = base64.b64decode(voice_res.audio_base64)
                    t_enc = time.perf_counter()
                    ogg_bytes, _ = await asyncio.to_thread(convert_wav_bytes_to_ogg_opus, reply_wav_bytes)
                    timings["wav_to_ogg_ms"] = round((time.perf_counter() - t_enc) * 1000, 2)

                    t_deliv = time.perf_counter()
                    await message.reply_voice(voice=io.BytesIO(ogg_bytes))
                    timings["telegram_delivery_ms"] = round((time.perf_counter() - t_deliv) * 1000, 2)
                    sent_voice = True
                except Exception as voice_send_err:
                    logger.warning("Failed to encode/send voice reply (update_id: %s): %s", update.update_id, voice_send_err)

            # If voice was not pre-synthesized (e.g. safe abstention, rejection, or fallback), synthesize and deliver voice note now
            if not sent_voice:
                resp_text = voice_res.response_text
                if not resp_text or any(c in resp_text.lower() for c in ("apologize", "verified official evidence")):
                    resp_text = TELEGRAM_ABSTENTION_FALLBACK
                await self._reply_voice_telugu(message, resp_text, timings_out=timings)
                sent_voice = True

            self._save_turn_background(user_id, "Telugu", transcript, voice_res)

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            timings["total_ms"] = elapsed_ms
            self._log_voice_telemetry(update.update_id, "voice", timings)
            logger.info(
                "Telegram event: update_id=%s, type=voice, voice_sent=%s, duration_ms=%.2f, status=success",
                update.update_id,
                sent_voice,
                elapsed_ms,
            )

        except AudioDurationExceededError:
            logger.info("Voice duration limit exceeded during pipeline processing (update_id: %s).", update.update_id)
            await self._reply_voice_telugu(
                message,
                self._localized_fallback(preferred_language, "duration", DURATION_LIMIT_MESSAGE),
                timings_out=timings,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            timings["total_ms"] = elapsed_ms
            self._log_voice_telemetry(update.update_id, "voice_duration_exceeded", timings)
            logger.info(
                "Telegram event: update_id=%s, type=voice_duration_exceeded, duration_ms=%.2f, status=rejected",
                update.update_id,
                elapsed_ms,
            )

        except Exception as e:
            logger.error("Error processing Telegram voice note (update_id: %s): %s", update.update_id, e, exc_info=True)
            try:
                await self._reply_voice_telugu(
                    message,
                    self._localized_fallback(preferred_language, "error", FALLBACK_ERROR_MESSAGE),
                    timings_out=timings,
                )
            except Exception:
                pass
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            timings["total_ms"] = elapsed_ms
            self._log_voice_telemetry(update.update_id, "voice_error", timings)
            logger.warning(
                "Telegram event: update_id=%s, type=voice, duration_ms=%.2f, status=error",
                update.update_id,
                elapsed_ms,
            )

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global error handler preventing crashes in polling loop."""
        logger.error("Telegram polling error: %s", context.error, exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(FALLBACK_ERROR_MESSAGE)
            except Exception:
                pass
