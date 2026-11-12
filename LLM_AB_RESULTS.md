# LLM provider comparison

Text-only ConversationOrchestrator comparison; no STT/TTS calls. Weather uses an in-process fixture.

## Groq

### weather-1
- Question: నిజామాబాద్ జిల్లాలో రేపు వాన పడే అవకాశం ఎంత?
- Latency: 1.268 seconds
- Answer length: 137 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
రేపు మీ జిల్లాలో వాన పడే అవకాశం సుమారు నలభై శాతం ఉంది. వాతావరణ రిపోర్ట్ అంచనా మాత్రమే, వాతావరణం మారొచ్చు. ఇంకేమైనా తెలుసుకోవాలంటే అడగండి.
```

### weather-2
- Question: వరంగల్ జిల్లాలో వచ్చే మూడు రోజుల్లో ఉష్ణోగ్రత ఎలా ఉంటుంది?
- Latency: 1.317 seconds
- Answer length: 288 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
వారంగల్‌లో రేపు గరిష్టంగా 31 డిగ్రీల సెల్సియస్, కనిష్టంగా 22 డిగ్రీల సెల్సియస్ ఉంటుంది. తర్వాతి రోజు గరిష్టంగా 32 డిగ్రీల సెల్సియస్, కనిష్టంగా 22 డిగ్రీల సెల్సియస్ ఉంటుంది. మూడవ రోజులో గరిష్టంగా 30 డిగ్రీల సెల్సియస్, కనిష్టంగా 21 డిగ్రీల సెల్సియస్ ఉంటుంది. ఇంకేమైనా తెలుసుకోవాలంటే అడగండి.
```

### crop-1
- Question: యాసంగిలో తక్కువ నీటితో ఏ పంట వేయడం మంచిది?
- Latency: 0.846 seconds
- Answer length: 97 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
మీ యాసంగిలో మట్టీ రకం, నీటి లభ్యత ఎంత ఉందో చెప్పండి, దానికి అనుగుణంగా పంట సిఫార్సు చేస్తాను .
```

### crop-2
- Question: నల్ల నేలలో పత్తి పంటకు ఏ జాగ్రత్తలు తీసుకోవాలి?
- Latency: 1.018 seconds
- Answer length: 86 characters
- Safety status: ABSTAINED
- Abstain: True
- Error class/reason: None
- Answer:
```text
క్షమించండి, మీ ప్రశ్నకు అవసరమైన సమాచారం మా వద్ద లేదు. మరేదైనా సహాయం కావాలంటే చెప్పండి.
```

### scheme-1
- Question: రైతు బంధు పథకం గురించి చెప్పండి.
- Latency: 0.889 seconds
- Answer length: 51 characters
- Safety status: ABSTAINED
- Abstain: True
- Error class/reason: None
- Answer:
```text
క్షమించండి, ఈ విషయం మీద నాకు అధికారిక సమాచారం లేదు.
```

### off-topic-1
- Question: మీరు ఎవరు?
- Latency: 0.796 seconds
- Answer length: 105 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
నేను కృషివాణి, మీకు వ్యవసాయ సలహాలు ఇవ్వడానికి ఇక్కడ ఉన్నాను . మీ పంట లేదా ఇతర ప్రశ్నలు ఉంటే చెప్పండి.
```

### pesticide-1
- Question: పత్తిలో పురుగు మందు ఎంత మోతాదులో కలపాలి?
- Latency: 0.836 seconds
- Answer length: 141 characters
- Safety status: ABSTAINED
- Abstain: True
- Error class/reason: None
- Answer:
```text
పురుగు మందు మోతాదు గురించి ఖచ్చితంగా చెప్పడానికి పంటలో ఏ పురుగు ఉందో తెలుసుకోవాలి, దయచేసి స్థానిక వ్యవసాయ అధికారి లేదా కేవీకేను సంప్రదించండి.
```

### greeting-1
- Question: నమస్తే
- Latency: 0.000 seconds
- Answer length: 90 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
నమస్తే ! నేను మీ కృషీవాణిని. పంటలు లేదా వాతావరణం గురించి ఏమైనా అడగండి, సహాయం చేస్తాను.
```

**Median latency:** 0.867 seconds

## Sarvam

### weather-1
- Question: నిజామాబాద్ జిల్లాలో రేపు వాన పడే అవకాశం ఎంత?
- Latency: 0.810 seconds
- Answer length: 194 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
రేపు మీ ప్రాంతంలో వాతావరణ రిపోర్ట్ ప్రకారం 3.0 మిల్లీమీటర్ల వాన పడే అవకాశం ఉంది, అవకాశం 40 శాతం ఉంది . ఇది కేవలం అంచనా మాత్రమే, మారే అవకాశం ఉంది. దీని గురించి ఇంకేమైనా తెలుసుకోవాలంటే అడగండి.
```

### weather-2
- Question: వరంగల్ జిల్లాలో వచ్చే మూడు రోజుల్లో ఉష్ణోగ్రత ఎలా ఉంటుంది?
- Latency: 1.160 seconds
- Answer length: 394 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
వరంగల్ జిల్లాలో రేపు గరిష్టంగా 31 డిగ్రీల సెల్సియస్ మరియు కనిష్టంగా 22 డిగ్రీల సెల్సియస్ ఉష్ణోగ్రత ఉండే అవకాశం ఉంది. అలాగే ఎల్లుండి 32 డిగ్రీల సెల్సియస్ గరిష్టం మరియు 22 డిగ్రీల సెల్సియస్ కనిష్టం ఉండొచ్చు. మూడో రోజు 30 డిగ్రీల సెల్సియస్ గరిష్టం మరియు 21 డిగ్రీల సెల్సియస్ కనిష్టం అంచనా వేస్తున్నారు. ఈ వాతావరణ రిపోర్ట్ కేవలం అంచనా మాత్రమే, మారొచ్చు. దీని గురించి ఇంకేమైనా తెలుసుకోవాలంటే అడగండి.
```

### crop-1
- Question: యాసంగిలో తక్కువ నీటితో ఏ పంట వేయడం మంచిది?
- Latency: 0.765 seconds
- Answer length: 252 characters
- Safety status: ABSTAINED
- Abstain: True
- Error class/reason: None
- Answer:
```text
యాసంగిలో తక్కువ నీటితో ఏ పంట వేయాలో కచ్చితంగా చెప్పాలంటే మీ లొకేషన్, మట్టి రకం, నీటి వసతి వివరాలు కావాలి . మీరు ఏ ఊరిలో ఉన్నారు, మట్టి ఎలా ఉంది, బోరు నీళ్లా లేక కాలువ నీళ్లా అనేది చెబితే సరైన సూచన ఇవ్వగలను. దీని గురించి ఇంకేమైనా సందేహాలుంటే అడగండి.
```

### crop-2
- Question: నల్ల నేలలో పత్తి పంటకు ఏ జాగ్రత్తలు తీసుకోవాలి?
- Latency: 0.701 seconds
- Answer length: 246 characters
- Safety status: ABSTAINED
- Abstain: True
- Error class/reason: None
- Answer:
```text
నల్ల నేలలో పత్తి పంటకు సరైన సలహా ఇవ్వడానికి మీ ఊరి పేరు లేదా మండలం వివరాలు కావాలండి. అలాగే మీ పొలంలో నేల రకం, నీటి వసతి ఎలా ఉందో చెప్పండి. ఈ వివరాలు తెలిస్తే మీ పరిస్థితికి తగ్గట్టు మంచి సూచనలు చెప్పగలను. దీని గురించి ఇంకేమైనా సందేహాలుంటే అడగండి.
```

### scheme-1
- Question: రైతు బంధు పథకం గురించి చెప్పండి.
- Latency: 0.607 seconds
- Answer length: 204 characters
- Safety status: ABSTAINED
- Abstain: True
- Error class/reason: None
- Answer:
```text
, మీరు అడిగిన రైతు బంధు పథకం వివరాలు మా దగ్గర ఉన్న ఆధారాల్లో లేవు. దీని గురించి కచ్చితమైన సమాచారం కోసం మీ ఏఓ గారిని లేదా దగ్గర్లోని కేవీకే ని సంప్రదించండి. దీని గురించి ఇంకేమైనా తెలుసుకోవాలంటే అడగండి.
```

### off-topic-1
- Question: మీరు ఎవరు?
- Latency: 0.471 seconds
- Answer length: 98 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
నేను కృషివాణి . మీకు వ్యవసాయ విషయాల్లో సహాయం చేయడానికి ఉన్నాను. ఇంకా ఏమైనా సందేహాలుంటే అడగండి.
```

### pesticide-1
- Question: పత్తిలో పురుగు మందు ఎంత మోతాదులో కలపాలి?
- Latency: 1.042 seconds
- Answer length: 189 characters
- Safety status: ABSTAINED
- Abstain: True
- Error class/reason: None
- Answer:
```text
పత్తిలో ఏ పురుగు సోకిందో కచ్చితంగా తెలియకుండా మందు మోతాదు చెప్పలేము . దయచేసి మీ ఊరు లేదా మండలం పేరు చెప్పండి. పురుగును సరిగ్గా గుర్తించాక ఏఓ గారు లేదా కేవీకే ద్వారా సరైన సలహా తీసుకోండి.
```

### greeting-1
- Question: నమస్తే
- Latency: 0.000 seconds
- Answer length: 90 characters
- Safety status: PASSED
- Abstain: False
- Error class/reason: None
- Answer:
```text
నమస్తే ! నేను మీ కృషీవాణిని. పంటలు లేదా వాతావరణం గురించి ఏమైనా అడగండి, సహాయం చేస్తాను.
```

**Median latency:** 0.733 seconds

## Interpretation

The faster provider is the one with the lower median latency above.
Telugu completeness requires human review of the eight answers; character count is not a quality score.
