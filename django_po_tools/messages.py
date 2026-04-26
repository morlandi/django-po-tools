#!/usr/bin/env python

"""
Utility script to manage messages in Django
(c) 2016 Mario Orlandi, Brainstorm S.r.l.
"""

__author__ = "Mario Orlandi"
__copyright__ = "Copyright (c) 2016-2026, Brainstorm S.r.l."
__license__ = "GPL"

import argparse
import importlib
import os
import shutil
import sys
import configparser

from django_po_tools.po_auto_translate import translate_po_file, gather_project_context

DRY_RUN = False

CONFIG_FILENAME = "djmessages.conf"


def run_command(command):
    if DRY_RUN:
        print("\x1b[1;37;40m# " + command + "\x1b[0m")
    else:
        print("\x1b[1;37;40m" + command + "\x1b[0m")
        rc = os.system(command)
        if rc != 0:
            raise Exception(command)


def assure_path_exists(path):
    if not os.path.exists(path):
        if DRY_RUN:
            print("\x1b[1;37;40m# os.makedirs(" + path + ")\x1b[0m")
        else:
            print("\x1b[1;37;40m os.makedirs(" + path + ")\x1b[0m")
            os.makedirs(path)


def fail(message):
    print("ERROR: " + message)
    exit(-1)


def read_config_file():
    """
    Parse the config file if exists;
    otherwise, create a default config file and exit.
    The config file is always looked up as ./messages.conf in the current working directory.
    """

    def create_default_config_file(config_filename):
        default_config = """
[general]
project={project}
settings_module={project}.settings
translations_target_folder=../translations
apps=app1, app2

[autotranslate]
# Translation engine: google (default) or claude
engine=google
# Application domain — used by Claude to choose appropriate terminology
# Example: paint dosing systems for the construction industry
domain=
# Anthropic API key (can also be set via ANTHROPIC_API_KEY environment variable)
anthropic_api_key=
"""
        cwd = os.getcwd()
        project = os.path.split(cwd)[-1]
        text = default_config.format(project=project)
        with open(config_filename, "w") as configfile:
            configfile.write(text)

    config_filename = os.path.join(os.getcwd(), CONFIG_FILENAME)
    config = configparser.ConfigParser()
    success = len(config.read(config_filename)) > 0
    if success:
        print('Using config file "%s"' % config_filename)
    else:
        print('Creating default config file "%s" ...' % config_filename)
        create_default_config_file(config_filename)
        print(
            'Default config file "%s" has been created; please check it before running this script again'
            % config_filename
        )
        exit(-1)

    return config


def normalize_language(language):
    code = language
    if "-" in language:
        code = language[: language.find("-")]
    return code


def list_available_languages(settings_module):
    # Given:
    #
    #   LANGUAGE_CODE = 'en-us'
    #   LANGUAGES = [
    #       ('en', 'English'),
    #       ('it', 'Italiano'),
    #       ('es', 'Spanish'),
    #       ("zh-hans", "Chinese"),
    #   ]
    #
    # Then:
    #
    #   ['it', 'es', 'zh']

    def code_prefix(code):
        if "-" in code:
            code = code[: code.find("-")]
        return code

    settings = importlib.import_module(settings_module)
    default_language_code = code_prefix(settings.LANGUAGE_CODE)
    languages = [
        normalize_language(code)
        for code, description in settings.LANGUAGES
        if code_prefix(code) != default_language_code
    ]
    return languages


def get_app_path(app):
    module = importlib.import_module(app)
    app_path = os.path.dirname(module.__file__)
    return app_path


def do_makemessages(apps, languages):
    manage_py = os.path.join(os.getcwd(), "manage.py")
    for app in apps:
        app_path = get_app_path(app)
        for language in languages:
            assure_path_exists(os.path.join(app_path, "locale", language))
        command = 'cd %s && python %s makemessages --extension "html,txt,py,js" %s' % (
            app_path,
            manage_py,
            " ".join(["-l %s" % language for language in languages]),
        )
        run_command(command)


def do_auto_translatemessages(apps, languages, fuzzy, engine="google", project_path=None, api_key=None, batch_size=500, model="claude-haiku-4-5-20251001", domain=""):
    # Gather project context once for all apps/languages (Claude engine only)
    project_context = None
    if engine == "claude" and not DRY_RUN:
        if project_path is None:
            project_path = os.getcwd()
        print("Gathering project context from: %s" % project_path)
        project_context = gather_project_context(project_path)
        print("Context gathered: %d chars" % len(project_context))

    for app in apps:
        app_path = get_app_path(app)
        for language in languages:
            po_file = os.path.join(app_path, "locale", language, "LC_MESSAGES", "django.po")
            po_file = os.path.normpath(po_file)
            engine_info = " --engine %s" % engine if engine != "google" else ""
            print("\x1b[1;37;40mpo-auto-translate %s%s%s\x1b[0m" % (
                po_file, " --fuzzy" if fuzzy else "", engine_info
            ))
            if not DRY_RUN:
                translate_po_file(
                    po_file,
                    fuzzy=fuzzy,
                    engine=engine,
                    project_path=project_path,
                    project_context=project_context,
                    api_key=api_key,
                    batch_size=batch_size,
                    model=model,
                    domain=domain,
                )


def do_compilemessages(apps, languages):
    manage_py = os.path.join(os.getcwd(), "manage.py")
    for app in apps:
        app_path = get_app_path(app)
        command = "cd %s && python %s compilemessages %s" % (
            app_path,
            manage_py,
            " ".join(["-l %s" % language for language in languages]),
        )
        run_command(command)


def do_collectmessages(apps, languages, target_folder):
    if not os.path.isdir(target_folder):
        raise Exception('Folder "%s" not found' % target_folder)

    print("Collecting translation files ...")
    for language in languages:
        print("Language: %s" % language)
        for app in apps:
            app_path = get_app_path(app)

            #
            # Collect po file as follows:
            #     MYAPP/locale/LANGUAGE/LC_MESSAGES/django.po --> ./translations/LANGUAGE/LANGUAGE_MYAPP.po
            #
            # in order to:
            #   1) remember both source language and app name in "django.po" copy
            #   2) collect all copies in a specific language folder under "translations"
            #
            # If app is kept in a subfolder, replace each "/" with "~" to obtain a flat filename:
            #     FOLDER/MYAPP/locale/LANGUAGE/LC_MESSAGES/django.po --> ./translations/LANGUAGE/LANGUAGE_FOLDER~MYAPP.po
            #

            assure_path_exists(os.path.join(target_folder, language))
            source_path = os.path.join(
                app_path, "locale", language, "LC_MESSAGES", "django.po"
            )
            target_file = "%s_%s.po" % (language, app.replace("/", "~"))
            target_path = os.path.join(target_folder, language, target_file)

            if os.path.isfile(source_path):
                try:
                    command = "cp %s %s" % (source_path, target_path)
                    run_command(command)
                    message = "[ok]"
                except:
                    message = "[NOT FOUND]"
            else:
                message = "[NOT FOUND]"
            print("    %-12.12s %s" % (message, target_path))


def do_removemessages(apps, languages):
    for app in apps:
        app_path = get_app_path(app)
        for language in languages:
            folder = os.path.join(app_path, "locale", language)
            folder = os.path.normpath(folder)
            if os.path.isdir(folder):
                if DRY_RUN:
                    print("\x1b[1;37;40m# shutil.rmtree(%s)\x1b[0m" % folder)
                else:
                    print("\x1b[1;37;40m shutil.rmtree(%s)\x1b[0m" % folder)
                    shutil.rmtree(folder)
            else:
                print("Folder not found (skipped): %s" % folder)


def do_installmessages(apps, languages, source_folder):
    def find_candidate(base_folder, candidates, extension):
        for candidate in candidates:
            filename = os.path.join(base_folder, candidate + "." + extension)
            if os.path.isfile(filename):
                return filename
        return ""

    if not os.path.isdir(source_folder):
        raise Exception('Folder "%s" not found' % source_folder)

    print("Installing translation files ...")
    for language in languages:
        print("Language: %s" % language)
        for app in apps:
            app_path = get_app_path(app)

            #
            # Do the reverse of "collect" command; that is:
            #
            #   1) search source file in "translations" folder, accepting either:
            #       - 'translations/LANGUAGE/LANGUAGE_MYAPP.po',
            #       - 'translations/LANGUAGE/MYAPP.po',
            #       - 'translations/LANGUAGE_MYAPP.po'
            #
            #   2) copy source file onto:
            #       - 'MYAPP/locale/LANGUAGE/LC_MESSAGES/django.po'
            #
            #   3) also, eventually remove the obsolete compiled translation file
            #       - 'MYAPP/locale/LANGUAGE/LC_MESSAGES/django.mo'
            #
            # Note that when the app is kept in a subfolder, we'll need to replace
            # "~" in source filename back to "/"
            #

            candidates = [
                os.path.join(language, language + "_" + app.replace("/", "~")),
                os.path.join(language, app.replace("/", "~")),
                language + "_" + app.replace("/", "~"),
            ]

            source_path = find_candidate(source_folder, candidates, "po")
            if source_path:
                path = os.path.join(app_path, "locale", language, "LC_MESSAGES", "django")
                target_path_po = path + ".po"
                target_path_mo = path + ".mo"
                try:
                    run_command("cp %s %s" % (source_path, target_path_po))
                    message = "[ok]"
                    if os.path.isfile(target_path_mo):
                        run_command("rm %s" % target_path_mo)
                except:
                    message = "[ERROR]"
                print("    %-12.12s %s --> %s" % (message, source_path, target_path_po))


def main():
    global DRY_RUN

    # Read config file
    config = read_config_file()
    project = config.get("general", "project").strip()
    settings_module = config.get("general", "settings_module").strip()
    available_apps = config.get("general", "apps").split(", ")

    # [autotranslate] section — all optional, with fallbacks
    def _conf(key, fallback=""):
        try:
            return config.get("autotranslate", key).strip()
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    config_engine = _conf("engine", "google")
    config_domain = _conf("domain", "")
    config_api_key = _conf("anthropic_api_key", "")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    sys.path.insert(0, os.getcwd())
    available_languages = list_available_languages(settings_module)

    # Parse command line
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.epilog = (
        "Available apps: "
        + ", ".join(available_apps)
        + "; "
        + "Available languages: "
        + ", ".join(available_languages)
    )
    command_choices = {
        "make":           "extract translatable strings and create/update .po files",
        "compile":        "compile .po files into binary .mo files",
        "collect":        "copy .po files into the translations target folder",
        "install":        "copy .po files from the translations target folder into the app locale folders",
        "remove":         "remove the locale/LANGUAGE folder (and its .po/.mo files) for the given app(s)",
        "autotranslate": "auto-translate untranslated strings in .po files using an AI service",
    }

    command_help = "\n".join(
        "  %-16s %s" % (name, description)
        for name, description in command_choices.items()
    )
    parser.add_argument(
        "command",
        metavar="command",
        choices=command_choices.keys(),
        help="one of:\n" + command_help,
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        choices=[0, 1, 2, 3],
        default=2,
        help="Verbosity level. (default: 2)",
    )
    parser.add_argument(
        "-f",
        "--fuzzy",
        action="store_true",
        default=False,
        help="Set fuzzy flag for new translations (only for autotranslate command)",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        default=False,
        help="Don't execute commands, just pretend. (default: False)",
    )
    parser.add_argument("-a", "--apps", nargs="*", required=False)
    parser.add_argument("-l", "--languages", nargs="*", required=False)
    parser.add_argument(
        "--engine",
        choices=["google", "claude"],
        default=config_engine or "google",
        help="Translation engine for autotranslate: 'google' (default) or 'claude' "
             "(requires anthropic package and ANTHROPIC_API_KEY env var). "
             "Can be set in djmessages.conf [autotranslate] engine=",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="Application domain description used by Claude to choose appropriate terminology "
             "(e.g. 'paint dosing systems for the construction industry'). "
             "Can be set in djmessages.conf [autotranslate] domain=",
    )
    parser.add_argument(
        "--project-path",
        default=None,
        help="Root of the Django project to scan for context (autotranslate + claude engine only). "
             "Defaults to the current working directory.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (overrides ANTHROPIC_API_KEY env var and djmessages.conf, claude engine only)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of strings per Claude API call (default: 500, claude engine only)",
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model to use (default: claude-haiku-4-5-20251001, claude engine only)",
    )
    parsed = parser.parse_args()

    command = parsed.command
    translations_target_folder = config.get(
        "general", "translations_target_folder"
    ).strip()
    if parsed.dry_run:
        DRY_RUN = True

    # Load app list from "apps" option (default: all)
    apps = []
    for app in (parsed.apps or available_apps):
        if app in available_apps:
            apps.append(app)
        else:
            raise Exception('Unknown app "%s"' % app)
    apps = list(set(apps))

    # Load language list from "languages" option (default: all)
    languages = []
    for language in (parsed.languages or available_languages):
        language = normalize_language(language)
        if language in available_languages:
            languages.append(language)
        else:
            raise Exception('Unknown language "%s"' % language)
    languages = list(set(languages))

    print("command: " + command)
    print("languages: " + ", ".join(languages))
    print("apps: " + ", ".join(apps))

    # Execute command
    if command == "make":
        do_makemessages(apps, languages)
    elif command == "compile":
        do_compilemessages(apps, languages)
    elif command == "collect":
        do_collectmessages(apps, languages, translations_target_folder)
    elif command == "install":
        do_installmessages(apps, languages, translations_target_folder)
    elif command == "autotranslate":
        project_path = parsed.project_path or os.getcwd()
        # CLI args take priority over djmessages.conf values
        api_key = parsed.api_key or config_api_key or None
        domain = parsed.domain or config_domain or ""
        do_auto_translatemessages(
            apps, languages, parsed.fuzzy,
            engine=parsed.engine,
            project_path=project_path,
            api_key=api_key,
            batch_size=parsed.batch_size,
            model=parsed.model,
            domain=domain,
        )
    elif command == "remove":
        do_removemessages(apps, languages)
    else:
        fail('Unknown command "%s"' % command)

    print("done.")


if __name__ == "__main__":
    main()
