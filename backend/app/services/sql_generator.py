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
3. Use only the tables and columns provided in the schema context.
4. Do NOT invent tables, columns, or relationships that don't exist in the schema.
5. Use proper JOINs based on the foreign key relationships provided.
6. Use appropriate aggregations (SUM, COUNT, AVG, etc.) as needed.
7. Always qualify column names with table aliases when joining tables.
8. For revenue calculations: revenue = quantity * unit_price * (1 - discount_pct / 100)
9. For date filtering, use the date columns available in the schema.
10. Return results ordered meaningfully (by date, by value descending, etc.).
11. Add a LIMIT clause for result sets that could be large.
12. If the question cannot be answered with the available schema, respond with a JSON object containing "error" and "clarification_needed".

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
    ) -> GenerationResult:
        """Generate and validate SQL for a natural language question.

        Args:
            question: The user's natural language question.
            schema_context: Formatted schema information.
            conversation_context: Prior conversation for follow-ups.

        Returns:
            GenerationResult with the generated SQL or error/clarification.
        """
        start_time = time.time()

        # Build the user prompt
        user_prompt = self._build_prompt(question, schema_context, conversation_context)

        # Generate SQL
        llm_response = self.llm.generate(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
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

        # Validate SQL through policy engine
        policy_result = self.policy.validate(sql)

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
                policy_result = self.policy.validate(sql)
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
    ) -> str:
        """Build the user prompt for SQL generation."""
        parts = [schema_context, "", f"USER QUESTION: {question}"]

        if conversation_context:
            parts.insert(0, "CONVERSATION CONTEXT:")
            for ctx in conversation_context[-3:]:  # Last 3 exchanges max
                parts.insert(1, f"  Q: {ctx.get('question', '')}")
                parts.insert(2, f"  SQL: {ctx.get('sql', 'N/A')}")
            parts.insert(len(conversation_context[-3:]) + 1, "")

        parts.append("")
        parts.append("Generate the SQL query as a JSON response.")

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
            json_mode=True,
        )

        if response.success:
            return self._parse_response(response.content)
        return None
