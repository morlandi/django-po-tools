#!/usr/bin/env python3

# Requirements:
#
# pip install polib
# pip install deep-translator
# pip install anthropic  (optional, for Claude engine)

import os
import re
import json
import argparse
import urllib.request
import urllib.parse
import glob as glob_module
import polib

from deep_translator import GoogleTranslator


def translate_with_mymemory(text, source, target):
    """Fallback translator using the MyMemory free API (no key required)."""
    params = urllib.parse.urlencode({"q": text, "langpair": "%s|%s" % (source, target)})
    url = "https://api.mymemory.translated.net/get?" + params
    with urllib.request.urlopen(url, timeout=10) as response:
        data = json.loads(response.read().decode())
    if data.get("responseStatus") != 200:
        raise Exception("MyMemory error: %s" % data.get("responseDetails", "unknown"))
    return data["responseData"]["translatedText"]


# Matches Python named format strings: %(name)s, %(count)d, %(value).2f, etc.
_PLACEHOLDER_RE = re.compile(r'%\(\w+\)[sdifgre%]|%[sdifgr%]|\{[\w]*\}')

_TRAILING_PUNCT_RE = re.compile(r'([!?.:;,\u2026]+)$')


def strip_trailing_punctuation(text):
    """Remove trailing punctuation and return (stripped_text, punctuation)."""
    m = _TRAILING_PUNCT_RE.search(text)
    if m:
        return text[:m.start()], m.group(1)
    return text, ""


def protect_placeholders(text):
    """
    Replace format-string tokens with neutral tags before translation.
    Returns (protected_text, [original_tokens]).
    E.g. "Refill: %(codes)s" -> ("Refill: @@0@@", ["%(codes)s"])
    """
    tokens = []

    def replacer(m):
        tokens.append(m.group(0))
        return f"@@{len(tokens) - 1}@@"

    protected = _PLACEHOLDER_RE.sub(replacer, text)
    return protected, tokens


def restore_placeholders(text, tokens):
    """Restore the original tokens after translation."""
    for i, token in enumerate(tokens):
        text = text.replace(f"@@{i}@@", token)
    return text


def gather_project_context(project_path, max_chars=6000):
    """
    Scan a Django project to build a context summary for AI translation.

    Reads a limited set of Python source files and HTML templates so the AI
    can understand the application domain, tone, and vocabulary before
    translating.  Returns a plain-text string (may be empty if project_path
    is not set or does not exist).
    """
    if not project_path or not os.path.isdir(project_path):
        return ""

    snippets = []
    total_chars = 0

    # High-level description files first — best context for the AI
    for desc_name in ("CLAUDE.md", "README.md", "README.rst", "README.txt", "README"):
        desc_path = os.path.join(project_path, desc_name)
        if os.path.isfile(desc_path):
            try:
                with open(desc_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read(3000)
                snippets.append("# %s\n%s" % (desc_name, content))
                total_chars += len(snippets[-1])
            except Exception:
                pass
            break

    # Python source files and HTML templates
    scan_patterns = [
        "**/*.py",
        "**/templates/**/*.html",
        "**/templates/**/*.txt",
    ]
    for pattern in scan_patterns:
        if total_chars >= max_chars:
            break
        files = sorted(
            glob_module.glob(os.path.join(project_path, pattern), recursive=True)
        )
        for filepath in files:
            if total_chars >= max_chars:
                break
            # Skip migrations and virtualenv folders
            parts = filepath.replace("\\", "/").split("/")
            if any(p in parts for p in ("migrations", "venv", ".venv", "node_modules", "__pycache__")):
                continue
            try:
                with open(filepath, encoding="utf-8", errors="ignore") as f:
                    content = f.read(600)
                if not content.strip():
                    continue
                rel = os.path.relpath(filepath, project_path)
                snippet = "# %s\n%s" % (rel, content)
                snippets.append(snippet)
                total_chars += len(snippet)
            except Exception:
                continue

    return "\n\n".join(snippets)


def translate_batch_with_claude(texts, source, target, project_context="", api_key=None, model="claude-haiku-4-5-20251001", domain=""):
    """
    Translate a list of strings from *source* to *target* using the Claude API.

    Returns a list of translated strings in the same order as *texts*.
    Raises an ImportError if the 'anthropic' package is not installed.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "The 'anthropic' package is required for the Claude engine.\n"
            "Install it with:  pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)  # falls back to ANTHROPIC_API_KEY env var

    system_lines = [
        "You are a professional software localisation expert.",
        "Translate the user-supplied strings from %s to %s." % (source, target),
    ]
    if domain:
        system_lines += [
            "Application domain: %s." % domain,
            "Use terminology and register appropriate to this domain.",
        ]
    system_lines += [
        "Rules:",
        "- Preserve every format placeholder exactly as-is: %(name)s, {var}, %s, %d, @@0@@ …",
        "- Preserve leading/trailing whitespace and punctuation.",
        "- Keep the same tone and register as the source.",
        "- Do NOT add explanations or comments — output only the translated strings.",
        "- Reply with a JSON array of strings, one per input string, in the same order.",
    ]
    if project_context:
        system_lines += [
            "",
            "Project context (source code excerpts — use this to understand the domain and choose appropriate terminology):",
            project_context,
        ]
    system_prompt = "\n".join(system_lines)

    # Build a numbered list so the model can match inputs to outputs unambiguously
    numbered = "\n".join("[%d] %s" % (i, t) for i, t in enumerate(texts))
    user_message = (
        "Translate each of the following strings. "
        "Reply with a JSON array of %d translated strings.\n\n%s" % (len(texts), numbered)
    )

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()

    # Extract JSON array from the response (the model may wrap it in markdown fences)
    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not json_match:
        raise ValueError("Claude returned an unexpected response (no JSON array found):\n%s" % raw)
    translations = json.loads(json_match.group(0))

    if len(translations) != len(texts):
        raise ValueError(
            "Claude returned %d translations for %d inputs." % (len(translations), len(texts))
        )
    return translations


def get_language_from_filepath(filepath):
    """
    Esempio: 'backend/locale/zh_hans/LC_MESSAGES/django.po' --> 'zh_hans'
    """
    parts = filepath.split(os.sep)
    idx = parts.index("locale")
    lang = parts[idx + 1]
    assert parts[idx+2]=='LC_MESSAGES', 'missing "LC_MESSAGES" in %s' % filepath
    return lang


def translate_po_file(
    filepath,
    source_language="en",
    fuzzy=False,
    dry_run=False,
    engine="google",
    project_path=None,
    project_context=None,
    api_key=None,
    batch_size=500,
    model="claude-haiku-4-5-20251001",
    domain="",
):
    """
    Auto-translate untranslated entries in a .po file.

    :param filepath: path to the .po file
    :param source_language: source language code (default: "en")
    :param fuzzy: if True, mark new translations as fuzzy
    :param dry_run: if True, do not save changes
    :param engine: translation engine — "google" (default) or "claude"
    :param project_path: root of the Django project; source files are scanned
                         to build context for the AI engine (default: cwd)
    :param project_context: pre-built context string (if provided, project_path scan is skipped)
    :param api_key: Anthropic API key (falls back to ANTHROPIC_API_KEY env var)
    :param batch_size: number of strings sent to Claude per API call (default: 500)
    :param model: Anthropic model to use (default: claude-haiku-4-5-20251001)
    :param domain: application domain description (e.g. "paint dosing systems for the construction industry")
    """
    if project_path is None:
        project_path = os.getcwd()
    target = get_language_from_filepath(filepath)
    if target in ['zh-hans', 'zh_hans', 'zh', 'zh_CN', 'zh-CN', 'zh-simplified']:
        target = "zh-cn"
    if target in ['zh-hant', 'zh_hant', 'zh_TW', 'zh-TW', 'zh-traditional']:
        target = "zh-tw"

    po = polib.pofile(filepath)
    print("Numero di voci:", len(po))
    print("Header Project-Id-Version:", po.metadata.get("Project-Id-Version"))
    untranslated = [entry for entry in po if not entry.msgstr]
    total = len(untranslated)
    print("Voci da tradurre: %d" % total)

    if total == 0:
        print('\n0 messages have been translated')
        return

    n = 0
    errors = []

    if engine == "claude":
        # ------------------------------------------------------------------ #
        # Claude engine: batch all strings and translate in one (or few) call #
        # ------------------------------------------------------------------ #
        print("Engine: Claude (Anthropic)")
        if project_context is None:
            print("Gathering project context from: %s" % project_path)
            project_context = gather_project_context(project_path)
            print("Context gathered: %d chars" % len(project_context))
        else:
            print("Using pre-built project context (%d chars)" % len(project_context))

        # Process in batches
        for batch_start in range(0, total, batch_size):
            batch_entries = untranslated[batch_start: batch_start + batch_size]

            # Protect placeholders for each entry
            protected_batch = []
            meta_batch = []  # (tokens, trailing_punct) per entry
            for entry in batch_entries:
                stripped, trailing_punct = strip_trailing_punctuation(entry.msgid)
                protected, tokens = protect_placeholders(stripped)
                protected_batch.append(protected)
                meta_batch.append((tokens, trailing_punct))

            batch_end = min(batch_start + batch_size, total)
            print(
                "\nTranslating batch [%d-%d] of %d with Claude ..."
                % (batch_start + 1, batch_end, total)
            )
            for i, entry in enumerate(batch_entries):
                print('  [%d/%d] "%s"' % (batch_start + i + 1, total, entry.msgid))

            try:
                translations = translate_batch_with_claude(
                    protected_batch, source_language, target,
                    project_context=project_context,
                    api_key=api_key,
                    model=model,
                    domain=domain,
                )
                for i, (entry, translation_raw) in enumerate(zip(batch_entries, translations)):
                    tokens, trailing_punct = meta_batch[i]
                    translation = restore_placeholders(str(translation_raw), tokens) + trailing_punct
                    print('  [%d/%d] --> "%s"' % (batch_start + i + 1, total, translation))
                    if not dry_run:
                        entry.msgstr = translation
                        if fuzzy:
                            entry.flags.append("fuzzy")
                    n += 1
            except Exception as e:
                print('ERRORE nel batch [%d-%d]: %s' % (batch_start + 1, batch_end, str(e)))
                for entry in batch_entries:
                    errors.append((entry.linenum, entry.msgid, str(e)))

    else:
        # ------------------------------------------------------------------ #
        # Google Translate engine (original behaviour)                        #
        # ------------------------------------------------------------------ #
        print("Engine: Google Translate")
        for entry in untranslated:
            try:
                pct = int(100 * n / total) if total else 100
                print('[%d/%d] (%d%%) msgid:  "%s"' % (n + 1, total, pct, entry.msgid))
                stripped, trailing_punct = strip_trailing_punctuation(entry.msgid)
                protected, tokens = protect_placeholders(stripped)
                try:
                    translated = GoogleTranslator(source=source_language, target=target).translate(protected)
                except Exception as e_google:
                    print('  Google failed (%s), trying MyMemory ...' % str(e_google))
                    translated = translate_with_mymemory(protected, source_language, target)
                translation = restore_placeholders(translated, tokens) + trailing_punct
                print('[%d/%d] (%d%%) msgstr: "%s"' % (n + 1, total, pct, translation))
                if not dry_run:
                    entry.msgstr = translation
                    if fuzzy:
                        entry.flags.append("fuzzy")
                n += 1
            except Exception as e:
                print('ERRORE: %s' % str(e))
                errors.append((entry.linenum, entry.msgid, str(e)))

    print('\n%d messages have been translated' % n)
    if errors:
        rel_filepath = os.path.relpath(filepath)
        print('\n%d untranslated message(s):' % len(errors))
        for linenum, msgid, msg in errors:
            print('  [%d] "%s"' % (linenum, msgid))
        print('\nedit with:')
        for linenum, msgid, msg in errors:
            print('  vim +%d "%s"' % (linenum, rel_filepath))
        if len(errors) > 1:
            all_cmds = "; ".join('vim +%d "%s"' % (linenum, rel_filepath) for linenum, msgid, msg in errors)
            print('\nor all at once:')
            print('  ' + all_cmds)
    if n > 0 and not dry_run:
        print('Saving file "%s" ...' % filepath)
        po.save(filepath)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pofile",
        help="path of po file to be auto translated"
    )
    parser.add_argument(
        "--source-language",
        default="en",
        help="Default: en",
    )
    parser.add_argument(
        "-f",
        "--fuzzy",
        action="store_true",
        default=False,
        help="Set fuzzy flag for new translations",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        default=False,
        help="Don't execute commands, just pretend. (default: False)",
    )
    parser.add_argument(
        "--engine",
        choices=["google", "claude"],
        default="google",
        help="Translation engine: 'google' (default) or 'claude' (requires anthropic package and ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--domain",
        default="",
        help="Application domain description used by Claude to choose appropriate terminology "
             "(e.g. 'paint dosing systems for the construction industry')",
    )
    parser.add_argument(
        "--project-path",
        default=None,
        help="Root of the Django project; source files are scanned to build context for the Claude engine (default: current directory)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (overrides ANTHROPIC_API_KEY env var, Claude engine only)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of strings per Claude API call (default: 500, Claude engine only)",
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model to use (default: claude-haiku-4-5-20251001, Claude engine only)",
    )
    parsed = parser.parse_args()

    translate_po_file(
        filepath=parsed.pofile,
        source_language=parsed.source_language,
        fuzzy=parsed.fuzzy,
        dry_run=parsed.dry_run,
        engine=parsed.engine,
        domain=parsed.domain,
        project_path=parsed.project_path,
        api_key=parsed.api_key,
        batch_size=parsed.batch_size,
        model=parsed.model,
    )


if __name__ == "__main__":
    main()
