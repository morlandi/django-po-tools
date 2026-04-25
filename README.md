# django-po-tools

Command-line tools to manage Django translation files (`.po`/`.mo`) and auto-translate them using Google Translate.

## Installation

```bash
pip install django-po-tools
```

## Commands

Two commands are installed in the virtualenv:

- **`djmessages`** — orchestrates `makemessages`, `compilemessages`, collect/install/remove workflows across multiple Django apps
- **`po-auto-translate`** — auto-translates untranslated entries in a single `.po` file using Google Translate (with MyMemory as fallback)

---

## `djmessages`

Run from the root of your Django project (where `manage.py` lives).

### Configuration

On first run, `djmessages` creates a `djmessages.conf` file in the current directory and exits. Edit it before running again:

```ini
[general]
project=myproject
settings_module=myproject.settings
translations_target_folder=../translations
apps=app1, app2
```

| Key | Description |
|-----|-------------|
| `project` | Django project name |
| `settings_module` | Dotted path to your Django settings module |
| `translations_target_folder` | Folder used by `collect` / `install` commands |
| `apps` | Comma-separated list of Django app names |

Available languages are read automatically from `LANGUAGES` in your Django settings (excluding the default `LANGUAGE_CODE`).

### Usage

```
djmessages <command> [-a <app> [app ...]] [-l <lang> [lang ...]]
```

If `-a` or `-l` are omitted, all configured apps or languages are used.

### Commands

| Command | Description |
|---------|-------------|
| `make` | Run `makemessages` — extract translatable strings and create/update `.po` files |
| `compile` | Run `compilemessages` — compile `.po` files into binary `.mo` files |
| `collect` | Copy `.po` files into `translations_target_folder` for external translation |
| `install` | Copy `.po` files back from `translations_target_folder` into each app's `locale/` |
| `remove` | Delete the `locale/<lang>/` folder for the given apps |
| `autotranslate` | Auto-translate untranslated entries in `.po` files (calls `po-auto-translate`) |

### Options

```
-a, --apps       One or more app names, or "all"
-l, --languages  One or more language codes, or "all"
-f, --fuzzy      Mark new auto-translations as fuzzy
-d, --dry-run    Print commands without executing them
-v, --verbosity  Verbosity level (0-3, default 2)
```

### Examples

```bash
# Extract strings for Italian and Spanish in two apps
djmessages make -a frontend main -l it es

# Compile all languages for all apps (options omitted = all)
djmessages compile

# Auto-translate missing strings in one app, mark as fuzzy for review
djmessages autotranslate -a frontend -l it es --fuzzy

# Dry-run: see what collect would do without touching files
djmessages collect --dry-run
```

---

## `po-auto-translate`

Translates all untranslated entries in a single `.po` file. The target language is inferred from the file path (`.../locale/<lang>/LC_MESSAGES/django.po`).

```bash
po-auto-translate path/to/locale/it/LC_MESSAGES/django.po
```

### Options

```
--source-language  Source language code (default: en)
-f, --fuzzy        Mark new translations as fuzzy
-d, --dry-run      Translate and print results without saving
```

### Translation backends

1. **Google Translate** (`googletrans`) — primary
2. **MyMemory** (free REST API, no key required) — automatic fallback if Google fails

Format-string placeholders (`%(name)s`, `{var}`, etc.) are protected before translation and restored afterwards.

---

## `collect` / `install` workflow

Useful when translations are done externally (e.g. by a translation agency):

```
myapp/locale/it/LC_MESSAGES/django.po
    → collect →
translations/it/it_myapp.po        ← send to translator
    → install →
myapp/locale/it/LC_MESSAGES/django.po
```

The `collect` command copies `.po` files into a flat, language-grouped folder. The `install` command is the reverse: it copies them back into the correct `locale/` paths and removes stale `.mo` files.

---

## License

GPL — Copyright (c) 2016-2026, Brainstorm S.r.l.
