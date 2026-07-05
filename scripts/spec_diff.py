"""Spec round-trip check: docs/agent_os_openapi.yaml is the contract; the
FastAPI-generated schema must stay in semantic parity with it.

Compared, per operation: path+method set, operationId, parameter names/in/
required, request-body required flag, response status codes, and — recursively
through resolved $refs — property name sets, required sets, types, enum values,
and the Money pattern. Descriptions, examples, and constraint sugar (min/max)
are not compared; $ref layout differences are normalized away, and
`type: [X, null]` / `anyOf: [X, null]` are treated as equivalent.

Exit 0 = no drift. Non-zero = drift, one line per finding.
"""

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "docs" / "agent_os_openapi.yaml"

_IGNORED_PARAMS: set[str] = set()


def _components(doc: dict) -> dict:
    return doc.get("components", {}).get("schemas", {})


def norm_schema(schema: Any, components: dict, seen: tuple = ()) -> Any:
    if not isinstance(schema, dict):
        return None

    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        if name in seen:
            return {"circular": name}
        return norm_schema(components.get(name, {}), components, (*seen, name))

    if "allOf" in schema:
        merged_props: dict = {}
        merged_required: set = set()
        merged_type = None
        extra: dict = {}
        for sub in schema["allOf"]:
            n = norm_schema(sub, components, seen) or {}
            merged_props.update(n.get("properties", {}))
            merged_required |= set(n.get("required", []))
            merged_type = n.get("type", merged_type)
            for key in ("enum", "pattern", "items"):
                if key in n:
                    extra[key] = n[key]
        out: dict = {"type": merged_type or "object", **extra}
        if merged_props:
            out["properties"] = merged_props
        if merged_required:
            out["required"] = sorted(merged_required)
        return out

    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            subs = [s for s in schema[combinator] if s.get("type") != "null"]
            if len(subs) == 1:
                return norm_schema(subs[0], components, seen)
            return {"anyOf": [norm_schema(s, components, seen) for s in subs]}

    type_ = schema.get("type")
    if isinstance(type_, list):
        non_null = [t for t in type_ if t != "null"]
        type_ = non_null[0] if len(non_null) == 1 else tuple(non_null) or None
    if type_ is None and "properties" in schema:
        type_ = "object"

    out = {}
    if type_:
        out["type"] = type_
    if "enum" in schema:
        out["enum"] = sorted(str(v) for v in schema["enum"] if v is not None)
    if "const" in schema:
        out["enum"] = [str(schema["const"])]
    if "pattern" in schema:
        out["pattern"] = schema["pattern"]
    if "properties" in schema:
        out["properties"] = {
            k: norm_schema(v, components, seen) for k, v in schema["properties"].items()
        }
    if "required" in schema:
        out["required"] = sorted(schema["required"])
    if "items" in schema:
        out["items"] = norm_schema(schema["items"], components, seen)
    if isinstance(schema.get("additionalProperties"), dict):
        out["additionalProperties"] = norm_schema(
            schema["additionalProperties"], components, seen
        )
    return out


def norm_operation(path: str, method: str, op: dict, path_params: list, components: dict) -> dict:
    params = {}
    for param in [*path_params, *op.get("parameters", [])]:
        if "$ref" in param:  # spec-level parameter refs
            name = param["$ref"].split("/")[-1]
            param = _PARAM_COMPONENTS[name]
        if param["name"] in _IGNORED_PARAMS:
            continue
        params[(param["in"], param["name"])] = bool(param.get("required", False))

    body = op.get("requestBody")
    request = None
    if body is not None:
        schema = body.get("content", {}).get("application/json", {}).get("schema")
        request = {
            "required": bool(body.get("required", False)),
            "schema": norm_schema(schema, components),
        }

    responses = {}
    for code, resp in op.get("responses", {}).items():
        if "$ref" in resp:  # response component refs, e.g. #/components/responses/Error
            resp = _RESPONSE_COMPONENTS.get(resp["$ref"].split("/")[-1], {})
        schema = resp.get("content", {}).get("application/json", {}).get("schema")
        responses[str(code)] = norm_schema(schema, components)

    return {
        "operationId": op.get("operationId"),
        "params": params,
        "request": request,
        "responses": responses,
    }


_PARAM_COMPONENTS: dict = {}
_RESPONSE_COMPONENTS: dict = {}


def norm_doc(doc: dict) -> dict:
    global _PARAM_COMPONENTS, _RESPONSE_COMPONENTS
    _PARAM_COMPONENTS = doc.get("components", {}).get("parameters", {})
    _RESPONSE_COMPONENTS = doc.get("components", {}).get("responses", {})
    components = _components(doc)
    out = {}
    for path, item in doc.get("paths", {}).items():
        path_params = item.get("parameters", [])
        for method, op in item.items():
            if method in ("get", "post", "put", "patch", "delete"):
                out[f"{method.upper()} {path}"] = norm_operation(
                    path, method, op, path_params, components
                )
    return out


def diff_values(loc: str, spec: Any, generated: Any, findings: list[str]) -> None:
    if isinstance(spec, dict) and isinstance(generated, dict):
        for key in sorted(set(spec) | set(generated)):
            if key not in spec:
                findings.append(f"{loc}.{key}: present in generated schema, absent in spec")
            elif key not in generated:
                findings.append(f"{loc}.{key}: required by spec, missing in generated schema")
            else:
                diff_values(f"{loc}.{key}", spec[key], generated[key], findings)
    elif spec != generated:
        findings.append(f"{loc}: spec={spec!r} generated={generated!r}")


def compare(spec_doc: dict, generated_doc: dict) -> list[str]:
    findings: list[str] = []
    spec_ops = norm_doc(spec_doc)
    gen_ops = norm_doc(generated_doc)

    for key in sorted(set(spec_ops) | set(gen_ops)):
        if key not in gen_ops:
            findings.append(f"{key}: in spec but not implemented")
            continue
        if key not in spec_ops:
            findings.append(f"{key}: implemented but not in spec")
            continue
        diff_values(key, spec_ops[key], gen_ops[key], findings)

    sec = generated_doc.get("components", {}).get("securitySchemes", {}).get("bearerAuth", {})
    if sec.get("type") != "http" or sec.get("scheme") != "bearer":
        findings.append("securitySchemes.bearerAuth: missing or not http/bearer")
    if {"bearerAuth": []} not in generated_doc.get("security", []):
        findings.append("global security: bearerAuth requirement missing")
    return findings


def main() -> int:
    spec_doc = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from enos.api.app import app

    generated_doc = app.openapi()

    findings = compare(spec_doc, generated_doc)
    if findings:
        print(f"SPEC DRIFT — {len(findings)} finding(s):")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print(f"OK — {len(norm_doc(spec_doc))} operations in semantic parity with the spec.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
