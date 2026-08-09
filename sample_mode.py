"""Sample Mode helpers: three safe localization variants and prospect-ready assets."""
from pathlib import Path
import json, html, re, subprocess

VARIANTS = ("brand_match", "performance", "premium")
VARIANT_LABELS = {"brand_match":"Brand Match", "performance":"Performance", "premium":"Premium"}
VARIANT_PROMPT = '''You are a native {language} advertising copywriter. Return ONLY valid JSON with keys brand_match, performance, premium. Each value must be an object with keys script, sentence_changes (array of objects with original, localized, reason), cultural_adaptations (array), cta_recommendations (array), alternative_hooks (array), alternative_headlines (array), alternative_ctas (array), compliance_notes (array), confidence (number 0-1). Create three genuinely distinct versions: brand_match preserves voice; performance uses punchier conversion-focused language; premium is elevated and sophisticated. Preserve every factual claim exactly; never add or strengthen claims, medical efficacy, testing, guarantees, numbers, endorsements, or certifications not present in the source. Flag claims in compliance_notes as unverified rather than inventing them. Preserve brand/product names. Localize naturally for {language}.

SOURCE SCRIPT:
{source}'''

MIN_CONFIDENCE = 0.75

def validate_variants(variants, source, target_lang):
    """Return per-variant validation errors; never infer language from mere text difference."""
    errors = {}
    target = target_lang.lower().split('-')[0]
    words = {
        'es': {'el','la','los','las','de','que','para','con','una','hoy','envío','zapatillas'},
        'fr': {'le','la','les','des','de','pour','avec','une','aujourd','livraison','chaussures'},
        'de': {'der','die','das','den','und','für','mit','eine','heute','versand','schuhe'},
    }.get(target, set())
    english = {'the','and','our','new','for','with','today','get','free','shipping','tired','ordinary','running','shoes','order'}
    for key in VARIANTS:
        v = variants.get(key) if isinstance(variants, dict) else None
        script = str((v or {}).get('script','')).strip()
        problems = []
        if not script: problems.append('empty localized script')
        if target != 'en' and re.sub(r'\W','',script.lower()) == re.sub(r'\W','',source.lower()):
            problems.append('localized script is identical to source')
        if target in {'es','fr','de'} and re.search(r'[\u0400-\u04ff]', script):
            problems.append('Cyrillic contamination in Latin-script target')
        tokens = set(re.findall(r"[A-Za-zÀ-ÿ]+", script.lower()))
        if target != 'en' and len(tokens & english) >= 3 and len(tokens & words) == 0:
            problems.append('significant English passthrough')
        if target in {'es','fr','de'} and len(tokens & words) == 0:
            problems.append(f'no recognizable {target} vocabulary')
        try: confidence = float((v or {}).get('confidence', 0))
        except (TypeError, ValueError): confidence = 0
        if confidence < MIN_CONFIDENCE: problems.append(f'confidence below {MIN_CONFIDENCE}')
        if problems: errors[key] = problems
    return errors

class LocalizationUnavailable(RuntimeError):
    """Raised when no provider produces validated localization."""


def _fallback(source, language):
    # Kept for callers that explicitly need a safe preview, but never used as success.
    return {k:{"script":source, "sentence_changes":[{"original":source,"localized":source,"reason":"Fallback preserves source wording because no localization provider was available."}],"cultural_adaptations":[],"cta_recommendations":["Validate the CTA with a native-market reviewer."],"alternative_hooks":[],"alternative_headlines":[],"alternative_ctas":[],"compliance_notes":["No new claims were introduced. Verify all source claims before publication."],"confidence":0.35} for k in VARIANTS}

def _parse(text, source, language):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.I|re.M).strip()
    try: data=json.loads(text)
    except Exception:
        m=re.search(r"\{.*\}", text, re.S)
        try: data=json.loads(m.group(0)) if m else None
        except Exception: data=None
    if not isinstance(data,dict) or not all(k in data for k in VARIANTS): return _fallback(source,language)
    out={}
    for k in VARIANTS:
        v=data[k] if isinstance(data[k],dict) else {}
        out[k]={"script":str(v.get("script",source)),"sentence_changes":v.get("sentence_changes",[]),"cultural_adaptations":v.get("cultural_adaptations",[]),"cta_recommendations":v.get("cta_recommendations",[]),"alternative_hooks":v.get("alternative_hooks",[]),"alternative_headlines":v.get("alternative_headlines",[]),"alternative_ctas":v.get("alternative_ctas",[]),"compliance_notes":v.get("compliance_notes",[]),"confidence":v.get("confidence",0.5)}
    return out

def _localize_with_xkiro(prompt):
    """OpenAI-compatible fallback via xKiro, retrying once on a backup model."""
    import os
    from openai import OpenAI
    key = os.getenv("XKIRO_API_KEY")
    if not key:
        raise RuntimeError("XKIRO_API_KEY is not configured")
    primary = os.getenv("XKIRO_MODEL", "minimax/minimax-m2.1")
    backup = os.getenv("XKIRO_BACKUP_MODEL", "mistralai/ministral-3b")
    models = [primary] + ([backup] if backup != primary else [])
    client = OpenAI(api_key=key, base_url=os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1"), timeout=45, max_retries=0)
    last_error = None
    for model in models:
        try:
            r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=0.7)
            return r.choices[0].message.content
        except Exception as e:
            last_error = e
    raise last_error


def localize_variants(source, target_lang, provider="auto"):
    language = {"de":"German","es":"Spanish","fr":"French","en":"English"}.get(target_lang,target_lang)
    prompt=VARIANT_PROMPT.format(language=language,source=source)
    attempts = []
    if provider in ("gemini","auto") and __import__('os').getenv("GEMINI_API_KEY"):
        attempts.append(("gemini", _localize_with_gemini, prompt))
    if provider in ("xkiro","auto") and __import__('os').getenv("XKIRO_API_KEY"):
        attempts.append(("xkiro", _localize_with_xkiro, prompt))
    if provider in ("openai","auto") and __import__('os').getenv("OPENAI_API_KEY"):
        attempts.append(("openai", _localize_with_openai, prompt))
    provider_errors = []
    for name, fn, p in attempts:
        try:
            variants = _parse(fn(p), source, language)
            validation = validate_variants(variants, source, target_lang)
            if validation:
                raise LocalizationUnavailable(f"{name} output failed validation: {json.dumps(validation)}")
            return variants
        except Exception as e:
            provider_errors.append(f"{name}: {e}")
            print(f"[SAMPLE] {name} failed: {e}")
    if not attempts:
        provider_errors.append("no configured localization provider")
    raise LocalizationUnavailable("; ".join(provider_errors))


def _localize_with_gemini(prompt):
    import google.generativeai as genai, os
    genai.configure(api_key=os.getenv("GEMINI_API_KEY")); model=genai.GenerativeModel(os.getenv("GEMINI_MODEL","gemini-2.0-flash"))
    return model.generate_content(prompt, request_options={"timeout":45}).text


def _localize_with_openai(prompt):
    from openai import OpenAI
    r=OpenAI().chat.completions.create(model="gpt-4o",messages=[{"role":"user","content":prompt}],temperature=.7,response_format={"type":"json_object"})
    return r.choices[0].message.content

def _items(value):
    return "\n".join(f"<li>{html.escape(str(x))}</li>" for x in (value or [])) or "<li>None supplied</li>"

def write_report(out, source, variants, language):
    sections=[]
    for key in VARIANTS:
        v=variants[key]; changes=v.get("sentence_changes",[])
        rows="".join(f"<tr><td>{html.escape(str(c.get('original','')))}</td><td>{html.escape(str(c.get('localized','')))}</td><td>{html.escape(str(c.get('reason','')))}</td></tr>" for c in changes if isinstance(c,dict))
        sections.append(f"<section><h2>{VARIANT_LABELS[key]}</h2><h3>Localized script</h3><pre>{html.escape(v['script'])}</pre><h3>Sentence-level rationale</h3><table><tr><th>Original</th><th>Localized</th><th>Why it changed</th></tr>{rows}</table><h3>Cultural adaptations</h3><ul>{_items(v.get('cultural_adaptations'))}</ul><h3>CTA recommendations</h3><ul>{_items(v.get('cta_recommendations'))}</ul><h3>Alternatives</h3><b>Hooks/headlines/CTAs</b><ul>{_items(v.get('alternative_hooks'))}{_items(v.get('alternative_headlines'))}{_items(v.get('alternative_ctas'))}</ul><h3>Compliance</h3><ul>{_items(v.get('compliance_notes'))}</ul><p><b>Confidence:</b> {float(v.get('confidence',0))*100:.0f}%</p></section>")
    doc=f"<!doctype html><html><head><meta charset='utf-8'><title>Pindola Localization Report</title><style>body{{font:15px Arial;max-width:1000px;margin:40px auto;color:#20202a}}h1{{color:#6d3bb5}}section{{border-top:3px solid #ddd;margin-top:30px;padding-top:15px}}pre{{white-space:pre-wrap;background:#f5f3f8;padding:15px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}th{{background:#eee}}</style></head><body><h1>PINDOLA Localization Report</h1><p><b>Target:</b> {html.escape(language)}</p><h2>Original script</h2><pre>{html.escape(source)}</pre>{''.join(sections)}<footer><p>Human review required before publication. Claims are not independently verified.</p></footer></body></html>"
    path=out/"localization_report.html"; path.write_text(doc,encoding="utf-8"); return path

def apply_watermark(src,dst):
    subprocess.run(["ffmpeg","-y","-i",str(src),"-vf","drawtext=text='PINDOLA SAMPLE':fontcolor=white@0.45:fontsize=42:x=(w-text_w)/2:y=h-100","-c:a","copy",str(dst)],capture_output=True,check=True)

def make_side_by_side(original, localized, output):
    subprocess.run(["ffmpeg","-y","-i",str(original),"-i",str(localized),"-filter_complex","[0:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2[l];[1:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2[r];[l][r]hstack=inputs=2[v]","-map","[v]","-map","1:a?","-shortest","-c:v","libx264","-c:a","aac",str(output)],capture_output=True,check=True)
