import sys
sys.path.insert(0, 'backend')
from app.services.llm_provider import LLMProvider
from app.services.sql_safety import SQLPolicyEngine
from app.services.sql_generator import SQLGenerator
from app.services.schema_service import SchemaService
from app.database import get_default_target_engine
from app.services.query_executor import QueryExecutor

llm = LLMProvider.from_settings()
policy = SQLPolicyEngine.from_settings()
engine = get_default_target_engine()
executor = QueryExecutor.from_settings()
schema_svc = SchemaService()
schema = schema_svc.discover_schema(engine, 'default', 'sales')
schema_ctx = schema_svc.format_schema_for_llm(schema)

repair_prompt = f"""{schema_ctx}

The following SQL was generated for the question: "Which sales rep has generated the most revenue?"

GENERATED SQL:
SELECT s.sales_rep, SUM(s.quantity * s.unit_price * (1 - s.discount_pct / 100)) AS total_revenue FROM sales.sales_order_items s JOIN sales.sales_orders o ON s.order_id = o.order_id GROUP BY s.sales_rep ORDER BY total_revenue DESC LIMIT 1

POSTGRESQL EXECUTION ERROR:
column s.sales_rep does not exist. HINT: Perhaps you meant to reference the column "o.sales_rep".

Fix the SQL so that it uses the correct table alias for each column.
Respond with a JSON object containing "sql", "explanation", "tables_used", and "assumptions"."""

resp = llm.generate(prompt=repair_prompt, system_prompt="You are a precise SQL analyst. Respond with JSON.", json_mode=True)
print("Repair response content:", resp.content)
