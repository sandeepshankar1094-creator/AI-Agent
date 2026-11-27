import re


_CHANGE_VERB = re.compile(
    r"\b(?:create|creation|add|configure|generate|write|make|set|increase|"
    r"decrease|raise|lower|scale|adjust|update|modify|change|set\s+up)\b",
    re.IGNORECASE,
)
_REMOVE_VERB = re.compile(r"\b(?:remove|delete|drop)\b", re.IGNORECASE)
_DOCKERFILE = re.compile(r"\bdocker[\s-]?file\b", re.IGNORECASE)
_CI_TARGET = re.compile(
    r"\b(?:ci|continuous integration|github actions|workflow|pipeline)\b",
    re.IGNORECASE,
)
_HELM_CHART = re.compile(r"\bhelm\s+charts?\b", re.IGNORECASE)
_HELM_VALUES = re.compile(r"\b(?:helm\s+)?values\.ya?ml\b", re.IGNORECASE)
_CD_TARGET = re.compile(
    r"\b(?:cd|continuous delivery|continuous deployment|deploy(?:ment)? pipeline)\b",
    re.IGNORECASE,
)
_SECRET_TARGET = re.compile(
    r"\b(?:secrets?|api[\s_-]?keys?|access[\s_-]?tokens?|passwords?)\b",
    re.IGNORECASE,
)
_HELM_PARAMETER_TARGET = re.compile(
    r"\b(?:replicas?|replicaCount|resources?|limits?|requests?|cpu|memory|"
    r"auto[\s_-]?scal(?:e|er|ing)\w*"
    r"(?:[\s_-]+(?:min|max)(?:imum)?(?:\s+value)?)?|"
    r"(?:min|max)(?:imum)?\s+(?:auto[\s_-]?scal\w*|scale|replicas?|value)|"
    r"container\s+port|service\s+port|port|targetPort|portName|"
    r"image|tag|pullPolicy|readinessEndpoint|livenessEndpoint|readiness|"
    r"liveness|prometheusPath|prometheus|envCode|environment\s+code|"
    r"environment\s+variables?|env|ingress|virtualServiceName|virtual\s+service|"
    r"destinationRuleName|destination\s+rule|certName|certificate|"
    r"egressSvcEntry|egress|micrometer|akvName|key\s+vault|configMapName|"
    r"kvSecrets|serviceAccount|annotations|values\.ya?ml|"
    r"hostnames?|domains?|urls?|endpoints?|redis|destinations?|"
    r"ip(?:\s+address)?|https)\b",
    re.IGNORECASE,
)


def requests_dockerfile(requirement: str) -> bool:
    return bool(_CHANGE_VERB.search(requirement) and _DOCKERFILE.search(requirement))


def requests_ci_configuration(requirement: str) -> bool:
    return bool(_CHANGE_VERB.search(requirement) and _CI_TARGET.search(requirement))


def requests_helm_chart(requirement: str) -> bool:
    return bool(
        (_CHANGE_VERB.search(requirement) or _REMOVE_VERB.search(requirement))
        and (
            _HELM_CHART.search(requirement)
            or _HELM_VALUES.search(requirement)
            or _HELM_PARAMETER_TARGET.search(requirement)
        )
    )


def requests_cd_configuration(requirement: str) -> bool:
    return bool(_CHANGE_VERB.search(requirement) and _CD_TARGET.search(requirement))


def requests_helm_secret_configuration(requirement: str) -> bool:
    return bool(
        (_CHANGE_VERB.search(requirement) or _REMOVE_VERB.search(requirement))
        and _SECRET_TARGET.search(requirement)
    )


def requests_helm_parameter_update(requirement: str) -> bool:
    return bool(
        _CHANGE_VERB.search(requirement)
        and _HELM_PARAMETER_TARGET.search(requirement)
    )
