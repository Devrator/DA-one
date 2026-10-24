"""SQL generation service — translates natural language to SQL using the LLM.

Uses the approved open-weight model via the LLM provider abstraction.
Includes structured prompts, query planning, and bounded repair.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Any

from app.services.llm_provider import LLMProvider, LLMResponse
from app.services.sql_safety import SQLPolicyEngine, PolicyResult
from app.schemas import SchemaResponse

logger = logging.getLogger(__name__)

# Maximum repair attempts to prevent infinite loops
MAX_REPAIR_ATTEMPTS = 2

SYSTEM_PROMPT = """You are a precise SQL analyst. Your job is to translate natural language questions into PostgreSQL queries.

RULES:
1. Generate ONLY valid PostgreSQL SELECT queries.
2. NEVER generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or any data-modifying statement.
3. Use ONLY the tables and columns provided in the schema context. Never invent tables or columns. If a table or column has been renamed in the schema context (e.g. 'sales.products' or 'discount_rate'), you MUST use the new table and column name shown in the schema context.
4. Always qualify column names with the EXACT table alias of the table that actually defines that column in the schema. Specifically:
   - 'sales_rep', 'order_date', 'status', 'region_id', 'customer_id' belong to 'sales.sales_orders'. (There is NO 'total_amount' or 'product_id' column on sales_orders).
   - 'quantity', 'unit_price', 'product_id' belong to 'sales.sales_order_items' (along with the active discount column, e.g. 'discount_pct' or 'discount_rate').
   - 'company_name', 'contact_name', 'segment' belong to 'sales.customers'. (There is NO 'customer_name' or 'customer_segment' column; use company_name and segment).
   - 'product_name', 'category' belong to the active products table ('sales.product_catalog' or 'sales.products' as defined in the schema).

5. For revenue calculations: revenue = quantity * unit_price * (1 - active_discount / 100) using whichever discount column is defined in the schema (e.g. discount_pct or discount_rate). Do NOT join sales.returns or subtract refunds unless the question explicitly asks for net revenue or return refunds.
6. In PostgreSQL, string comparisons are case-sensitive and database values are lowercase. Always use lowercase for status values (e.g. 'completed', 'cancelled', 'pending', 'returned') or use LOWER(status) = 'completed'. NEVER use uppercase 'Completed' or 'Cancelled'.
7. For average order value (AOV): calculate total revenue per order in a subquery or CTE (grouping by order_id: SUM(quantity * unit_price * (1 - discount_pct/100))), then take the AVG() of those order totals. Do NOT take the average of individual item rows.
8. For monthly revenue by region: GROUP BY r.region_name, EXTRACT(MONTH FROM o.order_date) (or region_id, month).
9. For regional targets vs actual sales: compute actuals in a CTE grouped by region_id, compute targets in a CTE grouped by region_id, and outer join with sales.regions on region_id using COALESCE(target, 0) and COALESCE(actual_sales, 0).
10. For return rate by product category: total items = COUNT(i.item_id) in that category; returns = COUNT(r.return_id) matching items in that category; return_rate_pct = ROUND(COALESCE(returns, 0)::numeric / total_items * 100, 2).
11. MULTI-TURN CONVERSATIONS: When answering a follow-up question (e.g. "Now only for 2026", "Compare it with 2025", "What about in the South region?"), preserve the metric, dimensions, and joins from the prior turn while updating the requested filter, grouping, or comparison.
12. AMBIGUITY & CLARIFICATION: If the question is ambiguous, lacks critical context (e.g. "What about the other one?", "Show me more details" with multiple possible interpretations), or asks for undefined business terms, respond with needs_clarification: true and a specific clarification_question.
13. If the question cannot be answered with the available schema or asks for restricted data not present in the schema, respond with needs_clarification: true and explain the limitation.
14. Add a LIMIT clause for result sets that could be large. When ranking the top items without an explicit number, use LIMIT 5.

RESPONSE FORMAT:
Respond with a JSON object with these fields:
{
  "sql": "YOUR SQL QUERY HERE",
  "explanation": "Brief explanation of what this query does",
  "tables_used": ["table1", "table2"],
  "assumptions": ["any assumptions made"],
  "needs_clarification": false,
  "clarification_question": null
}

If clarification is needed:
{
  "sql": null,
  "explanation": "Why clarification is needed",
  "needs_clarification": true,
  "clarification_question": "What specific clarification is needed?"
}"""



@dataclass
class GenerationResult:
    """Result of SQL generation from natural language."""
    success: bool
    sql: Optional[str] = None
    explanation: Optional[str] = None
    tables_used: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    model_name: Optional[str] = None
    generation_time_ms: float = 0.0
    repair_attempts: int = 0
    error: Optional[str] = None
    raw_response: Optional[str] = None


class SQLGenerator:
    """Generates SQL from natural language using the LLM."""

    def __init__(self, llm: LLMProvider, policy_engine: SQLPolicyEngine):
        self.llm = llm
        self.policy = policy_engine

    def generate(
        self,
        question: str,
        schema_context: str,
        conversation_context: list[dict] | None = None,
        role: str = "executive",
    ) -> GenerationResult:
        """Generate and validate SQL for a natural language question.

        Args:
            question: The user's natural language question.
            schema_context: Formatted schema information.
            conversation_context: Prior conversation for follow-ups.
            role: The active user role for column and table permission enforcement.

        Returns:
            GenerationResult with the generated SQL or error/clarification.
        """
        start_time = time.time()

        # Build the user prompt
        user_prompt = self._build_prompt(question, schema_context, conversation_context, role=role)

        # Generate SQL
        llm_response = self.llm.generate(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=512,
            json_mode=True,
        )

        if not llm_response.success:
            return GenerationResult(
                success=False,
                error=llm_response.error or "Model inference failed",
                model_name=llm_response.model,
                generation_time_ms=(time.time() - start_time) * 1000,
            )

        # Parse the LLM response
        parsed = self._parse_response(llm_response.content)
        if parsed is None:
            return GenerationResult(
                success=False,
                error="Failed to parse model response as JSON",
                model_name=llm_response.model,
                generation_time_ms=(time.time() - start_time) * 1000,
                raw_response=llm_response.content[:500],
            )

        # Check if clarification is needed
        if parsed.get("needs_clarification"):
            return GenerationResult(
                success=True,
                needs_clarification=True,
                clarification_question=parsed.get("clarification_question", "Could you provide more details?"),
                explanation=parsed.get("explanation"),
                model_name=llm_response.model,
                generation_time_ms=(time.time() - start_time) * 1000,
            )

        sql = parsed.get("sql")
        if not sql:
            return GenerationResult(
                success=False,
                error="Model did not generate SQL",
                explanation=parsed.get("explanation"),
                model_name=llm_response.model,
                generation_time_ms=(time.time() - start_time) * 1000,
            )

        # Validate SQL through policy engine with active role
        policy_result = self.policy.validate(sql, role=role)

        # If validation fails, attempt bounded repair
        repair_attempts = 0
        while not policy_result.allowed and repair_attempts < MAX_REPAIR_ATTEMPTS:
            repair_attempts += 1
            logger.info(
                "SQL repair attempt %d/%d: %s",
                repair_attempts, MAX_REPAIR_ATTEMPTS,
                "; ".join(policy_result.violations),
            )

            repair_result = self._attempt_repair(
                question=question,
                original_sql=sql,
                violations=policy_result.violations,
                schema_context=schema_context,
            )

            if repair_result and repair_result.get("sql"):
                sql = repair_result["sql"]
                policy_result = self.policy.validate(sql, role=role)
                parsed.update(repair_result)
            else:
                break

        elapsed = (time.time() - start_time) * 1000

        if not policy_result.allowed:
            return GenerationResult(
                success=False,
                sql=sql,
                error=f"Generated SQL failed validation: {'; '.join(policy_result.violations)}",
                model_name=llm_response.model,
                generation_time_ms=elapsed,
                repair_attempts=repair_attempts,
            )

        return GenerationResult(
            success=True,
            sql=policy_result.modified_sql or sql,
            explanation=parsed.get("explanation"),
            tables_used=parsed.get("tables_used", []),
            assumptions=parsed.get("assumptions", []),
            model_name=llm_response.model,
            generation_time_ms=elapsed,
            repair_attempts=repair_attempts,
        )

    def _build_prompt(
        self,
        question: str,
        schema_context: str,
        conversation_context: list[dict] | None = None,
        role: str = "executive",
    ) -> str:
        """Build the user prompt for SQL generation."""
        parts = [schema_context, ""]

        if conversation_context:
            conv_lines = ["PRIOR CONVERSATION TURNS (Use these to understand follow-ups, filters, and metrics):"]
            for i, ctx in enumerate(conversation_context[-3:], 1):
                conv_lines.append(f"  Turn {i} Question: {ctx.get('question', '')}")
                if ctx.get('sql'):
                    conv_lines.append(f"  Turn {i} Executed SQL: {ctx.get('sql')}")
                if ctx.get('active_filters'):
                    conv_lines.append(f"  Turn {i} Active Filters: {ctx.get('active_filters')}")
            parts.append("\n".join(conv_lines))
            parts.append("")

        parts.append(f"USER ROLE: {role.upper()}")
        parts.append(f"USER QUESTION: {question}")
        parts.append("")
        parts.append("Generate the SQL query as a JSON response.")

        return "\n".join(parts)

        return "\n".join(parts)

    def _parse_response(self, content: str) -> dict | None:
        """Parse the LLM response as JSON, with fallback extraction."""
        # Try direct JSON parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding a JSON object in the content
        brace_match = re.search(r'\{.*\}', content, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        # Last resort: try to extract SQL from plain text
        sql_match = re.search(r'(SELECT\s+.+?)(?:;|\Z)', content, re.DOTALL | re.IGNORECASE)
        if sql_match:
            return {
                "sql": sql_match.group(1).strip(),
                "explanation": "Extracted SQL from model response",
                "tables_used": [],
                "assumptions": [],
            }

        return None

    def _attempt_repair(
        self,
        question: str,
        original_sql: str,
        violations: list[str],
        schema_context: str,
    ) -> dict | None:
        """Attempt to repair invalid SQL by prompting the model with the errors."""
        repair_prompt = f"""{schema_context}

The following SQL was generated for the question: "{question}"

GENERATED SQL:
{original_sql}

VALIDATION ERRORS:
{chr(10).join(f'- {v}' for v in violations)}

Fix the SQL to address these validation errors. Use only tables and columns from the schema above.
Respond with a JSON object containing "sql", "explanation", "tables_used", and "assumptions"."""

        response = self.llm.generate(
            prompt=repair_prompt,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=512,
            json_mode=True,
        )

        if response.success:
            return self._parse_response(response.content)
        return None

    def attempt_execution_repair(
        self,
        question: str,
        original_sql: str,
        db_error: str,
        schema_context: str,
        role: str = "executive",
    ) -> GenerationResult:
        """Attempt to repair SQL that caused a database execution error."""
        start_time = time.time()
        repair_prompt = f"""{schema_context}

The following SQL query was generated for the question: "{question}"
under role {role.upper()} but failed during execution on PostgreSQL with this error:

GENERATED SQL:
{original_sql}

DATABASE ERROR:
{db_error}

Carefully examine the error and the schema above.
Fix the SQL so that it uses the correct table aliases and column locations.
Respond with a JSON object containing "sql", "explanation", "tables_used", and "assumptions"."""

        response = self.llm.generate(
            prompt=repair_prompt,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=512,
            json_mode=True,
        )

        elapsed = (time.time() - start_time) * 1000
        if not response.success:
            return GenerationResult(
                success=False,
                error=response.error or "Repair LLM inference failed",
                generation_time_ms=elapsed,
                repair_attempts=1,
            )

        parsed = self._parse_response(response.content)
        if not parsed or not parsed.get("sql"):
            return GenerationResult(
                success=False,
                error="Failed to parse repaired SQL from model",
                generation_time_ms=elapsed,
                repair_attempts=1,
            )

        repaired_sql = parsed["sql"]
        policy_res = self.policy.validate(repaired_sql, role=role)
        if not policy_res.allowed:
            return GenerationResult(
                success=False,
                sql=repaired_sql,
                error=f"Repaired SQL failed policy: {'; '.join(policy_res.violations)}",
                generation_time_ms=elapsed,
                repair_attempts=1,
            )

        return GenerationResult(
            success=True,
            sql=policy_res.modified_sql or repaired_sql,
            explanation=parsed.get("explanation"),
            tables_used=parsed.get("tables_used", []),
            assumptions=parsed.get("assumptions", []),
            model_name=response.model,
            generation_time_ms=elapsed,
            repair_attempts=1,
        )

