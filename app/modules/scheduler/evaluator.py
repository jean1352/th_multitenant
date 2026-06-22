import enum
import importlib
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy import select, func, and_, or_, JSON, ForeignKey
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

class AdvancedConditionEvaluator:
    @staticmethod
    def get_model_by_name(model_name: str) -> Any:
        """
        Dynamically imports and returns a model class by name.
        """
        modules_to_search = [
            "app.modules.auth.models",
            "app.modules.organization.models",
            "app.modules.recruitment.models",
            "app.modules.employees.models",
            "app.modules.trainings.models",
            "app.modules.notifications.models",
            "app.modules.calendar.models",
            "app.modules.benefits.models",
            "app.modules.disciplinary.models",
            "app.modules.dietary.models",
            "app.modules.scheduler.models",
            "app.modules.tenants.models",
        ]
        
        # Normalize name (e.g. event_enrollments -> EventEnrollment)
        name = model_name
        if "_" in name and not name[0].isupper():
            parts = name.split("_")
            name = "".join(p.capitalize() for p in parts)
            
        # Singularize common names
        if name.endswith("s") and not name.endswith("status") and not name.endswith("process"):
            if name == "Vacancies": name = "Vacancy"
            elif name == "Contracts": name = "Contract"
            elif name == "Employees": name = "Employee"
            elif name == "EventEnrollments": name = "EventEnrollment"
            elif name == "DietaryRestrictions": name = "DietaryRestriction"
            
        for module_path in modules_to_search:
            try:
                mod = importlib.import_module(module_path)
                model = getattr(mod, name, None)
                if model:
                    return model
            except ImportError:
                continue
                
        # Fallback search inside imported modules if still not found
        raise ValueError(f"Model {model_name} (normalized to {name}) not found in the application.")

    @classmethod
    def get_operator_filter(cls, column: Any, operator: str, value: Any) -> Any:
        """
        Maps simple string operator to SQLAlchemy filter expressions.
        """
        op = operator.lower()
        if op == "==":
            return column == value
        elif op == "!=":
            return column != value
        elif op == ">":
            return column > value
        elif op == "<":
            return column < value
        elif op == ">=":
            return column >= value
        elif op == "<=":
            return column <= value
        elif op == "like":
            return column.ilike(f"%{value}%")
        elif op == "days_ago_greater_than":
            target_date = datetime.now() - timedelta(days=int(value))
            return column < target_date
        elif op == "days_ago_less_than":
            target_date = datetime.now() - timedelta(days=int(value))
            return column > target_date
        elif op == "days_ago_equals":
            from sqlalchemy import Date, cast
            target_date = datetime.now() - timedelta(days=int(value))
            return cast(column, Date) == target_date.date()
        else:
            raise ValueError(f"Unsupported operator: {operator}")

    @classmethod
    def resolve_field_path(
        cls, base_model: Any, field_path: str, query: Any, joined_relations: set
    ) -> Tuple[Any, Any, Any]:
        """
        Resolves a dotted path like 'employee.position.area.name' starting from base_model.
        Returns (resolved_column, updated_query, updated_joined_relations)
        """
        parts = field_path.split(".")
        current_model = base_model
        
        # Loop through relationships
        for part in parts[:-1]:
            # Get the relationship attribute from current_model
            rel_attr = getattr(current_model, part, None)
            if rel_attr is None:
                raise AttributeError(f"Model {current_model.__name__} has no attribute {part}")
            
            # Get the target model of the relationship
            target_model = rel_attr.property.mapper.class_
            
            # Join if not already joined in this query
            join_key = (current_model, target_model, part)
            if join_key not in joined_relations:
                query = query.join(rel_attr)
                joined_relations.add(join_key)
                
            current_model = target_model
            
        # Get the final column
        col_name = parts[-1]
        column = getattr(current_model, col_name, None)
        if column is None:
            raise AttributeError(f"Model {current_model.__name__} has no column {col_name}")
            
        return column, query, joined_relations

    @classmethod
    def build_conditions(
        cls, base_model: Any, query: Any, condition_node: Dict[str, Any], joined_relations: set
    ) -> Tuple[Any, Any, set]:
        """
        Recursively translates a JSON rule node into SQLAlchemy filters and joins.
        """
        operator = condition_node.get("operator", "AND").upper()
        
        if operator in ("AND", "OR"):
            rules = condition_node.get("rules", [])
            filters = []
            for rule in rules:
                if "operator" in rule and ("rules" in rule or "filter" in rule):
                    # Nested condition group or aggregation
                    sub_filter, query, joined_relations = cls.build_conditions(
                        base_model, query, rule, joined_relations
                    )
                    if sub_filter is not None:
                        filters.append(sub_filter)
                else:
                    # Base rule
                    field = rule.get("field")
                    op = rule.get("operator")
                    val = rule.get("value")
                    
                    column, query, joined_relations = cls.resolve_field_path(
                        base_model, field, query, joined_relations
                    )
                    filters.append(cls.get_operator_filter(column, op, val))
                    
            if not filters:
                return None, query, joined_relations
                
            combined_filter = and_(*filters) if operator == "AND" else or_(*filters)
            return combined_filter, query, joined_relations
            
        elif operator == "AGGREGATE":
            agg_func_name = condition_node.get("aggregate_func", "COUNT").upper()
            target_table_name = condition_node.get("target_table")
            joins = condition_node.get("joins", [])
            filter_rule = condition_node.get("filter", {})
            having_cond = condition_node.get("having", {})

            target_model = cls.get_model_by_name(target_table_name)
            
            # Start correlated subquery
            link_col = None
            for fk in target_model.__table__.foreign_keys:
                if fk.column.table == base_model.__table__:
                    link_col = getattr(target_model, fk.parent.name)
                    break
            
            if link_col is not None:
                # Correlated subquery
                correlated_col = getattr(base_model, "id")
                stmt = select(func.count()).select_from(target_model).where(link_col == correlated_col)
                
                for join_relation in joins:
                    stmt = stmt.join(getattr(target_model, join_relation))
                    
                if filter_rule:
                    field = filter_rule.get("field")
                    op = filter_rule.get("operator")
                    val = filter_rule.get("value")
                    col, stmt, _ = cls.resolve_field_path(
                        target_model, field, stmt, set()
                    )
                    stmt = stmt.where(cls.get_operator_filter(col, op, val))
                
                having_op = having_cond.get("operator")
                having_val = having_cond.get("value")
                
                scalar_sub = stmt.scalar_subquery()
                combined_filter = cls.get_operator_filter(scalar_sub, having_op, having_val)
                return combined_filter, query, joined_relations
            else:
                # Direct aggregate query on the target model itself
                having_op = having_cond.get("operator")
                having_val = having_cond.get("value")
                query = query.group_by(target_model.id)
                having_filter = cls.get_operator_filter(func.count(target_model.id), having_op, having_val)
                query = query.having(having_filter)
                return None, query, joined_relations
                
        return None, query, joined_relations

    @classmethod
    def extract_fields(cls, node: Dict[str, Any]) -> List[str]:
        """
        Recursively extracts field paths from condition nodes.
        """
        fields = []
        if not node:
            return fields
        if "field" in node:
            fields.append(node["field"])
        if "rules" in node:
            for rule in node["rules"]:
                fields.extend(cls.extract_fields(rule))
        if "filter" in node:
            fields.extend(cls.extract_fields(node["filter"]))
        return fields

    @classmethod
    def extract_fields_from_templates(cls, actions: List[Dict[str, Any]]) -> List[str]:
        """
        Extracts variable placeholders and destination paths from action nodes.
        """
        fields = []
        if not actions:
            return fields
        for action in actions:
            for key in ["subject", "body", "to"]:
                template = action.get(key, "")
                if template:
                    if key == "to" and "@" not in template:
                        fields.append(template)
                    else:
                        placeholders = re.findall(r"\{([^}]+)\}", template)
                        fields.extend(placeholders)
        return fields

    @classmethod
    def apply_eager_loads(cls, base_model: Any, query: Any, field_paths: List[str]) -> Any:
        """
        Automatically adds nested joinedload options for all relations referenced in dotted paths.
        """
        for path in field_paths:
            parts = path.split(".")
            if len(parts) > 1:
                rel_parts = parts[:-1]
                try:
                    opt = joinedload(getattr(base_model, rel_parts[0]))
                    curr_model = getattr(base_model, rel_parts[0]).property.mapper.class_
                    for part in rel_parts[1:]:
                        opt = opt.joinedload(getattr(curr_model, part))
                        curr_model = getattr(curr_model, part).property.mapper.class_
                    query = query.options(opt)
                except Exception:
                    continue
        return query

    @classmethod
    async def evaluate_rule(cls, db: AsyncSession, rule: Any) -> List[Any]:
        """
        Runs the dynamic evaluator for an AutomationRule and returns the matching ORM records.
        """
        conditions = rule.conditions
        if not conditions:
            return []

        # Find starting base model
        model_name = conditions.get("model") or conditions.get("target_table")
        if not model_name:
            if rule.rule_type == "vacancy_stagnation" or rule.rule_type == "vacancy_weekly_report" or rule.rule_type == "sla_daily_check":
                model_name = "Vacancy"
            elif rule.rule_type == "event_reminder":
                model_name = "EventEnrollment"
            elif rule.rule_type == "contract_expiration":
                model_name = "Contract"
            elif rule.rule_type == "probation_end":
                model_name = "Employee"
            else:
                raise ValueError("No model specified in rules and could not infer target table.")

        base_model = cls.get_model_by_name(model_name)
        
        query = select(base_model)
        
        # Extract and apply automatic eager loads
        field_paths = cls.extract_fields(conditions)
        if rule.actions:
            field_paths.extend(cls.extract_fields_from_templates(rule.actions))
        query = cls.apply_eager_loads(base_model, query, field_paths)

        joined_relations = set()
        where_clause, query, joined_relations = cls.build_conditions(
            base_model, query, conditions, joined_relations
        )
        
        if where_clause is not None:
            query = query.where(where_clause)
            
        result = await db.execute(query)
        return result.scalars().unique().all()

class ActionExecutor:
    @classmethod
    async def execute_actions(cls, db: AsyncSession, rule: Any, entities: List[Any]) -> int:
        """
        Executes actions defined in an AutomationRule for the matching entity records.
        """
        actions = rule.actions or []
        if not actions or not entities:
            return 0
            
        from app.modules.notifications.service import send_email_notification
        import logging
        logger = logging.getLogger(__name__)
        
        count = 0
        for entity in entities:
            for action in actions:
                action_type = action.get("type", "").upper()
                if action_type == "EMAIL":
                    to_field = action.get("to")
                    subject_template = action.get("subject", "")
                    body_template = action.get("body", "")
                    is_html = action.get("is_html", False)
                    
                    recipient_email = None
                    if to_field:
                        if "@" in to_field:
                            recipient_email = to_field
                        else:
                            val = entity
                            for part in to_field.split("."):
                                if val is not None:
                                    val = getattr(val, part, None)
                            recipient_email = str(val) if val is not None else None
                            
                    if not recipient_email:
                        logger.warning(f"Could not resolve recipient for action {action} on {entity}")
                        continue
                        
                    subject = cls.interpolate_template(subject_template, entity)
                    body = cls.interpolate_template(body_template, entity)
                    
                    try:
                        await send_email_notification(db, recipient_email, subject, body, is_html=is_html)
                        count += 1
                    except Exception as e:
                        logger.error(f"Error executing email action for rule {rule.id}: {e}")
                        
                elif action_type == "NOTIFICATION":
                    pass
        return count

    @classmethod
    def interpolate_template(cls, template: str, entity: Any) -> str:
        """
        Interpolates template variables like {employee.full_name} with values from the entity.
        """
        placeholders = re.findall(r"\{([^}]+)\}", template)
        result = template
        for placeholder in placeholders:
            val = entity
            for part in placeholder.split("."):
                if val is not None:
                    val = getattr(val, part, None)
            val_str = str(val) if val is not None else ""
            result = result.replace(f"{{{placeholder}}}", val_str)
        return result
