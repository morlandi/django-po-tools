#!/usr/bin/env python3

# Requirements:
#
# pip install polib
# pip install googletrans==4.0.0-rc1  (versione sincrona)

import os
import re
import json
import argparse
import urllib.request
import urllib.parse
import polib

# https://py-googletrans.readthedocs.io/en/latest/
from googletrans import Translator


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


def get_language_from_filepath(filepath):
    """
    Esempio: 'backend/locale/zh_hans/LC_MESSAGES/django.po' --> 'zh_hans'
    """
    parts = filepath.split(os.sep)
    idx = parts.index("locale")
    lang = parts[idx + 1]
    assert parts[idx+2]=='LC_MESSAGES', 'missing "LC_MESSAGES" in %s' % filepath
    return lang


def translate_po_file(filepath, source_language="en", fuzzy=False, dry_run=False):
    """
    Auto-translate untranslated entries in a .po file.

    :param filepath: path to the .po file
    :param source_language: source language code (default: "en")
    :param fuzzy: if True, mark new translations as fuzzy
    :param dry_run: if True, do not save changes
    """
    target = get_language_from_filepath(filepath)
    if target in ['zh-hans', 'zh_hans', 'zh']:
        target = "zh-cn"
    if target in ['zh-hant', 'zh_hant']:
        target = "zh-tw"

    translator = Translator()

    po = polib.pofile(filepath)
    print("Numero di voci:", len(po))
    print("Header Project-Id-Version:", po.metadata.get("Project-Id-Version"))
    untranslated = [entry for entry in po if not entry.msgstr]
    total = len(untranslated)
    print("Voci da tradurre: %d" % total)
    n = 0
    errors = []
    for entry in untranslated:
        try:
            pct = int(100 * n / total) if total else 100
            print('[%d/%d] (%d%%) msgid:  "%s"' % (n + 1, total, pct, entry.msgid))
            stripped, trailing_punct = strip_trailing_punctuation(entry.msgid)
            protected, tokens = protect_placeholders(stripped)
            try:
                result = translator.translate(protected, src=source_language, dest=target)
                translated = result.text
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
    parsed = parser.parse_args()

    translate_po_file(
        filepath=parsed.pofile,
        source_language=parsed.source_language,
        fuzzy=parsed.fuzzy,
        dry_run=parsed.dry_run,
    )


if __name__ == "__main__":
    main()
