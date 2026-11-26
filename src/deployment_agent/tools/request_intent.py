import re


_CHANGE_VERB = re.compile(
    r"\b(?:create|add|generate|write|make|update|modify|change|set\s+up)\b",
    re.IGNORECASE,
)
_DOCKERFILE = re.compile(r"\bdocker[\s-]?file\b", re.IGNORECASE)
_CI_TARGET = re.compile(
    r"\b(?:ci|continuous integration|github actions|workflow|pipeline)\b",
    re.IGNORECASE,
)


def requests_dockerfile(requirement: str) -> bool:
    return bool(_CHANGE_VERB.search(requirement) and _DOCKERFILE.search(requirement))


def requests_ci_configuration(requirement: str) -> bool:
    return bool(_CHANGE_VERB.search(requirement) and _CI_TARGET.search(requirement))
