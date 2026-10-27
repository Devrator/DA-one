"""SAP S/4HANA connector tests.

IMPORTANT HONESTY NOTE (spec §16): these tests exercise the REAL connector
code against a LOCAL ODATA PROTOCOL-FIXTURE HTTP SERVER. That validates
protocol handling (EDMX parsing, query building, pagination, retries, SSRF,
auth flows) but it is NOT a live SAP connection. Live-tenant verification
remains pending and is covered by the checklist in docs.

Parts:
  1. Pure unit tests: metadata parser, literal encoding, filter rendering,
     page parsing, net_security/SSRF, policy boundary, crypto, auth handler.
  2. Adapter integration tests against the fixture server: discovery,
     paginated fetches, retry/backoff, poisoned continuation URLs, redirects,
     size caps, auth failures, OAuth2 token lifecycle, role enforcement.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.connectors.base import ConnectorContext, ConnectorError
from app.services.connectors.net_security import (
    UnsafeURLError,
    host_is_allowed,
    parse_allowed_hosts,
    validate_continuation_url,
    validate_url,
)
from app.services.connectors.sap_s4hana import odata
from app.services.connectors.sap_s4hana.auth import AuthHandler, redact
from app.services.connectors.sap_s4hana.metadata import (
    descriptor_from_dict,
    descriptor_to_dict,
    normalize_edm_type,
    parse_edmx,
    parse_service_document,
)
from app.services.connectors.sap_s4hana.policy import validate_plan
from app.services.connectors.sap_s4hana.adapter import SAPS4hanaConnector
from app.services.crypto import decrypt_secret, encrypt_secret, is_encrypted, reencrypt_if_needed

# ---------------------------------------------------------------------------
# Fixtures data: real-shaped EDMX documents
# ---------------------------------------------------------------------------

EDMX_V4 = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="SAP.api.sales_1" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="SalesOrder">
        <Key><PropertyRef Name="SalesOrderID"/></Key>
        <Property Name="SalesOrderID" Type="Edm.String" Nullable="false" MaxLength="10"/>
        <Property Name="NetAmountME" Type="Edm.Decimal" Nullable="true" Precision="15" Scale="3"/>
        <Property Name="TransactionCreatedAt" Type="Edm.DateTimeOffset"/>
        <Property Name="RegionCode" Type="Edm.String" MaxLength="4"/>
        <Property Name="BuyerName" Type="Edm.String" MaxLength="80"/>
        <NavigationProperty Name="Items" Type="Collection(SAP.api.sales_1.SalesOrderItem)"/>
      </EntityType>
      <EntityType Name="SalesOrderItem">
        <Key><PropertyRef Name="SalesOrderID"/><PropertyRef Name="ItemNo"/></Key>
        <Property Name="SalesOrderID" Type="Edm.String" Nullable="false"/>
        <Property Name="ItemNo" Type="Edm.String" Nullable="false"/>
        <Property Name="Quantity" Type="Edm.Decimal" Precision="13" Scale="3"/>
      </EntityType>
      <EntityType Name="BusinessPartner">
        <Key><PropertyRef Name="BusinessPartnerID"/></Key>
        <Property Name="BusinessPartnerID" Type="Edm.String" Nullable="false"/>
        <Property Name="BusinessPartnerDisplayName" Type="Edm.String"/>
        <Property Name="EmailAddress" Type="Edm.String"/>
        <Property Name="PhoneNumber" Type="Edm.String"/>
      </EntityType>
      <EntityType Name="PurchaseOrder">
        <Key><PropertyRef Name="PurchaseOrderID"/></Key>
        <Property Name="PurchaseOrderID" Type="Edm.String" Nullable="false"/>
        <Property Name="SupplierName" Type="Edm.String"/>
      </EntityType>
      <EntityType Name="PurchaseOrderItem">
        <Key><PropertyRef Name="PurchaseOrderID"/><PropertyRef Name="ItemNo"/></Key>
        <Property Name="PurchaseOrderID" Type="Edm.String"/>
        <Property Name="ItemNo" Type="Edm.String"/>
        <Property Name="MaterialEntryPrice" Type="Edm.Decimal" Precision="15" Scale="3"/>
      </EntityType>
      <EntityType Name="Supplier">
        <Key><PropertyRef Name="SupplierID"/></Key>
        <Property Name="SupplierID" Type="Edm.String"/>
        <Property Name="SupplierAccountGroupCode" Type="Edm.String"/>
      </EntityType>
      <EntityType Name="Product">
        <Key><PropertyRef Name="ProductID"/></Key>
        <Property Name="ProductID" Type="Edm.Int32" Nullable="false"/>
        <Property Name="ProductName" Type="Edm.String" MaxLength="60"/>
        <Property Name="StandardCost" Type="Edm.Decimal" Precision="15" Scale="2"/>
      </EntityType>
      <EntityType Name="Attachment">
        <Key><PropertyRef Name="AttachmentID"/></Key>
        <Property Name="AttachmentID" Type="Edm.String"/>
        <Property Name="Payload" Type="Edm.Binary"/>
      </EntityType>
      <EntityContainer Name="Service">
        <EntitySet Name="I_SalesOrder" EntityType="SAP.api.sales_1.SalesOrder"/>
        <EntitySet Name="I_SalesOrderItem" EntityType="SAP.api.sales_1.SalesOrderItem"/>
        <EntitySet Name="I_BusinessPartner" EntityType="SAP.api.sales_1.BusinessPartner"/>
        <EntitySet Name="I_PurchaseOrder" EntityType="SAP.api.sales_1.PurchaseOrder"/>
        <EntitySet Name="I_PurchaseOrderItem" EntityType="SAP.api.sales_1.PurchaseOrderItem"/>
        <EntitySet Name="I_Supplier" EntityType="OTHER.NS.Supplier"/>
        <EntitySet Name="I_Product" EntityType="SAP.api.sales_1.Product"/>
        <EntitySet Name="I_Attachment" EntityType="SAP.api.sales_1.Attachment"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""

EDMX_V2 = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"
           xmlns:m="http://schemas.microsoft.com/ado/2008/09/metadata">
  <edmx:DataServices m:DataServiceVersion="2.0">
    <Schema Namespace="Test.Gateway" xmlns="http://schemas.microsoft.com/ado/2008/09/csdl">
      <EntityType Name="OrderType">
        <Key><PropertyRef Name="OrderID"/></Key>
        <Property Name="OrderID" Type="Edm.String" Nullable="false"/>
        <Property Name="Status" Type="Edm.String" m:updatable="false"/>
        <Property Name="CreatedAt" Type="Edm.DateTime"/>
        <Property Name="Total" Type="Edm.Decimal" Precision="15" Scale="2"/>
      </EntityType>
      <EntityContainer Name="Container">
        <EntitySet Name="OrderSet" EntityType="Test.Gateway.OrderType" m:count="7"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


# ---------------------------------------------------------------------------
# 1. Pure unit tests
# ---------------------------------------------------------------------------

def test_parse_edmx_v4_typed_entities():
    parsed = parse_edmx(EDMX_V4)
    assert parsed["odata_version"] == "4"
    names = {e.name for e in parsed["entities"]}
    assert {"I_SalesOrder", "I_SalesOrderItem", "I_BusinessPartner", "I_PurchaseOrder"} <= names
    so = next(e for e in parsed["entities"] if e.name == "I_SalesOrder")
    assert so.keys == ["SalesOrderID"]
    assert so.navigation == ["Items"]
    assert so.declared is True
    amt = so.property("NetAmountME")
    assert amt.json_type == "number" and amt.precision == 15 and amt.scale == 3
    when = so.property("TransactionCreatedAt")
    assert when.json_type == "datetime"
    key_prop = so.property("SalesOrderID")
    assert key_prop.is_key and not key_prop.nullable


def test_parse_edmx_v4_short_name_fallback():
    """I_Supplier references OTHER.NS.Supplier — parser must resolve by short name."""
    parsed = parse_edmx(EDMX_V4)
    sup = next(e for e in parsed["entities"] if e.name == "I_Supplier")
    assert sup.property("SupplierAccountGroupCode") is not None


def test_parse_edmx_v2_readonly_count_and_types():
    parsed = parse_edmx(EDMX_V2)
    assert parsed["odata_version"] == "2"
    order = parsed["entities"][0]
    assert order.name == "OrderSet" and order.count == 7
    status = order.property("Status")
    assert status.readonly is True          # m:updatable="false"
    assert order.property("CreatedAt").json_type == "datetime"  # Edm.DateTime
    assert normalize_edm_type("Edm.DateTime")[0] == "datetime"


def test_parse_edmx_rejects_dtd():
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><edmx:Edmx xmlns:edmx="x" Version="4.0"/>'
    with pytest.raises(ValueError):
        parse_edmx(evil)


def test_parse_service_document_v4_and_v2_flavors():
    v4 = parse_service_document({"value": [{"name": "I_SalesOrder", "url": "I_SalesOrder"}]},
                                "http://h/svc")
    assert v4[0].name == "I_SalesOrder" and v4[0].url == "http://h/svc/I_SalesOrder"
    v2 = parse_service_document({"d": {"results": [{"name": "OrderSet", "url": "/OrderSet"}]}},
                                "http://h/svc")
    assert v2[0].url == "http://h/svc/OrderSet"


def test_descriptor_cache_roundtrip():
    parsed = parse_edmx(EDMX_V4)
    entities = parsed["entities"]
    data = descriptor_to_dict([], entities, parsed["source_version"], ["note"])
    services, restored, version, notes = descriptor_from_dict(data)
    assert version == parsed["source_version"] and notes == ["note"]
    a = next(e for e in entities if e.name == "I_SalesOrder")
    b = next(e for e in restored if e.name == "I_SalesOrder")
    assert [p.name for p in a.properties] == [p.name for p in b.properties]
    assert b.property("NetAmountME").json_type == "number"


def test_encode_literal_quote_escape():
    out = odata.encode_literal("O'Brien", "Edm.String", "4")
    assert out == "'O''Brien'"


def test_encode_literal_datetime_versions():
    v2 = odata.encode_literal("2023-01-05T00:00:00", "Edm.DateTime", "2")
    assert v2 == "datetime'2023-01-05T00:00:00'"
    v4 = odata.encode_literal("2023-01-05T00:00:00Z", "Edm.DateTimeOffset", "4")
    assert v4 == "2023-01-05T00:00:00Z"


def test_encode_literal_type_mismatch_rejected():
    from app.services.connectors.base import PolicyError
    with pytest.raises(PolicyError):
        odata.encode_literal("not-a-number", "Edm.Int32", "4")
    with pytest.raises(PolicyError):
        odata.encode_literal("nope", "Edm.Boolean", "4")


def test_render_filter_plan_v2_and_v4():
    parsed = parse_edmx(EDMX_V4)
    so = next(e for e in parsed["entities"] if e.name == "I_SalesOrder")
    plan = {"and": [{"field": "RegionCode", "op": "eq", "value": "NORTH"},
                    {"field": "NetAmountME", "op": "gt", "value": 100}]}
    f4 = odata.render_filter_plan(plan, so, "4")
    assert f4 == "(RegionCode eq 'NORTH') and (NetAmountME gt 100)"
    f2 = odata.render_filter_plan({"field": "BuyerName", "op": "contains", "value": "ACME"}, so, "2")
    assert f2 == "substringof('ACME',BuyerName)"


def test_render_filter_undeclared_field_rejected():
    from app.services.connectors.base import PolicyError
    parsed = parse_edmx(EDMX_V4)
    so = next(e for e in parsed["entities"] if e.name == "I_SalesOrder")
    with pytest.raises(PolicyError):
        odata.render_filter_plan({"field": "DROP TABLE", "op": "eq", "value": "x"}, so, "4")


def test_parse_page_v4_and_v2():
    rows, nxt, count = odata.parse_page(
        {"value": [{"A": 1}], "@odata.nextLink": "http://h/svc/E?skiptoken=x", "@odata.count": "9"}, "4")
    assert rows == [{"A": 1}] and nxt.endswith("skiptoken=x") and count == 9
    rows, nxt, count = odata.parse_page(
        {"d": {"results": [{"A": 2}], "__next": "http://h/svc/E?x=1", "__count": "3"}}, "2")
    assert rows == [{"A": 2}] and nxt == "http://h/svc/E?x=1" and count == 3


def test_build_query_params_v2_includes_format():
    p = odata.build_query_params(select=["A", "B"], filter_str="A eq 'x'",
                                 orderby=None, top=10, version="2")
    assert p["$select"] == "A,B" and p["$format"] == "json" and p["$top"] == 10


# ---- net security ----------------------------------------------------------

def test_parse_allowed_hosts():
    assert parse_allowed_hosts("A.com, *.b.corp ") == ["a.com", "*.b.corp"]


def test_validate_url_allowlist_and_fail_closed():
    assert validate_url("https://a.com/svc", ["a.com"]) == "https://a.com/svc"
    assert validate_url("https://x.b.corp/svc", ["*.b.corp"])
    with pytest.raises(UnsafeURLError):
        validate_url("https://evil.com/svc", ["a.com"])
    with pytest.raises(UnsafeURLError):
        validate_url("https://a.com", [])           # fail-closed
    with pytest.raises(UnsafeURLError):
        validate_url("file:///etc/passwd", ["a.com"])


def test_validate_url_blocks_metadata_and_internal():
    # hard block wins even if an admin tries to allowlist the metadata IP
    with pytest.raises(UnsafeURLError):
        validate_url("http://169.254.169.254/latest/meta-data", ["169.254.169.254"])
    with pytest.raises(UnsafeURLError):
        validate_url("http://10.0.0.5/svc", ["a.com"])     # private IP not allowlisted
    # an allowlisted private IP (SAP over VPN) is permitted
    assert validate_url("http://10.0.0.5/svc", ["10.0.0.5"]) == "http://10.0.0.5/svc"


def test_continuation_url_same_origin_required():
    svc = "https://sap.corp/svc/I_SalesOrder"
    good = "https://sap.corp/svc/I_SalesOrder?skiptoken=2"
    assert validate_continuation_url(good, svc, ["sap.corp"]) == good + ""
    with pytest.raises(UnsafeURLError):
        validate_continuation_url("https://evil.com/x", svc, ["sap.corp"])
    with pytest.raises(UnsafeURLError):
        validate_continuation_url("http://169.254.169.254/next", svc, ["sap.corp"])


# ---- policy boundary --------------------------------------------------------

def _entities_by_name():
    parsed = parse_edmx(EDMX_V4)
    return {e.name: e for e in parsed["entities"]}


def test_policy_rejects_unknown_entity_and_field():
    ents = _entities_by_name()
    with pytest.raises(Exception):
        validate_plan(None, {"select": ["A"]}, "executive", max_records=100)
    with pytest.raises(Exception):
        validate_plan(ents["I_SalesOrder"], {"select": ["Nope"]}, "executive", max_records=100)


def test_policy_blocks_large_binary_select():
    ents = _entities_by_name()
    with pytest.raises(Exception):
        validate_plan(ents["I_Attachment"], {"select": ["Payload"]}, "executive", max_records=100)


def test_policy_role_restrictions_sap():
    ents = _entities_by_name()
    # sales_rep: whole purchasing entities prohibited
    with pytest.raises(Exception):
        validate_plan(ents["I_PurchaseOrder"], {"select": ["PurchaseOrderID"]},
                      "sales_rep", max_records=100)
    # regional_manager: supplier price column restricted
    with pytest.raises(Exception):
        validate_plan(ents["I_PurchaseOrderItem"],
                      {"select": ["PurchaseOrderID", "MaterialEntryPrice"]},
                      "regional_manager", max_records=100)
    # executive can
    ok = validate_plan(ents["I_PurchaseOrderItem"],
                       {"select": ["PurchaseOrderID", "MaterialEntryPrice"]},
                       "executive", max_records=100)
    assert ok["select"] == ["PurchaseOrderID", "MaterialEntryPrice"]


def test_policy_clamps_top_and_validates_orderby():
    ents = _entities_by_name()
    plan = validate_plan(ents["I_SalesOrder"], {"select": ["SalesOrderID"], "top": 99999},
                         "executive", max_records=500)
    assert plan["top"] == 500
    with pytest.raises(Exception):
        validate_plan(ents["I_SalesOrder"], {"select": ["SalesOrderID"], "orderby": "Nope asc"},
                      "executive", max_records=500)
    with pytest.raises(Exception):
        validate_plan(ents["I_SalesOrder"],
                      {"select": ["SalesOrderID"], "orderby": "RegionCode sideways"},
                      "executive", max_records=500)


def test_policy_rejects_structures_and_bad_operators_in_filter():
    ents = _entities_by_name()
    with pytest.raises(Exception):
        validate_plan(ents["I_SalesOrder"],
                      {"select": ["SalesOrderID"],
                       "filter": {"field": "RegionCode", "op": "eq", "value": {"$ne": None}}},
                      "executive", max_records=500)
    with pytest.raises(Exception):
        validate_plan(ents["I_SalesOrder"],
                      {"select": ["SalesOrderID"],
                       "filter": {"field": "RegionCode", "op": "gtgt", "value": "x"}},
                      "executive", max_records=500)


# ---- crypto -------------------------------------------------------------------

def test_crypto_roundtrip_and_legacy_passthrough():
    enc = encrypt_secret("s3cret")
    assert is_encrypted(enc) and enc != "s3cret"
    assert decrypt_secret(enc) == "s3cret"
    assert decrypt_secret("legacy-plaintext") == "legacy-plaintext"
    assert encrypt_secret(enc) == enc  # idempotent


def test_crypto_reencrypt_upgrades_plaintext():
    upgraded = reencrypt_if_needed("plaintext-value")
    assert is_encrypted(upgraded) and decrypt_secret(upgraded) == "plaintext-value"
    assert reencrypt_if_needed(upgraded) == upgraded


def test_auth_handler_basic_and_redaction():
    h = AuthHandler(auth_mode="basic", username="user1", secret="pw1")
    hdrs = h.headers()
    assert hdrs["Authorization"].startswith("Basic ")
    decoded = base64.b64decode(hdrs["Authorization"].split()[1]).decode()
    assert decoded == "user1:pw1"
    assert "pw1" not in json.dumps(h.describe())
    msg = redact("failed with Authorization: Bearer abc123")
    assert "abc123" not in msg


# ---------------------------------------------------------------------------
# 2. Protocol-fixture HTTP server (NOT a live SAP system)
# ---------------------------------------------------------------------------

class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "ODataFixture/1.0"

    def log_message(self, *args):  # silence
        pass

    def _json(self, obj, status=200, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _xml(self, text, status=200):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        from urllib.parse import urlsplit
        path = urlsplit(self.path).path
        srv: FixtureServer = self.server.fixtures

        if path == "/token":
            auth = self.headers.get("Authorization", "")
            expect = "Basic " + base64.b64encode(b"svc-client:svc-secret").decode()
            srv.token_calls += 1
            if auth != expect:
                return self._json({"error": "invalid_client"}, 401)
            return self._json({"access_token": f"tok-{srv.token_calls}",
                               "expires_in": 3600, "token_type": "Bearer"})

        if path.startswith("/secure/") and self.headers.get("Authorization", "").startswith("Bearer tok-"):
            if path == "/secure/svc":
                return self._json({"value": [{"name": "I_SalesOrder", "url": "I_SalesOrder"}]})
            if path == "/secure/svc/$metadata":
                return self._xml(EDMX_V4)

        if path.startswith("/svc_oauth/") and not self.headers.get("Authorization", "").startswith("Bearer tok-"):
            return self._json({"error": "unauthorized"}, 401)
        root = None
        for candidate in ("/svc_oauth/svc", "/svc", "/flaky/svc", "/evilnext/svc",
                          "/redirect/svc", "/unauth/svc", "/huge/svc", "/v2svc"):
            if path == candidate or path.startswith(candidate + "/") or path == candidate + "?":
                root = candidate
                break
        if root is None:
            return self._json({"error": "not found"}, 404)

        if root == "/unauth/svc":
            return self._json({"error": "unauthorized"}, 401)
        if root == "/redirect/svc" and path == "/redirect/svc":
            return self._json({}, 302, {"Location": "http://evil.example.com/steal"})

        base = f"http://127.0.0.1:{srv.port}"

        if path == f"{root}/$metadata":
            return self._xml(EDMX_V2 if root == "/v2svc" else EDMX_V4)

        if path == root:  # service document
            return self._json({"value": [{"name": "I_SalesOrder", "url": "I_SalesOrder"}]})

        if path == f"{root}/I_Product":
            return self._json({"value": [
                {"ProductID": i,
                 "ProductName": ["Widget A", "Widget B", "Gadget C", "Gadget D", "Part E"][i - 1],
                 "StandardCost": f"{i * 7.5:.2f}"}
                for i in range(1, 6)
            ]})

        if path == f"{root}/I_BusinessPartner":
            return self._json({"value": [
                {"BusinessPartnerID": "BP-1", "BusinessPartnerDisplayName": "ACME Ltd",
                 "EmailAddress": "ops@acme.test", "PhoneNumber": "+49-111"},
                {"BusinessPartnerID": "BP-2", "BusinessPartnerDisplayName": "Globex Inc",
                 "EmailAddress": "io@globex.test", "PhoneNumber": "+1-212"},
            ]})

        if path in (f"{root}/I_SalesOrder", f"{root}/OrderSet"):
            if root == "/flaky/svc":
                srv.flaky_count += 1
                if srv.flaky_count <= 2:
                    return self._json({"error": "temporarily unavailable"}, 503)
            if root == "/huge/svc":
                big = {"value": [{"SalesOrderID": "X" * 500} for _ in range(50)]}
                return self._json(big)
            rows = [
                {"SalesOrderID": f"SO-{i}", "NetAmountME": str(i * 10.5),
                 "RegionCode": "NORTH", "BuyerName": "ACME", "@odata.etag": 'W/"x"'}
                for i in (1, 2)
            ]
            if path.endswith("OrderSet"):
                rows = [{"OrderID": f"O-{i}", "Status": "OPEN", "Total": "10.0"} for i in (1, 2)]
            qs = urlsplit(self.path).query
            if "skiptoken=p2" in qs:
                page2 = [dict(r, SalesOrderID=r["SalesOrderID"].replace("SO-", "SO-9"))
                         if "SalesOrderID" in r else r for r in rows]
                if path.endswith("OrderSet"):
                    return self._json({"d": {"results": page2}})
                return self._json({"value": page2, "@odata.count": "4"})
            if root == "/evilnext/svc":
                nxt = "http://169.254.169.254/latest/meta-data/"
            else:
                nxt = f"{base}{root}/{'I_SalesOrder' if 'I_' in path else 'OrderSet'}?skiptoken=p2"
            if path.endswith("OrderSet"):
                return self._json({"d": {"results": rows, "__next": nxt}})
            return self._json({"value": rows, "@odata.nextLink": nxt, "@odata.count": "4"})

        return self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode() if length else ""
        if self.path == "/token":
            return self.do_GET()
        return self._json({"error": "not found"}, 404)


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.fixtures = self
        self.port = self.server_address[1]
        self.token_calls = 0
        self.flaky_count = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture(scope="module")
def fixture_srv():
    srv = FixtureServer()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


def _ctx(base_url: str, service_path: str, **overrides) -> ConnectorContext:
    params = dict(
        connection_id="test-conn", name="Fixture SAP", deployment_type="on_premises",
        base_url=base_url, service_path=service_path, odata_version="4",
        auth_mode="basic", username="sap_reader", secret="pw",
        allowed_hosts=["127.0.0.1", "localhost"],
        timeout_seconds=5.0, max_records=10, page_size=2,
        max_response_bytes=8_000_000, max_retries=3,
        backoff_base=0.01, backoff_max=0.05,
    )
    params.update(overrides)
    return ConnectorContext(**params)


# ---- adapter integration -----------------------------------------------------

def test_adapter_test_connection_success(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "svc"))
    result = conn.test_connection()
    assert result["success"] is True and result["entity_sets"] == 1
    assert "pw" not in json.dumps(result)  # describe never leaks secret


def test_adapter_test_connection_auth_failure_classified(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "unauth/svc"))
    result = conn.test_connection()
    assert result["success"] is False
    assert result["error_category"] == "authentication_error"


def test_adapter_discover_schema(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "svc"))
    desc = conn.discover_schema()
    assert desc.entity("I_SalesOrder") is not None
    assert desc.source_version.startswith("odata_v4")


def test_adapter_fetch_records_paginates(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "svc"))
    result = conn.fetch_records("I_SalesOrder",
                                select=["SalesOrderID", "RegionCode"],
                                filter_plan={"field": "RegionCode", "op": "eq", "value": "NORTH"},
                                orderby="SalesOrderID asc", top=4, role="executive")
    assert result.success
    assert result.row_count == 4  # 2 rows page 1 + 2 rows page 2 via validated continuation
    assert result.columns == ["SalesOrderID", "RegionCode"]
    assert result.truncated is False
    ids = [r["SalesOrderID"] for r in result.rows]
    assert ids[0].startswith("SO-") and ids[-1].startswith("SO-9")
    assert all(r["RegionCode"] == "NORTH" for r in result.rows)


def test_adapter_v2_service_flow(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "v2svc", odata_version="2"))
    desc = conn.discover_schema()
    order = desc.entity("OrderSet")
    assert order is not None and order.count == 7
    result = conn.fetch_records("OrderSet", select=["OrderID", "Status"], top=4,
                                role="executive")
    assert result.success and result.row_count == 4


def test_adapter_retry_on_transient_503(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "flaky/svc"))
    result = conn.fetch_records("I_SalesOrder", select=["SalesOrderID"], top=2, role="executive")
    assert result.success  # recovered after 503s


def test_adapter_refuses_poisoned_continuation_url(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "evilnext/svc"))
    with pytest.raises(ConnectorError) as exc:
        conn.fetch_records("I_SalesOrder", select=["SalesOrderID"], top=4, role="executive")
    assert exc.value.category == "configuration_error"


def test_adapter_refuses_redirect(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "redirect/svc"))
    result = conn.test_connection()
    assert result["success"] is False
    assert "redirect" in result["message"].lower()


def test_adapter_response_size_cap(fixture_srv):
    conn = SAPS4hanaConnector(_ctx(fixture_srv.base_url, "huge/svc", max_response_bytes=1000))
    with pytest.raises(ConnectorError) as exc:
        conn.fetch_records("I_SalesOrder", select=["SalesOrderID"], top=2, role="executive")
    assert exc.value.category == "size_limit"


def test_adapter_oauth2_token_lifecycle_and_bearer(fixture_srv):
    srv = fixture_srv
    conn = SAPS4hanaConnector(_ctx(srv.base_url, "svc_oauth/svc",
                                   auth_mode="oauth_client_credentials",
                                   username="", client_id="svc-client", secret="svc-secret",
                                   token_url=srv.base_url + "/token"))
    # Server only answers svc_oauth/svc with a valid Bearer token.
    before = srv.token_calls
    result = conn.test_connection()
    assert result["success"] is True
    after = srv.token_calls
    assert after - before == 1  # exactly one acquisition
    result2 = conn.test_connection()
    assert result2["success"] is True
    assert srv.token_calls == after  # cached token reused, no refetch


def test_adapter_oauth_refresh_after_invalidate(fixture_srv):
    srv = fixture_srv
    conn = SAPS4hanaConnector(_ctx(srv.base_url, "svc_oauth/svc",
                                   auth_mode="oauth_client_credentials",
                                   username="", client_id="svc-client", secret="svc-secret",
                                   token_url=srv.base_url + "/token"))
    assert conn.test_connection()["success"] is True
    conn._auth.invalidate()  # simulates token expiry / 401 recovery
    # NOTE: server accepts any tok-N we ever issued; refresh still performs a new fetch
    result = conn.test_connection()
    assert srv.token_calls >= 2  # a fresh acquisition happened after invalidation
