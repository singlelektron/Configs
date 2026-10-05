"""Small, deterministic application search model with no GTK or process state."""
from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class Application:
    desktop_id: str
    name: str
    description: str = ""
    generic_name: str = ""
    executable: str = ""
    keywords: tuple[str, ...] = ()


def normalize(value):
    return unicodedata.normalize("NFKC", value).casefold().strip()


def search_applications(applications, query):
    """Match every query term, prioritizing exact names and name prefixes.

    Metadata remains searchable, including translated descriptions, generic
    names, executable names and .desktop keywords. No launch history is kept.
    """
    phrase = normalize(query)
    terms = phrase.split()
    matches = []
    for application in applications:
        name = normalize(application.name)
        metadata = normalize(" ".join((application.generic_name, application.description,
                                       application.executable, *application.keywords)))
        searchable = name + " " + metadata
        if not all(term in searchable for term in terms):
            continue
        if not phrase or name == phrase:
            score = 0
        elif name.startswith(phrase):
            score = 1
        elif all(any(word.startswith(term) for word in name.split()) for term in terms):
            score = 2
        elif all(term in name for term in terms):
            score = 3
        else:
            score = 4
        matches.append((score, name, application.desktop_id, application))
    return [entry[3] for entry in sorted(matches, key=lambda entry: entry[:3])]
