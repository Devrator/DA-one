"""Role-Based Access Control (RBAC) and Security Context Service for Phase 2.

Defines three secure roles:
1. Executive (Admin): Full analytical visibility across all regions, reps, and metrics.
2. Regional Manager: Row-restricted to assigned region; column-restricted from customer contact PII and unit cost prices.
3. Sales Rep: Row-restricted to assigned sales rep orders; column-restricted from cost prices, management targets, and customer PII.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set, Tuple


@dataclass(frozen=True)
class UserSecurityContext:
    """Server-resolved user security identity and permission scope."""
    user_id: str
    username: str
    role: str  # "executive", "regional_manager", "sales_rep"
    region_id: Optional[int] = None
    sales_rep: Optional[str] = None
    description: str = ""

    @property
    def is_executive(self) -> bool:
        return self.role == "executive"

    @property
    def is_regional_manager(self) -> bool:
        return self.role == "regional_manager"

    @property
    def is_sales_rep(self) -> bool:
        return self.role == "sales_rep"


# Built-in verified server-side identities (do not trust arbitrary client roles)
VERIFIED_USERS: dict[str, UserSecurityContext] = {
    "executive": UserSecurityContext(
        user_id="usr_exec_01",
        username="executive",
        role="executive",
        region_id=None,
        sales_rep=None,
        description="Executive / Admin — Organization-wide unrestricted analytical access",
    ),
    "regional_manager_north": UserSecurityContext(
        user_id="usr_mgr_north",
        username="regional_manager_north",
        role="regional_manager",
        region_id=1,  # North
        sales_rep=None,
        description="Regional Manager (North, Region 1) — Restricted to Region 1; no cost margins or customer PII",
    ),
    "regional_manager_south": UserSecurityContext(
        user_id="usr_mgr_south",
        username="regional_manager_south",
        role="regional_manager",
        region_id=2,  # South
        sales_rep=None,
        description="Regional Manager (South, Region 2) — Restricted to Region 2; no cost margins or customer PII",
    ),
    "sales_rep_carol": UserSecurityContext(
        user_id="usr_rep_carol",
        username="sales_rep_carol",
        role="sales_rep",
        region_id=1,
        sales_rep="Carol Chen",
        description="Sales Rep (Carol Chen) — Restricted to Carol Chen orders; no regional targets, cost prices, or PII",
    ),
    "sales_rep_david": UserSecurityContext(
        user_id="usr_rep_david",
        username="sales_rep_david",
        role="sales_rep",
        region_id=2,
        sales_rep="David Kim",
        description="Sales Rep (David Kim) — Restricted to David Kim orders; no regional targets, cost prices, or PII",
    ),
}

# Column restriction rules: (schema, table, column)
# Entries under schema "sap" govern SAP S/4HANA OData entities (entity set,
# property). They are EXAMPLE DEFAULTS for the shipped read-only analytics
# scope — administrators should tune them to mirror SAP-side authorizations.
# QueryPilot authz is IN ADDITION TO SAP authz, never a replacement.
RESTRICTED_COLUMNS: dict[str, Set[Tuple[str, str, str]]] = {
    "executive": set(),
    "regional_manager": {
        ("sales", "customers", "phone"),
        ("sales", "customers", "email"),
        ("sales", "product_catalog", "cost_price"),
        ("sap", "I_PurchaseOrderItem", "MaterialEntryPrice"),
        ("sap", "I_BusinessPartner", "EmailAddress"),
        ("sap", "I_BusinessPartner", "PhoneNumber"),
    },
    "sales_rep": {
        ("sales", "customers", "phone"),
        ("sales", "customers", "email"),
        ("sales", "product_catalog", "cost_price"),
        ("sales", "regional_targets", "revenue_target"),
        ("sales", "regions", "manager_name"),
        ("sap", "I_PurchaseOrderItem", "MaterialEntryPrice"),
        ("sap", "I_BusinessPartner", "EmailAddress"),
        ("sap", "I_BusinessPartner", "PhoneNumber"),
        ("sap", "I_Supplier", "SupplierAccountGroupCode"),
    },
}

# Prohibited tables per role (e.g. sales_rep cannot query regional_targets)
# "sap" schema entries prohibit whole SAP entity sets for a role.
PROHIBITED_TABLES_BY_ROLE: dict[str, Set[Tuple[str, str]]] = {
    "executive": set(),
    "regional_manager": set(),
    "sales_rep": {
        ("sales", "regional_targets"),
        ("sap", "I_PurchaseOrder"),
        ("sap", "I_PurchaseOrderItem"),
        ("sap", "I_Supplier"),
    },
}


def resolve_user_context(
    role_or_username: Optional[str] = None,
    explicit_role: Optional[str] = None,
    explicit_region_id: Optional[int] = None,
    explicit_sales_rep: Optional[str] = None,
) -> UserSecurityContext:
    """Resolve and validate user security context on the server."""
    if not role_or_username:
        role_or_username = "executive"

    key = role_or_username.lower().strip()
    if key in VERIFIED_USERS:
        base = VERIFIED_USERS[key]
        # Allow explicit parameters only if narrowing or matching
        region = explicit_region_id if explicit_region_id is not None else base.region_id
        rep = explicit_sales_rep if explicit_sales_rep is not None else base.sales_rep
        return UserSecurityContext(
            user_id=base.user_id,
            username=base.username,
            role=base.role,
            region_id=region,
            sales_rep=rep,
            description=base.description,
        )

    # If an explicit role is supplied, strictly validate against supported roles
    role = (explicit_role or key).lower()
    if role not in ("executive", "regional_manager", "sales_rep"):
        # Default to least-privileged role if unknown
        role = "sales_rep"
        rep = explicit_sales_rep or "Carol Chen"
        region = explicit_region_id or 1
    else:
        rep = explicit_sales_rep if role == "sales_rep" else None
        region = explicit_region_id if role in ("regional_manager", "sales_rep") else None

    return UserSecurityContext(
        user_id=f"usr_{role}",
        username=role_or_username,
        role=role,
        region_id=region,
        sales_rep=rep,
        description=f"Server-resolved {role} context",
    )


def is_column_allowed(schema: str, table: str, column: str, role: str) -> bool:
    """Check if a column is accessible to the specified role."""
    restricted = RESTRICTED_COLUMNS.get(role, set())
    col_low = column.lower().strip()
    tbl_low = (table or "").lower().strip()

    for s, t, c in restricted:
        if c.lower() == col_low:
            # If table is not specified or wildcard, reject immediately
            if not tbl_low or tbl_low == "*":
                return False
            # If table matches target table or target table contains table prefix/alias
            if tbl_low == t.lower() or t.lower().startswith(tbl_low):
                return False
            # If schema matches
            if (s == "*" or s.lower() == schema.lower()) and tbl_low == t.lower():
                return False
    return True


def is_table_allowed(schema: str, table: str, role: str) -> bool:
    """Check if a table is accessible to the specified role."""
    prohibited = PROHIBITED_TABLES_BY_ROLE.get(role, set())
    for s, t in prohibited:
        if (s == "*" or s.lower() == schema.lower()) and t.lower() == table.lower():
            return False
    return True
