"""GenericRenderer — default renderer that converts a dictionary to natural language facts.

Recursive structured renderer with depth/item limits to prevent context overflow.
"""
from nexus.artifacts.renderers.base import ArtifactRenderer


class GenericRenderer(ArtifactRenderer):
    """Default renderer that formats typed artifact data as indented key-value facts."""

    def render(self, data: dict, depth: int = 0, max_depth: int = 2, max_items: int = 10) -> str:
        if not data or depth > max_depth:
            return ""
        lines = []
        prefix = "  " * depth

        items = list(data.items())
        for key, value in items[:max_items]:
            if value is None or value == "":
                continue
            formatted_key = key.replace("_", " ").title()

            if isinstance(value, dict):
                lines.append(f"{prefix}{formatted_key}:")
                rendered = self.render(value, depth + 1, max_depth, max_items)
                if rendered:
                    lines.append(rendered)
            elif isinstance(value, list):
                lines.append(f"{prefix}{formatted_key}:")
                for item in value[:max_items]:
                    if isinstance(item, dict):
                        lines.append(self.render(item, depth + 1, max_depth, max_items))
                    else:
                        item_str = str(item)
                        if len(item_str) > 100:
                            item_str = item_str[:100] + "..."
                        lines.append(f"{prefix}- {item_str}")
                if len(value) > max_items:
                    remaining = len(value) - max_items
                    lines.append(f"{prefix}  ... ({remaining} more items)")
            else:
                value_str = str(value)
                if len(value_str) > 200:
                    value_str = value_str[:200] + "..."
                lines.append(f"{prefix}{formatted_key}: {value_str}")

        if depth == 0 and len(items) > max_items:
            remaining = len(items) - max_items
            lines.append(f"... ({remaining} more fields)")

        return "\n".join(lines)
