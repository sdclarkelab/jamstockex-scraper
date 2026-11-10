"""The packaged docs files: vendored Swagger UI, the docs page and openapi.json."""

import hashlib
import importlib.resources
import json
import re

import pytest

from tests.helpers import JSE_URL

PACKAGE = importlib.resources.files("jamstockex")
SWAGGER_VERSION = "5.33.3"
VENDORED_SHA256 = {
    "swagger-ui-bundle.js": "3861ec4cc8e7b9fa9f250280da9350436e418137788282c753b9a2ac5fb7bd2f",
    "swagger-ui.css": "1ac324f7dcd27e4b9386b4bd6421271ec147e922a22c05ba24b11515e9aa6321",
    "swagger-ui-bundle.js.LICENSE.txt": "e5a4792feaa5332dfba37f1d7adf84308b93b4f2d8da0569a9f48a3cb61c969b",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "NOTICE": "0d20d1adef18aee3f40dd258172155521ce702ac445cb5f7b7d60ed32dad2fb2",
}


def read(name):
    return PACKAGE.joinpath(name).read_text(encoding="utf-8")


def openapi():
    return json.loads(read("openapi.json"))


def test_swagger_version_is_recorded():
    assert read("static/swagger/VERSION") == SWAGGER_VERSION + "\n"


@pytest.mark.parametrize("name, digest", VENDORED_SHA256.items())
def test_vendored_files_are_the_pinned_release(name, digest):
    data = PACKAGE.joinpath("static/swagger", name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest


def test_swagger_license_is_apache_2():
    assert "Apache License" in read("static/swagger/LICENSE")
    assert "Version 2.0" in read("static/swagger/LICENSE")


def test_docs_page_loads_local_assets_without_inline_script():
    page = read("static/docs.html")
    assert '<link rel="stylesheet" href="/docs/assets/swagger-ui.css">' in page
    scripts = re.findall(r"<script[^>]*>", page)
    assert scripts == ['<script src="/docs/assets/swagger-ui-bundle.js">', '<script src="/docs/assets/docs-init.js">']
    assert "http://" not in page and "https://" not in page


def test_docs_init_script_points_at_the_local_openapi_document():
    script = read("static/docs-init.js")
    assert 'url: "/openapi.json"' in script
    assert "validatorUrl: null" in script  # no badge image from an outside validator


def test_openapi_document_shape():
    doc = openapi()
    assert doc["openapi"] == "3.1.0"
    assert doc["info"]["version"] == "2.0.0"
    assert doc["servers"] == [{"url": "/", "description": "This app, on 127.0.0.1"}]
    for path, item in doc["paths"].items():
        assert set(item) == {"get"}, path
        responses = item["get"]["responses"]
        assert {"403", "405", "500"} <= set(responses), path
        ok = responses.get("200") or responses.get("302")
        assert ok, path


def test_every_v2_json_response_has_an_example():
    for path, item in openapi()["paths"].items():
        if path.startswith("/v2/"):
            body = item["get"]["responses"]["200"]["content"]["application/json"]
            assert body["example"]["meta"]["api_version"] == "v2", path


def test_every_ref_resolves():
    doc = openapi()
    refs = set(re.findall(r'"\$ref": "#/components/(\w+)/(\w+)"', read("openapi.json")))
    assert refs
    assert {(kind, name) for kind, name in refs if name not in doc["components"][kind]} == set()


@pytest.mark.parametrize("name", ["openapi.json", "static/docs.html", "static/docs-init.js"])
def test_no_jse_links(name):
    assert not JSE_URL.search(read(name))
